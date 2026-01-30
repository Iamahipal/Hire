#!/usr/bin/env python3
"""
BFL PeopleStrong FULL Scraper v2
================================
Properly extracts ALL job data from bflcareers.peoplestrong.com

Based on actual page structure:
- 7000+ jobs, 45 per page, paginated
- Each card has: Title, JR Code, Department, Location, Experience, Dates
- Pages: First, 1, 2, 3... Last

RUN THIS ON YOUR LOCAL MACHINE (needs Chrome)

Usage:
    python bfl_scraper_v2.py
    python bfl_scraper_v2.py --pages 5       # Only first 5 pages (for testing)
    python bfl_scraper_v2.py --headless       # Run without opening browser window
"""

import csv
import json
import re
import sys
import time
import argparse
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
    ElementClickInterceptedException,
)

try:
    from webdriver_manager.chrome import ChromeDriverManager
    USE_DRIVER_MANAGER = True
except ImportError:
    USE_DRIVER_MANAGER = False

# ==============================================================
# CONFIG
# ==============================================================
BASE_URL = "https://bflcareers.peoplestrong.com"
JOB_LIST_URL = f"{BASE_URL}/job/joblist"
JOBS_PER_PAGE = 45  # As shown on the site

OUTPUT_DIR = Path(__file__).parent / "bfl_output"
OUTPUT_DIR.mkdir(exist_ok=True)


def setup_driver(headless=False):
    """Setup Chrome driver."""
    options = Options()

    if headless:
        options.add_argument("--headless=new")

    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")

    if USE_DRIVER_MANAGER:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
    else:
        driver = webdriver.Chrome(options=options)

    driver.set_page_load_timeout(60)
    driver.implicitly_wait(5)
    return driver


def wait_for_cards(driver, timeout=15):
    """Wait for job cards to load on the page."""
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        time.sleep(3)  # Extra wait for Angular rendering
        return True
    except TimeoutException:
        return False


def get_total_jobs(driver):
    """Extract total job count from 'SHOWING 45 OF 7022' text."""
    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text
        match = re.search(r'OF\s+([\d,]+)', body_text)
        if match:
            total = int(match.group(1).replace(',', ''))
            return total
    except Exception:
        pass
    return 0


def get_total_pages(driver):
    """Figure out how many pages there are."""
    total_jobs = get_total_jobs(driver)
    if total_jobs > 0:
        pages = (total_jobs + JOBS_PER_PAGE - 1) // JOBS_PER_PAGE
        return pages, total_jobs

    # Fallback: try to find the last page button
    try:
        last_btn = driver.find_element(By.XPATH, "//*[text()='Last']")
        # Some sites put page count in URL or nearby
        return 0, 0
    except NoSuchElementException:
        return 0, 0


def extract_cards_from_page(driver):
    """
    Extract all job cards from the CURRENT page.

    Based on the actual BFL PeopleStrong structure:
    - Title (bold, top of card)
    - JR Code (e.g., JR00201544)
    - Department | Location line
    - Posted On / End Date line
    - Required Experience
    """
    jobs = []

    # Get all the text blocks that look like job cards
    # The page shows cards in a grid. Let's extract from the full page text
    # and parse structured blocks.

    # Method 1: Try to find card elements by common PeopleStrong selectors
    card_selectors = [
        "app-job-card",               # Angular component
        "[class*='job-card']",
        "[class*='jobCard']",
        "[class*='job_card']",
        "[class*='card-body']",
        ".card",
        "mat-card",                    # Angular Material
        "[class*='listing'] > div",
    ]

    cards = []
    for selector in card_selectors:
        try:
            found = driver.find_elements(By.CSS_SELECTOR, selector)
            if found and len(found) > 2:
                # Verify they contain JR codes
                sample_text = found[0].text
                if re.search(r'JR\d+', sample_text):
                    cards = found
                    break
        except Exception:
            continue

    # Method 2: Find cards by looking for JR code pattern
    if not cards:
        try:
            # Find all elements containing JR codes
            jr_elements = driver.find_elements(By.XPATH,
                "//*[contains(text(), 'JR00')]"
            )
            if jr_elements:
                # Go up to parent card container
                for jr_elem in jr_elements:
                    try:
                        # Walk up to find the card container
                        parent = jr_elem
                        for _ in range(5):
                            parent = parent.find_element(By.XPATH, "..")
                            parent_text = parent.text
                            # A good card container has JR code + experience + dates
                            if ('JR00' in parent_text and
                                ('Experience' in parent_text or 'Posted' in parent_text) and
                                ('Apply' in parent_text or 'Share' in parent_text)):
                                if parent not in cards:
                                    cards.append(parent)
                                break
                    except Exception:
                        continue
        except Exception:
            pass

    # Method 3: Parse from full page text (most reliable fallback)
    if not cards or len(cards) < 3:
        return extract_from_page_text(driver)

    # Extract data from each card
    for card in cards:
        try:
            job = parse_card_element(card)
            if job:
                jobs.append(job)
        except Exception as e:
            continue

    return jobs


