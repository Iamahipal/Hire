#!/usr/bin/env python3
"""
BFL PeopleStrong Local Scraper
==============================
RUN THIS ON YOUR LOCAL MACHINE (not on a server).

The BFL careers portal blocks server IPs, but it works from local browsers.

Requirements:
    pip install selenium webdriver-manager pandas

Usage:
    python LOCAL_bfl_scraper.py
"""

import csv
import json
import time
import re
from datetime import datetime
from pathlib import Path

# ==========================================
# CONFIGURATION - MODIFY IF NEEDED
# ==========================================
BASE_URL = "https://bflcareers.peoplestrong.com"
OUTPUT_DIR = Path("./bfl_output")
OUTPUT_DIR.mkdir(exist_ok=True)

# ==========================================
# IMPORTS
# ==========================================
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from webdriver_manager.chrome import ChromeDriverManager
except ImportError:
    print("Missing dependencies! Run:")
    print("  pip install selenium webdriver-manager")
    exit(1)


def setup_driver(headless=False):
    """Setup Chrome driver."""
    options = Options()

    if headless:
        options.add_argument("--headless=new")

    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(60)

    return driver


def wait_for_jobs_load(driver, timeout=30):
    """Wait for job listings to load."""
    try:
        # Wait for Angular app to load
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )

        # Wait a bit more for dynamic content
        time.sleep(5)

        # Try to find job cards or listings
        selectors = [
            "[class*='job-card']",
            "[class*='job-list']",
            "[class*='vacancy']",
            ".card",
            "article",
        ]

        for selector in selectors:
            try:
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
                print(f"Found elements with: {selector}")
                return True
            except:
                continue

        return True  # Continue anyway

    except Exception as e:
        print(f"Warning: {e}")
        return False


def scroll_and_load(driver, max_scrolls=50):
    """Scroll to load all jobs."""
    print("Scrolling to load all jobs...")

    last_height = driver.execute_script("return document.body.scrollHeight")
    scroll_count = 0

    while scroll_count < max_scrolls:
        # Try to find and click "Load More" button
        load_more_found = False
        try:
            buttons = driver.find_elements(By.XPATH,
                "//*[contains(text(), 'Load More') or contains(text(), 'Show More') or contains(text(), 'View More')]"
            )
            for btn in buttons:
                if btn.is_displayed() and btn.is_enabled():
                    driver.execute_script("arguments[0].click();", btn)
                    print(f"  Clicked 'Load More' (scroll {scroll_count + 1})")
                    load_more_found = True
                    time.sleep(2)
                    break
        except:
            pass

        if not load_more_found:
            # Scroll down
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1.5)

        new_height = driver.execute_script("return document.body.scrollHeight")

        if new_height == last_height:
            print(f"  Reached end after {scroll_count} scrolls")
            break

        last_height = new_height
        scroll_count += 1

    return scroll_count


def extract_all_jobs(driver):
    """Extract all job listings."""
    jobs = []

    # Get page source for regex extraction
    page_source = driver.page_source

    # Method 1: Try to find job elements
    selectors = [
        "[class*='job-card']",
        "[class*='job-item']",
        "[class*='vacancy']",
        ".card[class*='job']",
        "div[class*='listing']",
    ]

    elements = []
    for selector in selectors:
        try:
            found = driver.find_elements(By.CSS_SELECTOR, selector)
            if found:
                print(f"Found {len(found)} elements with: {selector}")
                elements = found
                break
        except:
            continue

    # Method 2: Find all job links
    if not elements:
        print("Trying to find job links...")
        try:
            links = driver.find_elements(By.XPATH, "//a[contains(@href, '/job/') or contains(@href, '/career/')]")
            print(f"Found {len(links)} job links")

            seen_urls = set()
            for link in links:
                try:
                    href = link.get_attribute("href") or ""
                    title = link.text.strip()

                    if not href or href in seen_urls:
                        continue
                    if not title or len(title) < 3:
                        continue

                    seen_urls.add(href)

                    # Extract job ID
                    match = re.search(r'/job/(\d+)', href)
                    jr_code = f"JR_{match.group(1)}" if match else f"JOB_{len(jobs)}"

                    jobs.append({
                        "jr_code": jr_code,
                        "title": title,
                        "location": "",
                        "department": "",
                        "experience": "",
                        "employment_type": "",
                        "deep_link": href,
                    })
                except:
                    continue

        except Exception as e:
            print(f"Error finding links: {e}")

    # Method 3: Extract from visible text
    if not jobs:
        print("Extracting from page text...")
        body_text = driver.find_element(By.TAG_NAME, "body").text

        # Look for patterns in the text
        lines = body_text.split('\n')
        for i, line in enumerate(lines):
            line = line.strip()
            # Heuristic: Job titles often have specific patterns
            if re.search(r'(Officer|Manager|Executive|Analyst|Engineer|Lead|Head|Associate)', line, re.I):
                if len(line) > 5 and len(line) < 100:
                    jobs.append({
                        "jr_code": f"JOB_{len(jobs)}",
                        "title": line,
                        "location": "",
                        "department": "",
                        "experience": "",
                        "employment_type": "",
                        "deep_link": "",
                    })

    return jobs


