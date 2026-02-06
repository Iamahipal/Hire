#!/usr/bin/env python3
"""
BFL PeopleStrong DETAIL Scraper v5
==================================
FIXED: Stale element reference bug from v4.

Key fix: Instead of storing element references upfront (which become stale after
navigation), we now:
1. Get list of JR codes on the page
2. For EACH job: re-find the element fresh, click, extract, go back
3. This avoids stale references since elements are queried fresh each time

Usage:
    python bfl_scraper_v5.py --pages 1    # First page only (test)
    python bfl_scraper_v5.py --pages 5    # First 5 pages
    python bfl_scraper_v5.py              # All pages
"""

import csv
import json
import re
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

BASE_URL = "https://bflcareers.peoplestrong.com"
JOB_LIST_URL = f"{BASE_URL}/job/joblist"

OUTPUT_DIR = Path(__file__).parent / "bfl_output"
OUTPUT_DIR.mkdir(exist_ok=True)


def setup_driver(headless=False):
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
    driver.implicitly_wait(3)
    return driver


def wait_for_page(driver, timeout=15):
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        time.sleep(1.5)
        return True
    except TimeoutException:
        return False


def get_jr_codes_on_page(driver):
    """
    Get ONLY the list of JR codes on the current page.
    NO element references stored - this avoids stale element issues.
    """
    jr_codes = []

    try:
        # Find all JR code text elements
        jr_elements = driver.find_elements(By.XPATH,
            "//*[not(*)][contains(text(), 'JR00')]"
        )

        for el in jr_elements:
            try:
                text = el.text.strip()
                if re.match(r'^JR\d{5,}$', text):
                    if text not in jr_codes:  # Avoid duplicates
                        jr_codes.append(text)
            except:
                continue

    except Exception as e:
        print(f"  Error getting JR codes: {e}")

    return jr_codes


def find_and_click_job(driver, jr_code):
    """
    Find a job card by its JR code and click on it to open detail page.
    This is called FRESH for each job, avoiding stale references.
    Returns True if click successful, False otherwise.
    """
    try:
        # Find the JR code element
        jr_element = driver.find_element(By.XPATH,
            f"//*[not(*)][text()='{jr_code}']"
        )

        # Walk up to find the card container
        card = jr_element
        for _ in range(10):
            card = card.find_element(By.XPATH, "..")
            card_text = card.text
            if 'Apply' in card_text and 'Share' in card_text:
                break

        # Find clickable element in the card
        clickable = None

        # Try 1: Title link
        try:
            clickable = card.find_element(By.CSS_SELECTOR,
                "a[class*='title'], a[class*='job'], [class*='title'] a"
            )
        except NoSuchElementException:
            pass

        # Try 2: Any link with job/detail in href
        if not clickable:
            try:
                links = card.find_elements(By.CSS_SELECTOR, "a[href*='job'], a[href*='detail'], a[href*='apply']")
                if links:
                    clickable = links[0]
            except:
                pass

        # Try 3: H1-H4 headings (often clickable)
        if not clickable:
            try:
                clickable = card.find_element(By.CSS_SELECTOR, "h1, h2, h3, h4")
            except:
                pass

        # Try 4: Any link inside the card
        if not clickable:
            try:
                clickable = card.find_element(By.TAG_NAME, "a")
            except:
                pass

        # Try 5: Click the card itself
        if not clickable:
            clickable = card

        # Scroll into view and click
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", clickable)
        time.sleep(0.3)

        try:
            clickable.click()
        except ElementClickInterceptedException:
            driver.execute_script("arguments[0].click();", clickable)

        return True

    except Exception as e:
        # Retry with JavaScript approach
        try:
            js_click = f"""
            var allElements = document.querySelectorAll('*');
            for (var el of allElements) {{
                if (el.textContent.trim() === '{jr_code}' && el.children.length === 0) {{
                    // Found JR code, walk up to find card
                    var parent = el;
                    for (var i = 0; i < 10; i++) {{
                        parent = parent.parentElement;
                        if (!parent) break;
                        if (parent.textContent.includes('Apply') && parent.textContent.includes('Share')) {{
                            // Found card, look for clickable
                            var link = parent.querySelector('a');
                            if (link) {{
                                link.click();
                                return true;
                            }}
                            parent.click();
                            return true;
                        }}
                    }}
                }}
            }}
            return false;
            """
            result = driver.execute_script(js_click)
            return result
        except:
            return False


