#!/usr/bin/env python3
"""
BFL PeopleStrong Career Portal Scraper
======================================
Scrapes all job listings from https://bflcareers.peoplestrong.com/job/joblist
and exports to a structured CSV.
"""

import csv
import json
import time
import re
from datetime import datetime
from pathlib import Path

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
)

# Try to use webdriver_manager for automatic driver download
try:
    from webdriver_manager.chrome import ChromeDriverManager
    USE_DRIVER_MANAGER = True
except ImportError:
    USE_DRIVER_MANAGER = False

# Output paths
OUTPUT_DIR = Path(__file__).parent / "output" / "data"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TARGET_URL = "https://bflcareers.peoplestrong.com/job/joblist"


def setup_driver():
    """Setup headless Chrome."""
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    if USE_DRIVER_MANAGER:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
    else:
        driver = webdriver.Chrome(options=options)

    driver.set_page_load_timeout(60)
    return driver


def scroll_to_load_all(driver, max_scrolls=100):
    """Scroll page to load all jobs (handles infinite scroll / lazy loading)."""
    print("Scrolling to load all jobs...")

    last_height = driver.execute_script("return document.body.scrollHeight")
    scroll_count = 0

    while scroll_count < max_scrolls:
        # Try clicking "Load More" or "Show More" button if exists
        try:
            load_more_selectors = [
                "//button[contains(text(), 'Load More')]",
                "//button[contains(text(), 'Show More')]",
                "//button[contains(text(), 'View More')]",
                "//a[contains(text(), 'Load More')]",
                "//*[contains(@class, 'load-more')]",
                "//*[contains(@class, 'show-more')]",
            ]
            for selector in load_more_selectors:
                try:
                    btn = driver.find_element(By.XPATH, selector)
                    if btn.is_displayed():
                        btn.click()
                        print(f"  Clicked load more button (scroll {scroll_count + 1})")
                        time.sleep(2)
                        break
                except NoSuchElementException:
                    continue
        except Exception:
            pass

        # Scroll down
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1.5)

        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            # Try scrolling a bit more to trigger lazy load
            driver.execute_script("window.scrollBy(0, 500);")
            time.sleep(1)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                print(f"  Reached end after {scroll_count} scrolls")
                break

        last_height = new_height
        scroll_count += 1

        if scroll_count % 10 == 0:
            print(f"  Scrolled {scroll_count} times...")

    return scroll_count


def extract_jobs(driver):
    """Extract all job listings from the page."""
    jobs = []

    # Common selectors for PeopleStrong job cards
    job_card_selectors = [
        ".job-card",
        ".job-listing",
        ".job-item",
        ".career-card",
        ".vacancy-card",
        "[class*='job-card']",
        "[class*='jobCard']",
        "[class*='job_card']",
        "article",
        ".card",
    ]

    job_cards = []
    for selector in job_card_selectors:
        try:
            cards = driver.find_elements(By.CSS_SELECTOR, selector)
            if cards and len(cards) > 0:
                # Verify these are actually job cards by checking content
                sample_text = cards[0].text.lower()
                if any(kw in sample_text for kw in ['apply', 'location', 'experience', 'job', 'position']):
                    job_cards = cards
                    print(f"Found {len(cards)} job cards using selector: {selector}")
                    break
        except Exception:
            continue

    if not job_cards:
        # Try finding job links
        print("Trying alternative extraction via links...")
        try:
            links = driver.find_elements(By.XPATH, "//a[contains(@href, '/job/')]")
            print(f"Found {len(links)} job links")
            for link in links:
                try:
                    href = link.get_attribute("href") or ""
                    text = link.text.strip()
                    if text and href:
                        # Extract job ID from URL
                        match = re.search(r'/job/(\d+)', href)
                        jr_code = match.group(1) if match else f"JOB_{len(jobs)}"
                        jobs.append({
                            "jr_code": jr_code,
                            "title": text,
                            "location": "See Details",
                            "department": "General",
                            "experience": "",
                            "employment_type": "",
                            "deep_link": href,
                        })
                except Exception:
                    continue
            return jobs
        except Exception as e:
            print(f"Alternative extraction failed: {e}")

    # Extract from job cards
    for i, card in enumerate(job_cards):
        try:
            job = extract_job_from_card(card, i)
            if job:
                jobs.append(job)
        except Exception as e:
            print(f"  Error extracting job {i}: {e}")

    return jobs