def fetch_job_details(driver, jobs, max_fetch=100):
    """Fetch details for each job by visiting its page."""
    print(f"\nFetching details for {min(len(jobs), max_fetch)} jobs...")

    for i, job in enumerate(jobs[:max_fetch]):
        if not job.get("deep_link"):
            continue

        try:
            driver.get(job["deep_link"])
            time.sleep(2)

            # Wait for page load
            WebDriverWait(driver, 10).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )

            page_text = driver.find_element(By.TAG_NAME, "body").text

            # Extract location
            if not job["location"]:
                loc_match = re.search(r'(?:Location|City|Place)[:\s]*([A-Za-z\s,]+?)(?:\n|$)', page_text, re.I)
                if loc_match:
                    job["location"] = loc_match.group(1).strip()[:80]

            # Extract department
            if not job["department"]:
                dept_match = re.search(r'(?:Department|Function|Team)[:\s]*([A-Za-z\s&]+?)(?:\n|$)', page_text, re.I)
                if dept_match:
                    job["department"] = dept_match.group(1).strip()[:50]

            # Extract experience
            if not job["experience"]:
                exp_match = re.search(r'(?:Experience)[:\s]*(\d+[\s-]*(?:to|-)?\s*\d*\s*(?:years?|yrs?))', page_text, re.I)
                if exp_match:
                    job["experience"] = exp_match.group(1).strip()

            # Extract employment type
            if not job["employment_type"]:
                type_match = re.search(r'(?:Employment Type|Job Type)[:\s]*(Full[- ]?Time|Part[- ]?Time|Contract|Intern)', page_text, re.I)
                if type_match:
                    job["employment_type"] = type_match.group(1).strip()

            if (i + 1) % 10 == 0:
                print(f"  Fetched {i + 1}/{min(len(jobs), max_fetch)} job details...")

        except Exception as e:
            continue

    return jobs


def save_csv(jobs, filename="bfl_jobs_complete.csv"):
    """Save to CSV."""
    output_path = OUTPUT_DIR / filename

    fieldnames = [
        "jr_code", "title", "department", "location",
        "experience", "employment_type", "deep_link", "scraped_at"
    ]

    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for job in jobs:
            job["scraped_at"] = datetime.now().isoformat()
            row = {k: job.get(k, "") for k in fieldnames}
            writer.writerow(row)

    print(f"\n CSV saved: {output_path}")
    return output_path


def save_json(jobs, filename="bfl_jobs_complete.json"):
    """Save to JSON."""
    output_path = OUTPUT_DIR / filename

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(jobs, f, indent=2, ensure_ascii=False)

    print(f" JSON saved: {output_path}")
    return output_path


def print_summary(jobs):
    """Print summary statistics."""
    dept_counts = {}
    loc_counts = {}

    for job in jobs:
        dept = job.get("department") or "Unknown"
        loc = job.get("location") or "Unknown"
        dept_counts[dept] = dept_counts.get(dept, 0) + 1
        loc_counts[loc] = loc_counts.get(loc, 0) + 1

    print("\n" + "=" * 60)
    print(f"TOTAL JOBS: {len(jobs)}")
    print("=" * 60)

    print("\nBy Department:")
    for dept, count in sorted(dept_counts.items(), key=lambda x: x[1], reverse=True)[:15]:
        print(f"  {dept:<40} {count:>5}")

    print("\nBy Location:")
    for loc, count in sorted(loc_counts.items(), key=lambda x: x[1], reverse=True)[:15]:
        print(f"  {loc:<40} {count:>5}")


def main():
    """Main function."""
    print("=" * 60)
    print("BFL PEOPLESTRONG LOCAL SCRAPER")
    print("=" * 60)
    print(f"\nThis will open a Chrome browser to scrape {BASE_URL}")
    print("Make sure you have Chrome installed.\n")

    driver = None
    try:
        # Setup
        print("[1/5] Setting up Chrome browser...")
        driver = setup_driver(headless=False)  # Set to True for headless

        # Navigate to careers page
        print("[2/5] Loading BFL careers portal...")
        # Try common job listing URLs
        job_urls = [
            f"{BASE_URL}/job/joblist",
            f"{BASE_URL}/jobs",
            f"{BASE_URL}/careers",
            f"{BASE_URL}/#/job/joblist",
            f"{BASE_URL}/#/jobs",
        ]

        loaded = False
        for url in job_urls:
            try:
                driver.get(url)
                wait_for_jobs_load(driver)
                # Check if we got jobs page
                if "job" in driver.current_url.lower() or "career" in driver.current_url.lower():
                    print(f"  Loaded: {driver.current_url}")
                    loaded = True
                    break
            except:
                continue

        if not loaded:
            # Try main page and navigate
            driver.get(BASE_URL)
            wait_for_jobs_load(driver)

        # Scroll to load all
        print("[3/5] Loading all jobs (scrolling)...")
        scroll_and_load(driver)

        # Extract
        print("[4/5] Extracting job data...")
        jobs = extract_all_jobs(driver)
        print(f"  Found {len(jobs)} jobs")

        if jobs:
            # Get details
            print("[5/5] Fetching job details...")
            jobs = fetch_job_details(driver, jobs)

            # Save
            save_csv(jobs)
            save_json(jobs)

            # Summary
            print_summary(jobs)

        else:
            print("\nNo jobs found. Saving page for debugging...")
            debug_path = OUTPUT_DIR / "debug_page.html"
            with open(debug_path, 'w', encoding='utf-8') as f:
                f.write(driver.page_source)
            print(f"Page saved to: {debug_path}")

            # Take screenshot
            screenshot_path = OUTPUT_DIR / "debug_screenshot.png"
            driver.save_screenshot(str(screenshot_path))
            print(f"Screenshot saved to: {screenshot_path}")

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()

    finally:
        if driver:
            input("\nPress Enter to close browser...")
            driver.quit()


if __name__ == "__main__":
    main()