def extract_detail_page(driver):
    """
    Extract ALL job details from the current detail page.
    """
    job = {
        "jr_code": "",
        "title": "",
        "department": "",
        "location": "",
        "experience": "",
        "posted_date": "",
        "end_date": "",
        "skills": "",
        "description": "",
        "deep_link": driver.current_url,
    }

    # Wait for page content
    time.sleep(1.5)

    try:
        page_text = driver.find_element(By.TAG_NAME, "body").text
    except:
        page_text = ""

    # --- JR CODE ---
    jr_match = re.search(r'(JR\d{5,})', page_text)
    if jr_match:
        job["jr_code"] = jr_match.group(1)

    # --- JavaScript extraction for structured data ---
    js_extract = """
    var data = {};

    // Title - look for main heading
    var titleEl = document.querySelector(
        'h1, h2, [class*="job-title"], [class*="jobTitle"], [class*="position-title"]'
    );
    if (titleEl) {
        data.title = titleEl.textContent.trim();
    }

    // Get all body text
    var allText = document.body.innerText;

    // Department
    var deptMatch = allText.match(/Department\\s*[:\\|]\\s*([^\\n\\|]+)/i);
    if (deptMatch) data.department = deptMatch[1].trim();

    // Function/Business Unit (alternative for department)
    if (!data.department) {
        var funcMatch = allText.match(/(?:Function|Business\\s*Unit|Team)\\s*[:\\|]\\s*([^\\n\\|]+)/i);
        if (funcMatch) data.department = funcMatch[1].trim();
    }

    // Location
    var locMatch = allText.match(/Location\\s*[:\\|]\\s*([^\\n\\|]+)/i);
    if (locMatch) data.location = locMatch[1].trim();

    // City (alternative for location)
    if (!data.location) {
        var cityMatch = allText.match(/(?:City|Place|Office)\\s*[:\\|]\\s*([^\\n\\|]+)/i);
        if (cityMatch) data.location = cityMatch[1].trim();
    }

    // Experience
    var expMatch = allText.match(/(?:Experience|Exp\\.?)\\s*[:\\|]\\s*([^\\n]+)/i);
    if (expMatch) data.experience = expMatch[1].trim();

    // Also try "X-Y years" pattern anywhere
    if (!data.experience) {
        var expMatch2 = allText.match(/(\\d+\\s*[-–]\\s*\\d+\\s*years?)/i);
        if (expMatch2) data.experience = expMatch2[1].trim();
    }

    // Posted Date
    var postedMatch = allText.match(/Posted\\s*(?:On|Date)?\\s*[:\\|]?\\s*(\\d{1,2}\\s+\\w+\\s+\\d{4}|\\d{4}-\\d{2}-\\d{2})/i);
    if (postedMatch) data.posted_date = postedMatch[1].trim();

    // End Date
    var endMatch = allText.match(/End\\s*Date\\s*[:\\|]?\\s*(\\d{1,2}\\s+\\w+\\s+\\d{4}|\\d{4}-\\d{2}-\\d{2})/i);
    if (endMatch) data.end_date = endMatch[1].trim();

    // Skills
    var skillsMatch = allText.match(/(?:Skills|Key\\s*Skills|Qualifications)\\s*[:\\|]?\\s*([^\\n]{10,300})/i);
    if (skillsMatch) data.skills = skillsMatch[1].trim();

    // Description
    var descMatch = allText.match(/(?:Job\\s*Description|Description|About\\s*the\\s*Role|Responsibilities)\\s*[:\\|]?\\s*([\\s\\S]{10,500})/i);
    if (descMatch) data.description = descMatch[1].trim().substring(0, 500);

    // Look for structured detail elements
    var detailDivs = document.querySelectorAll('[class*="detail"], [class*="info"], [class*="field"], [class*="meta"]');
    for (var d of detailDivs) {
        var label = d.querySelector('[class*="label"], [class*="key"], strong, b, dt');
        var value = d.querySelector('[class*="value"], [class*="data"], span:last-child, dd');

        if (label && value) {
            var labelText = label.textContent.toLowerCase();
            var valueText = value.textContent.trim();

            if (labelText.includes('department') || labelText.includes('function')) {
                if (!data.department) data.department = valueText;
            }
            if (labelText.includes('location') || labelText.includes('city')) {
                if (!data.location) data.location = valueText;
            }
            if (labelText.includes('experience')) {
                if (!data.experience) data.experience = valueText;
            }
        }
    }

    return data;
    """

    try:
        extracted = driver.execute_script(js_extract)
        if extracted:
            for key in ["title", "department", "location", "experience",
                        "posted_date", "end_date", "skills", "description"]:
                if extracted.get(key) and not job[key]:
                    job[key] = extracted[key]
    except Exception as e:
        pass

    # --- Fallback: regex on page text ---
    if not job["title"]:
        lines = [l.strip() for l in page_text.split('\n') if l.strip()]
        for line in lines[:15]:
            if len(line) > 10 and len(line) < 150 and 'JR00' not in line:
                if not any(kw in line for kw in ['Posted', 'End Date', 'Sign In', 'Register', 'Experience', 'Apply', 'Share']):
                    job["title"] = line
                    break

    if not job["department"]:
        dept_match = re.search(r'(?:Department|Function|Team)[:\s|]+([A-Za-z\s&-]+?)(?:\n|$|\|)', page_text, re.I)
        if dept_match:
            job["department"] = dept_match.group(1).strip()

    if not job["location"]:
        loc_match = re.search(r'(?:Location|City|Office)[:\s|]+([A-Za-z\s,()-]+?)(?:\n|$|\|)', page_text, re.I)
        if loc_match:
            job["location"] = loc_match.group(1).strip()

    return job