def extract_job_from_card(card, index):
    """Extract job details from a single card element."""
    job = {
        "jr_code": "",
        "title": "",
        "location": "",
        "department": "",
        "experience": "",
        "employment_type": "",
        "posted_date": "",
        "deep_link": "",
    }

    # Get all text for debugging
    card_text = card.text

    # Title
    title_selectors = [".job-title", ".title", "h2", "h3", "h4", "[class*='title']", "a"]
    for sel in title_selectors:
        try:
            elem = card.find_element(By.CSS_SELECTOR, sel)
            title = elem.text.strip()
            if title and len(title) > 3:
                job["title"] = title
                break
        except NoSuchElementException:
            continue

    # Location
    location_selectors = [".location", "[class*='location']", "[class*='city']", "[class*='place']"]
    for sel in location_selectors:
        try:
            elem = card.find_element(By.CSS_SELECTOR, sel)
            job["location"] = elem.text.strip()
            break
        except NoSuchElementException:
            continue

    # Try to extract location from text if not found
    if not job["location"]:
        loc_match = re.search(r'(?:Location|City|Place)[:\s]*([A-Za-z\s,]+)', card_text, re.I)
        if loc_match:
            job["location"] = loc_match.group(1).strip()

    # Department
    dept_selectors = [".department", "[class*='department']", "[class*='category']", "[class*='function']"]
    for sel in dept_selectors:
        try:
            elem = card.find_element(By.CSS_SELECTOR, sel)
            job["department"] = elem.text.strip()
            break
        except NoSuchElementException:
            continue

    # Experience
    exp_selectors = ["[class*='experience']", "[class*='exp']"]
    for sel in exp_selectors:
        try:
            elem = card.find_element(By.CSS_SELECTOR, sel)
            job["experience"] = elem.text.strip()
            break
        except NoSuchElementException:
            continue

    # Try to extract experience from text
    if not job["experience"]:
        exp_match = re.search(r'(\d+[\s-]*(?:to|-)?\s*\d*\s*(?:years?|yrs?))', card_text, re.I)
        if exp_match:
            job["experience"] = exp_match.group(1).strip()

    # Deep link
    try:
        link = card.find_element(By.CSS_SELECTOR, "a")
        job["deep_link"] = link.get_attribute("href") or ""
    except NoSuchElementException:
        pass

    # JR Code - from URL or data attribute
    if job["deep_link"]:
        match = re.search(r'/job/(\d+)', job["deep_link"])
        if match:
            job["jr_code"] = f"JR_{match.group(1)}"

    if not job["jr_code"]:
        try:
            job["jr_code"] = card.get_attribute("data-job-id") or card.get_attribute("data-id") or f"JOB_{index}"
        except Exception:
            job["jr_code"] = f"JOB_{index}"

    # Only return if we have at least a title
    if job["title"]:
        return job
    return None


def save_to_csv(jobs, filename="bfl_jobs_master.csv"):
    """Save jobs to CSV with proper structure."""
    output_path = OUTPUT_DIR / filename

    fieldnames = [
        "jr_code",
        "title",
        "department",
        "location",
        "experience",
        "employment_type",
        "posted_date",
        "deep_link",
        "scraped_at"
    ]

    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for job in jobs:
            job["scraped_at"] = datetime.now().isoformat()
            writer.writerow({k: job.get(k, "") for k in fieldnames})

    print(f"\nSaved {len(jobs)} jobs to: {output_path}")
    return output_path


