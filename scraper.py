"""
The Harvester - Robust Job Scraper
==================================
Scrapes job listings from career portals with proper error handling,
rate limiting, and deduplication.

Usage:
    from scraper import JobScraper
    scraper = JobScraper()
    jobs = scraper.scrape()
"""

import csv
import json
import logging
import random
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    StaleElementReferenceException,
    WebDriverException
)

from config import SCRAPER_CONFIG, DATA_DIR, LOGS_DIR

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOGS_DIR / 'scraper.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


@dataclass
class JobListing:
    """Represents a single job listing."""
    jr_code: str  # Unique identifier
    title: str
    location: str
    department: str
    deep_link: str
    posted_date: Optional[str] = None
    scraped_at: str = ""

    def __post_init__(self):
        if not self.scraped_at:
            self.scraped_at = datetime.now().isoformat()


class JobScraper:
    """
    Robust job scraper with error handling and rate limiting.

    Features:
    - Headless Chrome with proper user-agent rotation
    - Handles infinite scroll / "Load More" buttons
    - Deduplication using JR Code
    - Automatic retries with exponential backoff
    - Respectful rate limiting
    """

    def __init__(self, config: dict = None):
        self.config = config or SCRAPER_CONFIG
        self.driver = None
        self.existing_jobs = self._load_existing_jobs()
        logger.info(f"Scraper initialized. {len(self.existing_jobs)} existing jobs loaded.")

    def _load_existing_jobs(self) -> set:
        """Load JR codes of already scraped jobs to avoid duplicates."""
        output_file = self.config["output_file"]
        existing = set()

        if Path(output_file).exists():
            try:
                with open(output_file, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if 'jr_code' in row:
                            existing.add(row['jr_code'])
                logger.info(f"Loaded {len(existing)} existing job codes for deduplication")
            except Exception as e:
                logger.warning(f"Could not load existing jobs: {e}")

        return existing

    def _get_random_user_agent(self) -> str:
        """Return a random user agent for rotation."""
        return random.choice(self.config["user_agents"])

    def _setup_driver(self) -> webdriver.Chrome:
        """Setup headless Chrome with stealth settings."""
        options = Options()

        # Headless mode
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")

        # Stealth settings to avoid detection
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument(f"user-agent={self._get_random_user_agent()}")
        options.add_argument("--window-size=1920,1080")

        # Performance optimizations
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-infobars")

        # Suppress logging
        options.add_experimental_option('excludeSwitches', ['enable-logging'])

        try:
            driver = webdriver.Chrome(options=options)
            driver.set_page_load_timeout(self.config["page_load_timeout"])

            # Additional stealth
            driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
                "source": """
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    })
                """
            })

            logger.info("Chrome driver initialized successfully")
            return driver

        except WebDriverException as e:
            logger.error(f"Failed to initialize Chrome driver: {e}")
            raise

    def _respectful_delay(self):
        """Add a polite delay between requests."""
        delay = self.config["request_delay"] + random.uniform(0.5, 1.5)
        time.sleep(delay)

    def _handle_infinite_scroll(self) -> int:
        """
        Handle infinite scroll / Load More button to get all jobs.
        Returns the number of scroll iterations performed.
        """
        scroll_count = 0
        last_height = self.driver.execute_script("return document.body.scrollHeight")
        max_attempts = self.config["max_scroll_attempts"]

        while scroll_count < max_attempts:
            # Try clicking "Load More" button if it exists
            try:
                load_more = self.driver.find_element(By.XPATH,
                    "//button[contains(text(), 'Load More') or contains(text(), 'Show More') or contains(@class, 'load-more')]"
                )
                if load_more.is_displayed() and load_more.is_enabled():
                    load_more.click()
                    logger.info(f"Clicked 'Load More' button (iteration {scroll_count + 1})")
                    time.sleep(self.config["scroll_pause_time"])
                    scroll_count += 1
                    continue
            except NoSuchElementException:
                pass
            except StaleElementReferenceException:
                pass

            # Scroll to bottom
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(self.config["scroll_pause_time"])

            # Check if we've reached the bottom
            new_height = self.driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                logger.info(f"Reached end of page after {scroll_count} scrolls")
                break

            last_height = new_height
            scroll_count += 1
            logger.debug(f"Scroll iteration {scroll_count}, height: {new_height}")

        return scroll_count

    def _extract_jobs_from_page(self) -> list[JobListing]:
        """
        Extract job listings from the current page.
        This method contains the CSS selectors - modify these if the site structure changes.
        """
        jobs = []

        # Common selectors for job listing sites - adjust as needed
        job_card_selectors = [
            ".job-card",
            ".job-listing",
            ".job-item",
            "[data-job-id]",
            ".career-item",
            ".vacancy-item",
            "article.job",
            ".job-post",
            ".position-card"
        ]

        job_cards = []
        for selector in job_card_selectors:
            try:
                cards = self.driver.find_elements(By.CSS_SELECTOR, selector)
                if cards:
                    job_cards = cards
                    logger.info(f"Found {len(cards)} jobs using selector: {selector}")
                    break
            except Exception:
                continue

        if not job_cards:
            # Try finding by common patterns in href
            try:
                links = self.driver.find_elements(By.XPATH, "//a[contains(@href, '/job/') or contains(@href, '/career/') or contains(@href, '/position/')]")
                logger.info(f"Found {len(links)} potential job links")
                # Process links differently
                for link in links:
                    try:
                        job = self._extract_job_from_link(link)
                        if job and job.jr_code not in self.existing_jobs:
                            jobs.append(job)
                    except Exception as e:
                        logger.debug(f"Could not extract job from link: {e}")
                return jobs
            except Exception as e:
                logger.warning(f"Alternative extraction also failed: {e}")

        for card in job_cards:
            try:
                job = self._extract_job_from_card(card)
                if job and job.jr_code not in self.existing_jobs:
                    jobs.append(job)
                    logger.debug(f"Extracted job: {job.title} ({job.jr_code})")
            except Exception as e:
                logger.warning(f"Failed to extract job from card: {e}")

        return jobs

    def _extract_job_from_card(self, card) -> Optional[JobListing]:
        """Extract job details from a single job card element."""
        try:
            # Title - try multiple selectors
            title = None
            title_selectors = [".job-title", ".title", "h2", "h3", "h4", "[class*='title']", "a"]
            for sel in title_selectors:
                try:
                    elem = card.find_element(By.CSS_SELECTOR, sel)
                    title = elem.text.strip()
                    if title:
                        break
                except NoSuchElementException:
                    continue

            # Location
            location = "Not Specified"
            location_selectors = [".location", ".job-location", "[class*='location']", "[class*='city']"]
            for sel in location_selectors:
                try:
                    elem = card.find_element(By.CSS_SELECTOR, sel)
                    location = elem.text.strip()
                    if location:
                        break
                except NoSuchElementException:
                    continue

            # Department
            department = "General"
            dept_selectors = [".department", ".job-department", "[class*='department']", "[class*='category']"]
            for sel in dept_selectors:
                try:
                    elem = card.find_element(By.CSS_SELECTOR, sel)
                    department = elem.text.strip()
                    if department:
                        break
                except NoSuchElementException:
                    continue

            # Deep link
            deep_link = ""
            try:
                link_elem = card.find_element(By.CSS_SELECTOR, "a")
                deep_link = link_elem.get_attribute("href") or ""
            except NoSuchElementException:
                pass

            # JR Code - try data attribute, URL, or generate from title
            jr_code = None
            try:
                jr_code = card.get_attribute("data-job-id") or card.get_attribute("data-id")
            except Exception:
                pass

            if not jr_code and deep_link:
                # Extract from URL (e.g., /job/12345 or ?id=12345)
                import re
                match = re.search(r'[/=](\d+)(?:[/?]|$)', deep_link)
                if match:
                    jr_code = match.group(1)

            if not jr_code:
                # Generate from title + location
                jr_code = f"{title[:20]}_{location[:10]}".replace(" ", "_").lower()

            if not title:
                return None

            return JobListing(
                jr_code=jr_code,
                title=title,
                location=location,
                department=department,
                deep_link=deep_link
            )

        except Exception as e:
            logger.debug(f"Failed to extract job from card: {e}")
            return None

    def _extract_job_from_link(self, link) -> Optional[JobListing]:
        """Extract basic job info from a link element."""
        try:
            href = link.get_attribute("href") or ""
            title = link.text.strip() or link.get_attribute("title") or ""

            if not title or not href:
                return None

            import re
            match = re.search(r'[/=](\d+)(?:[/?]|$)', href)
            jr_code = match.group(1) if match else f"link_{hash(href) % 100000}"

            return JobListing(
                jr_code=jr_code,
                title=title,
                location="See Details",
                department="General",
                deep_link=href
            )
        except Exception:
            return None

    def _save_jobs(self, jobs: list[JobListing], append: bool = True):
        """Save jobs to CSV file."""
        output_file = self.config["output_file"]
        output_file.parent.mkdir(parents=True, exist_ok=True)

        mode = 'a' if append and output_file.exists() else 'w'
        write_header = mode == 'w'

        try:
            with open(output_file, mode, newline='', encoding='utf-8') as f:
                fieldnames = ['jr_code', 'title', 'location', 'department', 'deep_link', 'posted_date', 'scraped_at']
                writer = csv.DictWriter(f, fieldnames=fieldnames)

                if write_header:
                    writer.writeheader()

                for job in jobs:
                    writer.writerow(asdict(job))
                    self.existing_jobs.add(job.jr_code)

            logger.info(f"Saved {len(jobs)} jobs to {output_file}")

            # Also save a JSON backup
            self._save_json_backup(jobs)

        except Exception as e:
            logger.error(f"Failed to save jobs: {e}")
            raise

    def _save_json_backup(self, jobs: list[JobListing]):
        """Save a JSON backup with timestamp."""
        archive_dir = self.config.get("archive_dir", DATA_DIR / "archive")
        archive_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = archive_dir / f"jobs_{timestamp}.json"

        try:
            with open(backup_file, 'w', encoding='utf-8') as f:
                json.dump([asdict(job) for job in jobs], f, indent=2, ensure_ascii=False)
            logger.debug(f"JSON backup saved to {backup_file}")
        except Exception as e:
            logger.warning(f"Could not save JSON backup: {e}")

    def scrape(self, url: str = None) -> list[JobListing]:
        """
        Main scraping method with full error handling.

        Args:
            url: Optional override URL to scrape

        Returns:
            List of new JobListing objects
        """
        target_url = url or self.config["target_url"]
        all_jobs = []
        max_retries = self.config["max_retries"]

        for attempt in range(max_retries):
            try:
                logger.info(f"Starting scrape attempt {attempt + 1}/{max_retries}")
                logger.info(f"Target URL: {target_url}")

                # Initialize driver
                self.driver = self._setup_driver()

                # Load the page
                logger.info("Loading page...")
                self.driver.get(target_url)
                self._respectful_delay()

                # Wait for page to load
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )

                # Handle infinite scroll
                logger.info("Handling infinite scroll...")
                self._handle_infinite_scroll()

                # Extract jobs
                logger.info("Extracting job listings...")
                all_jobs = self._extract_jobs_from_page()

                logger.info(f"Successfully extracted {len(all_jobs)} new jobs")
                break  # Success, exit retry loop

            except TimeoutException:
                logger.warning(f"Page load timeout on attempt {attempt + 1}")
                if attempt < max_retries - 1:
                    time.sleep(self.config["retry_delay"] * (attempt + 1))
            except WebDriverException as e:
                logger.error(f"WebDriver error on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(self.config["retry_delay"] * (attempt + 1))
            except Exception as e:
                logger.error(f"Unexpected error on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(self.config["retry_delay"] * (attempt + 1))
            finally:
                if self.driver:
                    try:
                        self.driver.quit()
                    except Exception:
                        pass
                    self.driver = None

        # Save results
        if all_jobs:
            self._save_jobs(all_jobs)
            logger.info(f"Scraping complete. {len(all_jobs)} new jobs saved.")
        else:
            logger.warning("No new jobs found in this scrape run.")

        return all_jobs

    def scrape_from_csv(self, csv_path: str) -> list[JobListing]:
        """
        Alternative: Load jobs from a manually exported CSV.
        Useful when scraping is blocked but you have a data export.

        Expected CSV columns: jr_code, title, location, department, deep_link
        """
        jobs = []
        try:
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get('jr_code') not in self.existing_jobs:
                        job = JobListing(
                            jr_code=row.get('jr_code', ''),
                            title=row.get('title', ''),
                            location=row.get('location', ''),
                            department=row.get('department', ''),
                            deep_link=row.get('deep_link', ''),
                            posted_date=row.get('posted_date', '')
                        )
                        jobs.append(job)

            if jobs:
                self._save_jobs(jobs)
            logger.info(f"Loaded {len(jobs)} jobs from CSV")
            return jobs

        except Exception as e:
            logger.error(f"Failed to load from CSV: {e}")
            raise


# Demo function for testing
def demo_scrape():
    """Quick demo/test of the scraper."""
    print("=" * 60)
    print("JOB SCRAPER DEMO")
    print("=" * 60)

    scraper = JobScraper()

    # For demo, we'll create some sample jobs
    sample_jobs = [
        JobListing(
            jr_code="BFL001",
            title="Sales Officer",
            location="Patna, Bihar",
            department="Sales",
            deep_link="https://example.com/job/001"
        ),
        JobListing(
            jr_code="BFL002",
            title="Collection Executive",
            location="Sheohar, Bihar",
            department="Collections",
            deep_link="https://example.com/job/002"
        ),
        JobListing(
            jr_code="BFL003",
            title="Branch Manager",
            location="Mumbai, Maharashtra",
            department="Operations",
            deep_link="https://example.com/job/003"
        ),
        JobListing(
            jr_code="BFL004",
            title="Credit Analyst",
            location="Sheohar, Bihar",
            department="Credit",
            deep_link="https://example.com/job/004"
        ),
        JobListing(
            jr_code="BFL005",
            title="Sales Officer",
            location="Sitamarhi, Bihar",
            department="Sales",
            deep_link="https://example.com/job/005"
        ),
    ]

    print(f"\nDemo: Saving {len(sample_jobs)} sample jobs...")
    scraper._save_jobs(sample_jobs, append=False)
    print(f"Jobs saved to: {SCRAPER_CONFIG['output_file']}")

    return sample_jobs


if __name__ == "__main__":
    # Run demo when executed directly
    demo_scrape()