def go_to_page_by_number(driver, page_num):
    """Navigate to a specific page number."""
    if page_num == 1:
        return True

    try:
        # Look for pagination element
        btn = driver.find_element(By.XPATH,
            f"//a[text()='{page_num}'] | //button[text()='{page_num}'] | "
            f"//*[contains(@class, 'page') and text()='{page_num}'] | "
            f"//li[text()='{page_num}']"
        )
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
        time.sleep(0.3)
        driver.execute_script("arguments[0].click();", btn)
        time.sleep(2)
        wait_for_page(driver)
        return True
    except:
        return False


def reload_listing_page(driver, page_num=1):
    """Reload the job listing page and navigate to the correct page number."""
    try:
        driver.get(JOB_LIST_URL)
        wait_for_page(driver)

        if page_num > 1:
            time.sleep(1)
            go_to_page_by_number(driver, page_num)

        return True
    except:
        return False


def save_results(all_jobs):
    # Deduplicate by JR code
    seen = set()
    unique = []
    for job in all_jobs:
        if job["jr_code"] and job["jr_code"] not in seen:
            seen.add(job["jr_code"])
            unique.append(job)

    # Save CSV
    csv_path = OUTPUT_DIR / "bfl_jobs_complete.csv"
    fieldnames = [
        "jr_code", "title", "department", "location",
        "experience", "posted_date", "end_date", "skills",
        "description", "deep_link", "scraped_at"
    ]
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for job in unique:
            job["scraped_at"] = datetime.now().isoformat()
            writer.writerow({k: job.get(k, "") for k in fieldnames})

    # Save JSON
    json_path = OUTPUT_DIR / "bfl_jobs_complete.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(unique, f, indent=2, ensure_ascii=False)

    return unique, csv_path