def parse_card_element(card):
    """Parse a single card element into a job dict."""
    text = card.text.strip()
    if not text or 'JR00' not in text:
        return None

    lines = [l.strip() for l in text.split('\n') if l.strip()]

    job = {
        "jr_code": "",
        "title": "",
        "department": "",
        "location": "",
        "experience": "",
        "posted_date": "",
        "end_date": "",
        "skills": "",
        "deep_link": "",
    }

    for i, line in enumerate(lines):
        # JR Code line (e.g., "JR00201544")
        jr_match = re.match(r'^(JR\d+)$', line)
        if jr_match:
            job["jr_code"] = jr_match.group(1)
            # Title is usually the line BEFORE JR code
            if i > 0:
                job["title"] = lines[i - 1]
            continue

        # Department | Location line (e.g., "Risk | Pune Corporate Office - Fou...")
        # or "BFS Direct | Madurai"
        if '|' in line and 'Posted' not in line and 'End' not in line:
            parts = line.split('|')
            if len(parts) >= 2:
                job["department"] = parts[0].strip()
                job["location"] = parts[1].strip()
            continue

        # Posted On / End Date (e.g., "Posted On: 30 Jan 2026 | End Date: 30 Jan 2027")
        if 'Posted' in line:
            posted_match = re.search(r'Posted\s*On:\s*(.+?)(?:\||$)', line)
            if posted_match:
                job["posted_date"] = posted_match.group(1).strip()
            end_match = re.search(r'End\s*Date:\s*(.+?)$', line)
            if end_match:
                job["end_date"] = end_match.group(1).strip()
            continue

        # Experience (e.g., "8-10 years" or "1-3 years")
        exp_match = re.match(r'^(\d+[\s-]+\d*\s*years?)$', line, re.I)
        if exp_match:
            job["experience"] = exp_match.group(1)
            continue

        # Also try "Required Experience" followed by value
        if 'Required Experience' in line:
            continue  # The actual value is on the next line

        # Skills
        if 'SKILLS' in line.upper():
            job["skills"] = line
            continue

    # Try to get the Apply link
    try:
        link = card.find_element(By.XPATH, ".//a[contains(text(), 'Apply') or contains(@href, '/job/')]")
        job["deep_link"] = link.get_attribute("href") or ""
    except:
        pass

    # Try share link for deep link
    if not job["deep_link"]:
        try:
            share_btn = card.find_element(By.XPATH, ".//button[contains(text(), 'Share')]")
            # Sometimes clicking share reveals the URL
        except:
            pass

    # Construct deep link from JR code if not found
    if not job["deep_link"] and job["jr_code"]:
        job["deep_link"] = f"{BASE_URL}/job/joblist"

    return job if job["jr_code"] else None


def extract_from_page_text(driver):
    """
    Fallback: Parse jobs from the full page text using regex patterns.
    This handles cases where CSS selectors don't match.
    """
    jobs = []

    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text
    except Exception:
        return jobs

    # Split text into blocks using JR code as delimiter
    # Pattern: Title line, then JR code, then details
    blocks = re.split(r'(?=\b[A-Z][A-Za-z\s\-/]+\n\s*JR\d{5,})', body_text)

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        jr_match = re.search(r'(JR\d{5,})', block)
        if not jr_match:
            continue

        job = {
            "jr_code": jr_match.group(1),
            "title": "",
            "department": "",
            "location": "",
            "experience": "",
            "posted_date": "",
            "end_date": "",
            "skills": "",
            "deep_link": f"{BASE_URL}/job/joblist",
        }

        lines = [l.strip() for l in block.split('\n') if l.strip()]

        for i, line in enumerate(lines):
            # Title = line before JR code
            if line == job["jr_code"] and i > 0:
                job["title"] = lines[i - 1]

            # Department | Location
            if '|' in line and 'Posted' not in line and 'End' not in line and 'SHOWING' not in line:
                parts = line.split('|')
                if len(parts) >= 2:
                    job["department"] = parts[0].strip()
                    job["location"] = parts[1].strip()

            # Dates
            if 'Posted' in line:
                posted_match = re.search(r'Posted\s*On:\s*(.+?)(?:\||$)', line)
                if posted_match:
                    job["posted_date"] = posted_match.group(1).strip()
                end_match = re.search(r'End\s*Date:\s*(.+?)$', line)
                if end_match:
                    job["end_date"] = end_match.group(1).strip()

            # Experience
            exp_match = re.match(r'^(\d+[\s-]+\d*\s*years?)$', line, re.I)
            if exp_match:
                job["experience"] = line

        if job["title"]:
            jobs.append(job)

    return jobs