def save_summary(jobs, filename="bfl_jobs_summary.csv"):
    """Save summary by department and location."""
    output_path = OUTPUT_DIR / filename

    # Count by department
    dept_counts = {}
    location_counts = {}

    for job in jobs:
        dept = job.get("department", "Unknown") or "Unknown"
        loc = job.get("location", "Unknown") or "Unknown"

        dept_counts[dept] = dept_counts.get(dept, 0) + 1
        location_counts[loc] = location_counts.get(loc, 0) + 1

    # Write department summary
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["DEPARTMENT SUMMARY"])
        writer.writerow(["Department", "Job Count"])
        for dept, count in sorted(dept_counts.items(), key=lambda x: x[1], reverse=True):
            writer.writerow([dept, count])

        writer.writerow([])
        writer.writerow(["LOCATION SUMMARY"])
        writer.writerow(["Location", "Job Count"])
        for loc, count in sorted(location_counts.items(), key=lambda x: x[1], reverse=True):
            writer.writerow([loc, count])

    print(f"Saved summary to: {output_path}")

    # Print summary
    print("\n" + "=" * 60)
    print("DEPARTMENT SUMMARY")
    print("=" * 60)
    for dept, count in sorted(dept_counts.items(), key=lambda x: x[1], reverse=True)[:15]:
        print(f"  {dept:<40} {count:>5} jobs")

    print("\n" + "=" * 60)
    print("LOCATION SUMMARY (Top 15)")
    print("=" * 60)
    for loc, count in sorted(location_counts.items(), key=lambda x: x[1], reverse=True)[:15]:
        print(f"  {loc:<40} {count:>5} jobs")

    return output_path


def main():
    """Main scraping function."""
    print("=" * 60)
    print("BFL PEOPLESTRONG CAREER PORTAL SCRAPER")
    print("=" * 60)
    print(f"\nTarget: {TARGET_URL}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    driver = None
    try:
        print("\n[1/4] Setting up browser...")
        driver = setup_driver()

        print("[2/4] Loading career portal...")
        driver.get(TARGET_URL)
        time.sleep(5)  # Wait for initial load

        # Wait for page to be interactive
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )

        print("[3/4] Scrolling to load all jobs...")
        scroll_to_load_all(driver)

        print("[4/4] Extracting job data...")
        jobs = extract_jobs(driver)

        print(f"\n{'=' * 60}")
        print(f"EXTRACTION COMPLETE: {len(jobs)} jobs found")
        print(f"{'=' * 60}")

        if jobs:
            # Save main CSV
            save_to_csv(jobs)

            # Save summary
            save_summary(jobs)

            # Also save as JSON for flexibility
            json_path = OUTPUT_DIR / "bfl_jobs_master.json"
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(jobs, f, indent=2, ensure_ascii=False)
            print(f"Saved JSON to: {json_path}")
        else:
            print("No jobs extracted. The site structure may have changed.")
            print("Saving page source for debugging...")
            debug_path = OUTPUT_DIR / "page_source.html"
            with open(debug_path, 'w', encoding='utf-8') as f:
                f.write(driver.page_source)
            print(f"Page source saved to: {debug_path}")

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()

        if driver:
            # Save screenshot and page source for debugging
            try:
                debug_path = OUTPUT_DIR / "error_screenshot.png"
                driver.save_screenshot(str(debug_path))
                print(f"Screenshot saved to: {debug_path}")

                html_path = OUTPUT_DIR / "error_page.html"
                with open(html_path, 'w', encoding='utf-8') as f:
                    f.write(driver.page_source)
                print(f"Page HTML saved to: {html_path}")
            except Exception:
                pass

    finally:
        if driver:
            driver.quit()
            print("\nBrowser closed.")


if __name__ == "__main__":
    main()