def print_summary(jobs):
    dept_counts = {}
    loc_counts = {}
    for j in jobs:
        d = j.get("department") or "Unknown"
        l = j.get("location") or "Unknown"
        dept_counts[d] = dept_counts.get(d, 0) + 1
        loc_counts[l] = loc_counts.get(l, 0) + 1

    print(f"\n{'='*60}")
    print(f"TOTAL UNIQUE JOBS: {len(jobs)}")
    print(f"{'='*60}")
    print(f"\nDepartments ({len(dept_counts)}):")
    for d, c in sorted(dept_counts.items(), key=lambda x: x[1], reverse=True)[:15]:
        print(f"  {d:<45} {c:>5}")
    print(f"\nLocations ({len(loc_counts)}):")
    for l, c in sorted(loc_counts.items(), key=lambda x: x[1], reverse=True)[:15]:
        print(f"  {l:<45} {c:>5}")


def main():
    parser = argparse.ArgumentParser(description="BFL Detail Scraper v5 - Fixed stale element bug")
    parser.add_argument("--pages", type=int, default=1, help="Number of pages (default=1)")
    parser.add_argument("--headless", action="store_true", help="Run without browser window")
    args = parser.parse_args()

    print("=" * 60)
    print("BFL PEOPLESTRONG DETAIL SCRAPER v5")
    print("=" * 60)
    print("FIXED: Stale element reference bug")
    print("Method: For each job - find fresh, click, extract, go back")
    print(f"Pages to scrape: {args.pages}")
    print()

    driver = None
    all_jobs = []

    try:
        print("[1/3] Setting up Chrome...")
        driver = setup_driver(headless=args.headless)

        print("[2/3] Loading careers portal...")
        driver.get(JOB_LIST_URL)
        wait_for_page(driver)

        print("[3/3] Scraping jobs...\n")

        for page in range(1, args.pages + 1):
            print(f"--- PAGE {page} ---")

            # Navigate to this page
            if page > 1:
                if not go_to_page_by_number(driver, page):
                    print(f"  Could not navigate to page {page}. Reloading...")
                    reload_listing_page(driver, page)
                time.sleep(1)

            # Get list of JR codes on this page (NO element references stored!)
            jr_codes = get_jr_codes_on_page(driver)
            print(f"  Found {len(jr_codes)} jobs: {jr_codes[:3]}...")

            if not jr_codes:
                print("  No jobs found. Stopping.")
                break

            # Process each job by JR code
            for idx, jr_code in enumerate(jr_codes):
                print(f"  [{idx+1}/{len(jr_codes)}] {jr_code}:", end=" ", flush=True)

                try:
                    # FRESH lookup and click for each job
                    if not find_and_click_job(driver, jr_code):
                        print("Could not click")
                        reload_listing_page(driver, page)
                        continue

                    # Wait for detail page
                    time.sleep(2)
                    wait_for_page(driver, timeout=10)

                    # Check if we're on a detail page (URL should change)
                    if 'joblist' in driver.current_url and 'detail' not in driver.current_url:
                        print("Did not navigate to detail")
                        continue

                    # Extract job details
                    job = extract_detail_page(driver)

                    # Use known JR code if not found
                    if not job["jr_code"]:
                        job["jr_code"] = jr_code

                    all_jobs.append(job)

                    title_short = job.get("title", "?")[:35]
                    dept = job.get("department", "?")[:20]
                    loc = job.get("location", "?")[:20]
                    print(f"OK | {dept} | {loc}")

                    # Go back to listing
                    driver.back()
                    time.sleep(1.5)
                    wait_for_page(driver)

                    # Verify we're back on listing and correct page
                    if 'joblist' not in driver.current_url:
                        reload_listing_page(driver, page)

                except Exception as e:
                    print(f"Error: {str(e)[:40]}")
                    # Recover by reloading the listing page
                    reload_listing_page(driver, page)
                    time.sleep(1)
                    continue

            print(f"  Page {page} done. Total collected: {len(all_jobs)}\n")

        # Save results
        print(f"\nSaving {len(all_jobs)} jobs...")
        unique_jobs, csv_path = save_results(all_jobs)
        print(f"  Saved to: {csv_path}")

        print_summary(unique_jobs)

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()

        if all_jobs:
            print(f"\nSaving {len(all_jobs)} jobs collected before error...")
            save_results(all_jobs)

    finally:
        if driver:
            if not args.headless:
                input("\nPress Enter to close browser...")
            driver.quit()


if __name__ == "__main__":
    main()