def go_to_next_page(driver, current_page):
    """Navigate to the next page."""
    next_page = current_page + 1

    try:
        # Method 1: Click the next page number
        page_btn = driver.find_element(By.XPATH,
            f"//a[text()='{next_page}'] | //button[text()='{next_page}'] | //*[contains(@class, 'page') and text()='{next_page}']"
        )
        driver.execute_script("arguments[0].scrollIntoView(true);", page_btn)
        time.sleep(0.5)
        driver.execute_script("arguments[0].click();", page_btn)
        time.sleep(3)
        return True
    except NoSuchElementException:
        pass

    try:
        # Method 2: Click the ">" (next) button
        next_btn = driver.find_element(By.XPATH,
            "//*[text()='>'] | //*[text()='Next'] | //*[text()='›'] | //*[contains(@class, 'next')]"
        )
        if next_btn.is_displayed() and next_btn.is_enabled():
            driver.execute_script("arguments[0].click();", next_btn)
            time.sleep(3)
            return True
    except NoSuchElementException:
        pass

    try:
        # Method 3: Modify the URL if it has page parameter
        current_url = driver.current_url
        if 'page=' in current_url:
            new_url = re.sub(r'page=\d+', f'page={next_page}', current_url)
        else:
            separator = '&' if '?' in current_url else '?'
            new_url = f"{current_url}{separator}page={next_page}"
        driver.get(new_url)
        time.sleep(3)
        return True
    except Exception:
        pass

    return False


def change_page_size(driver, size=100):
    """Try to change the 'SHOWING 45' dropdown to show more jobs per page."""
    try:
        # Look for the dropdown that says "45"
        dropdown = driver.find_element(By.XPATH,
            "//*[contains(text(), 'SHOWING')]/following::select[1] | //select[contains(@class, 'page-size')]"
        )
        from selenium.webdriver.support.ui import Select
        select = Select(dropdown)
        # Try to select the highest option
        options = [o.text for o in select.options]
        print(f"  Page size options: {options}")
        for opt in ['100', '75', '50']:
            if opt in options:
                select.select_by_visible_text(opt)
                time.sleep(3)
                return int(opt)
    except Exception:
        pass

    # Try clicking the "45" number to see if it's a clickable dropdown
    try:
        size_elem = driver.find_element(By.XPATH,
            "//*[contains(text(), 'SHOWING')]//*[text()='45']"
        )
        size_elem.click()
        time.sleep(1)
    except Exception:
        pass

    return JOBS_PER_PAGE


def save_results(all_jobs):
    """Save all jobs to CSV and JSON."""
    # Remove duplicates by JR code
    seen = set()
    unique_jobs = []
    for job in all_jobs:
        if job["jr_code"] not in seen:
            seen.add(job["jr_code"])
            unique_jobs.append(job)

    # CSV
    csv_path = OUTPUT_DIR / "bfl_jobs_complete.csv"
    fieldnames = [
        "jr_code", "title", "department", "location",
        "experience", "posted_date", "end_date", "skills",
        "deep_link", "scraped_at"
    ]

    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for job in unique_jobs:
            job["scraped_at"] = datetime.now().isoformat()
            writer.writerow({k: job.get(k, "") for k in fieldnames})

    # JSON
    json_path = OUTPUT_DIR / "bfl_jobs_complete.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(unique_jobs, f, indent=2, ensure_ascii=False)

    # Summary CSV
    dept_counts = {}
    loc_counts = {}
    for job in unique_jobs:
        d = job.get("department") or "Unknown"
        l = job.get("location") or "Unknown"
        dept_counts[d] = dept_counts.get(d, 0) + 1
        loc_counts[l] = loc_counts.get(l, 0) + 1

    summary_path = OUTPUT_DIR / "bfl_summary.csv"
    with open(summary_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["Category", "Name", "Job Count"])
        writer.writerow([])
        writer.writerow(["--- DEPARTMENT ---", "", ""])
        for dept, count in sorted(dept_counts.items(), key=lambda x: x[1], reverse=True):
            writer.writerow(["Department", dept, count])
        writer.writerow([])
        writer.writerow(["--- LOCATION ---", "", ""])
        for loc, count in sorted(loc_counts.items(), key=lambda x: x[1], reverse=True):
            writer.writerow(["Location", loc, count])

    return unique_jobs, csv_path, json_path, summary_path


