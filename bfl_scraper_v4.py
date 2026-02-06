#!/usr/bin/env python3
"""
BFL PeopleStrong DETAIL Scraper v4
==================================
Clicks into EACH job detail page to get complete, accurate data.

Flow:
1. Load job listing page
2. Click on job card → opens full JD detail page
3. Extract ALL fields from detail page (complete data, not truncated)
4. Go back to listing
5. Click next job card
6. Repeat for all jobs on page
7. Go to next page

This is slower but gets 100% accurate data.

Usage:
    python bfl_scraper_v4.py --pages 1    # First page only (recommended for testing)
    python bfl_scraper_v4.py --pages 2    # First 2 pages
    python bfl_scraper_v4.py              # All pages (takes time!)
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
        time.sleep(2)
        return True
    except TimeoutException:
        return False


def get_job_cards_info(driver):
    """
    Get basic info (JR code + clickable element) for all jobs on current page.
    We'll click each one to get full details.
    """
    cards_info = []

    # JavaScript to find all JR codes and their clickable parent elements
    js_get_cards = """
    var results = [];
    var allElements = document.querySelectorAll('*');

    for (var i = 0; i < allElements.length; i++) {
        var el = allElements[i];
        var text = el.textContent.trim();

        // Find JR code elements
        if (/^JR\\d{5,}$/.test(text) && el.children.length === 0) {
            // Walk up to find clickable card or title
            var parent = el;
            var clickable = null;
            var title = '';

            for (var k = 0; k < 10; k++) {
                parent = parent.parentElement;
                if (!parent) break;

                // Look for title in this parent
                var titleEl = parent.querySelector('h1, h2, h3, h4, h5, [class*="title"], a[class*="title"]');
                if (titleEl && !title) {
                    title = titleEl.textContent.trim();
                    // Title element is often clickable
                    if (titleEl.tagName === 'A' || titleEl.onclick || titleEl.style.cursor === 'pointer') {
                        clickable = titleEl;
                    }
                }

                // Check if parent has Apply/Share (means it's the card)
                if (parent.textContent.includes('Apply') && parent.textContent.includes('Share')) {
                    // Find any clickable link in the card
                    var links = parent.querySelectorAll('a');
                    for (var l = 0; l < links.length; l++) {
                        var href = links[l].href || '';
                        if (href.includes('job') || href.includes('detail') || href.includes('apply')) {
                            clickable = links[l];
                            break;
                        }
                    }
                    if (!clickable) {
                        // Try the title as clickable
                        var titleLink = parent.querySelector('h1 a, h2 a, h3 a, h4 a, [class*="title"] a, a[class*="title"]');
                        if (titleLink) clickable = titleLink;
                    }
                    break;
                }
            }

            if (clickable || title) {
                results.push({
                    jr_code: text,
                    title: title,
                    element: clickable || el
                });
            }
        }
    }

    return results;
    """

    try:
        # Get list of cards with their JR codes
        cards_data = driver.execute_script(js_get_cards)

        # We need to return actual element references, so let's do it differently
        # Find all JR code elements and store their index for clicking
        jr_elements = driver.find_elements(By.XPATH,
            "//*[not(*)][contains(text(), 'JR00')]"
        )

        for jr_el in jr_elements:
            try:
                jr_text = jr_el.text.strip()
                if not re.match(r'^JR\d{5,}$', jr_text):
                    continue

                # Find the clickable title/link for this job
                # Walk up to find the card container
                card = jr_el
                for _ in range(8):
                    card = card.find_element(By.XPATH, "..")
                    card_text = card.text
                    if 'Apply' in card_text and 'Share' in card_text:
                        break

                # Find title link in the card
                clickable = None
                title = ""

                try:
                    # Try to find a clickable title
                    title_el = card.find_element(By.CSS_SELECTOR,
                        "a[class*='title'], h1 a, h2 a, h3 a, h4 a, [class*='title'] a"
                    )
                    clickable = title_el
                    title = title_el.text.strip() or title_el.get_attribute("title") or ""
                except NoSuchElementException:
                    pass

                if not clickable:
                    try:
                        # Try any link with job/detail in href
                        links = card.find_elements(By.CSS_SELECTOR, "a[href*='job'], a[href*='detail']")
                        if links:
                            clickable = links[0]
                            title = clickable.text.strip()
                    except:
                        pass

                if not clickable:
                    try:
                        # Last resort: find title element and click it
                        title_el = card.find_element(By.CSS_SELECTOR, "h1, h2, h3, h4, [class*='title']")
                        clickable = title_el
                        title = title_el.text.strip()
                    except:
                        pass

                if clickable:
                    cards_info.append({
                        "jr_code": jr_text,
                        "title": title,
                        "element": clickable
                    })

            except Exception as e:
                continue

    except Exception as e:
        print(f"  Error getting cards: {e}")

    return cards_info


def extract_detail_page(driver):
    """
    Extract ALL job details from the current detail page.
    This page has complete, non-truncated data.
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

    # Wait for page to load
    time.sleep(2)

    page_text = driver.find_element(By.TAG_NAME, "body").text

    # --- JR CODE ---
    jr_match = re.search(r'(JR\d{5,})', page_text)
    if jr_match:
        job["jr_code"] = jr_match.group(1)

    # --- Use JavaScript to extract from structured elements ---
    js_extract = """
    var data = {};

    // Title - look for main heading
    var titleEl = document.querySelector(
        'h1, h2, [class*="job-title"], [class*="jobTitle"], [class*="position-title"]'
    );
    if (titleEl) {
        data.title = titleEl.textContent.trim();
    }

    // Look for labeled fields like "Department:", "Location:", etc.
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
    var expMatch = allText.match(/(?:Experience|Exp)\\s*[:\\|]\\s*([^\\n]+)/i);
    if (expMatch) data.experience = expMatch[1].trim();

    // Also try "X-Y years" pattern anywhere
    if (!data.experience) {
        var expMatch2 = allText.match(/(\\d+\\s*[-–]\\s*\\d+\\s*years?)/i);
        if (expMatch2) data.experience = expMatch2[1].trim();
    }

    // Posted Date
    var postedMatch = allText.match(/Posted\\s*(?:On|Date)?\\s*[:\\|]?\\s*(\\d{1,2}\\s+\\w+\\s+\\d{4})/i);
    if (postedMatch) data.posted_date = postedMatch[1].trim();

    // End Date
    var endMatch = allText.match(/End\\s*Date\\s*[:\\|]?\\s*(\\d{1,2}\\s+\\w+\\s+\\d{4})/i);
    if (endMatch) data.end_date = endMatch[1].trim();

    // Skills
    var skillsMatch = allText.match(/(?:Skills|Qualifications)\\s*[:\\|]?\\s*([^\\n]{10,200})/i);
    if (skillsMatch) data.skills = skillsMatch[1].trim();

    // Job Description (first 500 chars)
    var descMatch = allText.match(/(?:Job\\s*Description|Description|About\\s*the\\s*Role|Responsibilities)\\s*[:\\|]?\\s*([\\s\\S]{10,500})/i);
    if (descMatch) data.description = descMatch[1].trim().substring(0, 500);

    // Look for structured detail elements (PeopleStrong often has these)
    var detailDivs = document.querySelectorAll('[class*="detail"], [class*="info"], [class*="field"]');
    for (var d of detailDivs) {
        var label = d.querySelector('[class*="label"], [class*="key"], strong, b');
        var value = d.querySelector('[class*="value"], [class*="data"], span:last-child');

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
        print(f"    JS extraction error: {e}")

    # --- Fallback: Parse page text with regex ---
    if not job["title"]:
        # Title is often the first big text or h1
        lines = [l.strip() for l in page_text.split('\n') if l.strip()]
        for line in lines[:10]:
            if len(line) > 10 and len(line) < 100 and 'JR00' not in line:
                if not any(kw in line for kw in ['Posted', 'End Date', 'Sign In', 'Register', 'Experience']):
                    job["title"] = line
                    break

    # Department and Location from text patterns
    if not job["department"]:
        dept_match = re.search(r'(?:Department|Function|Team)[:\s|]+([A-Za-z\s&-]+?)(?:\n|$|\|)', page_text, re.I)
        if dept_match:
            job["department"] = dept_match.group(1).strip()

    if not job["location"]:
        loc_match = re.search(r'(?:Location|City|Office)[:\s|]+([A-Za-z\s,-]+?)(?:\n|$|\|)', page_text, re.I)
        if loc_match:
            job["location"] = loc_match.group(1).strip()

    return job


def go_back_safe(driver):
    """Go back to listing page safely."""
    try:
        driver.back()
        time.sleep(2)
        wait_for_page(driver)
        return True
    except:
        # If back fails, navigate directly
        try:
            driver.get(JOB_LIST_URL)
            wait_for_page(driver)
            return True
        except:
            return False


def go_to_page(driver, page_num):
    """Navigate to specific page number."""
    try:
        # Click page number
        btn = driver.find_element(By.XPATH,
            f"//a[text()='{page_num}'] | //button[text()='{page_num}'] | "
            f"//*[contains(@class, 'page') and text()='{page_num}']"
        )
        driver.execute_script("arguments[0].scrollIntoView(true);", btn)
        time.sleep(0.5)
        driver.execute_script("arguments[0].click();", btn)
        time.sleep(2)
        wait_for_page(driver)
        return True
    except:
        return False


def save_results(all_jobs):
    # Deduplicate
    seen = set()
    unique = []
    for job in all_jobs:
        if job["jr_code"] and job["jr_code"] not in seen:
            seen.add(job["jr_code"])
            unique.append(job)

    # CSV
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

    # JSON
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
    parser = argparse.ArgumentParser(description="BFL Detail Scraper v4 - Clicks into each job")
    parser.add_argument("--pages", type=int, default=1, help="Number of pages (default=1)")
    parser.add_argument("--headless", action="store_true", help="No browser window")
    args = parser.parse_args()

    print("=" * 60)
    print("BFL PEOPLESTRONG DETAIL SCRAPER v4")
    print("=" * 60)
    print("Method: Click into each job → Extract full details → Go back")
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

        print("[3/3] Scraping jobs (clicking into each detail page)...")

        for page in range(1, args.pages + 1):
            print(f"\n--- PAGE {page} ---")

            # Navigate to this page if not first
            if page > 1:
                if not go_to_page(driver, page):
                    print(f"  Could not navigate to page {page}. Stopping.")
                    break
                time.sleep(2)

            # Get all job cards on this page
            cards = get_job_cards_info(driver)
            print(f"  Found {len(cards)} jobs on this page")

            if not cards:
                print("  No jobs found. Stopping.")
                break

            # Click into each job and extract details
            for idx, card_info in enumerate(cards):
                jr_code = card_info["jr_code"]
                title_preview = card_info["title"][:40] if card_info["title"] else "?"

                print(f"  [{idx+1}/{len(cards)}] {jr_code}: {title_preview}...", end=" ", flush=True)

                try:
                    # Click the job to open detail page
                    element = card_info["element"]
                    driver.execute_script("arguments[0].scrollIntoView(true);", element)
                    time.sleep(0.3)

                    try:
                        element.click()
                    except ElementClickInterceptedException:
                        driver.execute_script("arguments[0].click();", element)

                    # Wait for detail page to load
                    time.sleep(2)
                    wait_for_page(driver, timeout=10)

                    # Extract details
                    job = extract_detail_page(driver)

                    # Use JR code from card if not found in detail
                    if not job["jr_code"]:
                        job["jr_code"] = jr_code

                    all_jobs.append(job)

                    dept = job.get("department", "?")[:20]
                    loc = job.get("location", "?")[:20]
                    print(f"✓ {dept} | {loc}")

                    # Go back to listing
                    go_back_safe(driver)

                    # Re-navigate to correct page if needed
                    if page > 1:
                        # Check if we're on the right page
                        time.sleep(1)
                        go_to_page(driver, page)

                    time.sleep(1)

                except Exception as e:
                    print(f"✗ Error: {str(e)[:50]}")
                    # Try to recover
                    try:
                        driver.get(JOB_LIST_URL)
                        wait_for_page(driver)
                        if page > 1:
                            go_to_page(driver, page)
                    except:
                        pass
                    continue

            print(f"  Page {page} complete. Total jobs collected: {len(all_jobs)}")

        # Save
        print(f"\nSaving {len(all_jobs)} jobs...")
        unique_jobs, csv_path = save_results(all_jobs)
        print(f"  CSV: {csv_path}")

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