def print_summary(jobs):
    """Print summary to console."""
    dept_counts = {}
    loc_counts = {}
    for job in jobs:
        d = job.get("department") or "Unknown"
        l = job.get("location") or "Unknown"
        dept_counts[d] = dept_counts.get(d, 0) + 1
        loc_counts[l] = loc_counts.get(l, 0) + 1

    print(f"\n{'=' * 60}")
    print(f"TOTAL UNIQUE JOBS: {len(jobs)}")
    print(f"{'=' * 60}")

    print(f"\nDepartments ({len(dept_counts)}):")
    for dept, count in sorted(dept_counts.items(), key=lambda x: x[1], reverse=True)[:20]:
        print(f"  {dept:<45} {count:>5}")

    print(f"\nTop Locations ({len(loc_counts)} total):")
    for loc, count in sorted(loc_counts.items(), key=lambda x: x[1], reverse=True)[:20]:
        print(f"  {loc:<45} {count:>5}")


def main():
    parser = argparse.ArgumentParser(description="BFL PeopleStrong Full Scraper")
    parser.add_argument("--pages", type=int, default=0, help="Max pages to scrape (0 = all)")
    parser.add_argument("--headless", action="store_true", help="Run headless (no browser window)")
    args = parser.parse_args()

    print("=" * 60)
    print("BFL PEOPLESTRONG FULL SCRAPER v2")
    print("=" * 60)
    print(f"Target: {JOB_LIST_URL}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    driver = None
    all_jobs = []

    try:
        # Setup
        print("[1/4] Setting up Chrome...")
        driver = setup_driver(headless=args.headless)

        # Load first page
        print("[2/4] Loading careers portal...")
        driver.get(JOB_LIST_URL)
        wait_for_cards(driver)

        # Get total count
        total_pages, total_jobs = get_total_pages(driver)
        print(f"  Found: {total_jobs} jobs across ~{total_pages} pages")

        # Try to increase page size
        actual_page_size = change_page_size(driver)
        if actual_page_size != JOBS_PER_PAGE:
            total_pages = (total_jobs + actual_page_size - 1) // actual_page_size
            print(f"  Changed page size to {actual_page_size}, now ~{total_pages} pages")

        max_pages = args.pages if args.pages > 0 else total_pages
        if max_pages == 0:
            max_pages = 200  # Safety limit

        print(f"  Will scrape: {max_pages} pages")

        # Scrape each page
        print(f"\n[3/4] Scraping jobs page by page...")

        for page in range(1, max_pages + 1):
            print(f"\n  --- Page {page}/{max_pages} ---")

            # Extract jobs from current page
            page_jobs = extract_cards_from_page(driver)

            if page_jobs:
                all_jobs.extend(page_jobs)
                print(f"  Extracted {len(page_jobs)} jobs (total so far: {len(all_jobs)})")

                # Show first job as sample
                if page == 1 and page_jobs:
                    j = page_jobs[0]
                    print(f"  Sample: {j['jr_code']} | {j['title']} | {j['department']} | {j['location']}")
            else:
                print(f"  No jobs found on this page. Stopping.")
                break

            # Navigate to next page
            if page < max_pages:
                success = go_to_next_page(driver, page)
                if not success:
                    print(f"  Could not navigate to page {page + 1}. Stopping.")
                    break
                wait_for_cards(driver)

        # Save results
        print(f"\n[4/4] Saving results...")
        unique_jobs, csv_path, json_path, summary_path = save_results(all_jobs)

        print(f"\n  CSV:     {csv_path}")
        print(f"  JSON:    {json_path}")
        print(f"  Summary: {summary_path}")

        # Print summary
        print_summary(unique_jobs)

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()

        # Save what we have so far
        if all_jobs:
            print(f"\nSaving {len(all_jobs)} jobs collected before error...")
            save_results(all_jobs)

        # Debug
        if driver:
            try:
                driver.save_screenshot(str(OUTPUT_DIR / "error_screenshot.png"))
                with open(OUTPUT_DIR / "error_page.html", 'w', encoding='utf-8') as f:
                    f.write(driver.page_source)
                print("Debug files saved.")
            except:
                pass

    finally:
        if driver:
            if not args.headless:
                input("\nPress Enter to close browser...")
            driver.quit()
            print("Browser closed.")


if __name__ == "__main__":
    main()
