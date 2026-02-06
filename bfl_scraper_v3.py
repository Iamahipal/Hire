#!/usr/bin/env python3
"""
BFL PeopleStrong FAST Scraper v3
================================
Uses JavaScript injection to extract data directly from DOM.
This is the "scanner" approach - fast and accurate.

Fixes from v2:
- Department and Location extracted as SEPARATE HTML elements (not concatenated text)
- Full title text (not truncated by CSS)
- 10x faster using JS extraction instead of Python element-by-element

Usage:
    python bfl_scraper_v3.py               # Scrape all pages
    python bfl_scraper_v3.py --pages 2     # Only first 2 pages
    python bfl_scraper_v3.py --headless    # No browser window
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
from selenium.common.exceptions import TimeoutException, NoSuchElementException

try:
    from webdriver_manager.chrome import ChromeDriverManager
    USE_DRIVER_MANAGER = True
except ImportError:
    USE_DRIVER_MANAGER = False

BASE_URL = "https://bflcareers.peoplestrong.com"
JOB_LIST_URL = f"{BASE_URL}/job/joblist"

OUTPUT_DIR = Path(__file__).parent / "bfl_output"
OUTPUT_DIR.mkdir(exist_ok=True)


# ============================================================
# This JavaScript runs INSIDE the browser - extracts everything
# in one shot per page. This is the "scanner" approach.
# ============================================================
JS_EXTRACT_JOBS = """
function extractAllJobs() {
    var jobs = [];

    // Find all job cards on the page
    // PeopleStrong uses Angular - cards are in a grid/list
    var cards = document.querySelectorAll(
        'app-job-card, [class*="job-card"], [class*="job_card"], .card'
    );

    // If Angular component selector didn't work, find by JR code pattern
    if (cards.length === 0) {
        // Find all elements containing JR codes and walk up to card
        var jrElements = document.querySelectorAll('*');
        var cardSet = new Set();
        for (var el of jrElements) {
            if (el.children.length === 0 && /^JR\\d{5,}$/.test(el.textContent.trim())) {
                // Walk up to find the card container
                var parent = el;
                for (var k = 0; k < 8; k++) {
                    parent = parent.parentElement;
                    if (!parent) break;
                    var text = parent.textContent;
                    if (text.includes('Apply') && text.includes('Share') && text.includes('Experience')) {
                        cardSet.add(parent);
                        break;
                    }
                }
            }
        }
        cards = Array.from(cardSet);
    }

    for (var i = 0; i < cards.length; i++) {
        var card = cards[i];
        var job = {
            jr_code: '',
            title: '',
            department: '',
            location: '',
            experience: '',
            posted_date: '',
            end_date: '',
            skills: '',
            deep_link: ''
        };

        // --- TITLE: Get full text (not truncated) ---
        // Title is usually in h1-h5, a, or element with 'title' class
        var titleEl = card.querySelector(
            'h1, h2, h3, h4, h5, [class*="title"], [class*="heading"], a[class*="title"]'
        );
        if (titleEl) {
            // Use title attribute (full text) or textContent
            job.title = titleEl.getAttribute('title') || titleEl.textContent.trim();
        }

        // --- JR CODE ---
        var allText = card.textContent;
        var jrMatch = allText.match(/JR\\d{5,}/);
        if (jrMatch) {
            job.jr_code = jrMatch[0];
        }

        // --- DEPARTMENT and LOCATION: Extract as SEPARATE elements ---
        // In PeopleStrong, dept and location are in separate spans/divs
        // They appear as colored text below the JR code
        // Look for elements that contain dept|location pattern
        var allElements = card.querySelectorAll('span, div, p, a, small');
        var deptLocCandidates = [];

        for (var j = 0; j < allElements.length; j++) {
            var el = allElements[j];
            var text = el.textContent.trim();

            // Skip if it's title, JR code, date, experience, skill, or button
            if (!text || text.length < 2) continue;
            if (/^JR\\d+$/.test(text)) continue;
            if (text === job.title) continue;
            if (/Posted|End Date|Required|SKILLS|Share|Apply|Sign In|Register/i.test(text)) continue;
            if (/^\\d+[\\s-]+\\d*\\s*years?$/i.test(text)) continue;

            // Check if this element has pipe separator
            if (text.includes('|') && !text.includes('Posted') && !text.includes('End Date')) {
                var parts = text.split('|');
                if (parts.length >= 2 && parts[0].trim().length > 1) {
                    job.department = parts[0].trim();
                    job.location = parts[1].trim();
                    break;
                }
            }
        }

        // If pipe method didn't work, find by element structure
        if (!job.department && !job.location) {
            // Look for the dept-location container
            // Usually it's a div/span with specific class containing two child spans
            var containers = card.querySelectorAll(
                '[class*="dept"], [class*="location"], [class*="detail"], [class*="info"], [class*="sub"]'
            );

            for (var c = 0; c < containers.length; c++) {
                var container = containers[c];
                var children = container.querySelectorAll('span, a, small');
                if (children.length >= 2) {
                    var texts = [];
                    for (var ch = 0; ch < children.length; ch++) {
                        var t = children[ch].textContent.trim();
                        if (t && t.length > 1 && !/Posted|End|Required|Apply|Share/i.test(t)) {
                            texts.push(t);
                        }
                    }
                    if (texts.length >= 2) {
                        job.department = texts[0];
                        job.location = texts[1];
                        break;
                    }
                }
            }
        }

        // Last resort: look for colored/styled text elements after JR code
        if (!job.department && !job.location) {
            var jrEl = null;
            var allEls = card.querySelectorAll('*');
            for (var x = 0; x < allEls.length; x++) {
                if (/^JR\\d{5,}$/.test(allEls[x].textContent.trim()) && allEls[x].children.length === 0) {
                    jrEl = allEls[x];
                    break;
                }
            }

            if (jrEl) {
                // Get the parent of JR code, then look for next sibling elements
                var jrParent = jrEl.parentElement;
                if (jrParent) {
                    var nextSib = jrParent.nextElementSibling;
                    if (!nextSib) {
                        jrParent = jrParent.parentElement;
                        nextSib = jrParent ? jrParent.nextElementSibling : null;
                    }

                    if (nextSib) {
                        var sibText = nextSib.textContent.trim();
                        // This might be "Risk | Pune Corporate Office"
                        if (sibText.includes('|')) {
                            var pts = sibText.split('|');
                            job.department = pts[0].trim();
                            job.location = pts[1].trim();
                        } else {
                            // Look at individual child elements
                            var sibChildren = nextSib.querySelectorAll('*');
                            var candidateTexts = [];
                            for (var sc = 0; sc < sibChildren.length; sc++) {
                                var st = sibChildren[sc].textContent.trim();
                                if (st && st.length > 1 && sibChildren[sc].children.length === 0) {
                                    if (!/Posted|End|Required|SKILLS|Apply|Share|years/i.test(st)) {
                                        candidateTexts.push(st);
                                    }
                                }
                            }
                            // Remove duplicates keeping order
                            var seen = {};
                            var unique = [];
                            for (var u = 0; u < candidateTexts.length; u++) {
                                if (!seen[candidateTexts[u]]) {
                                    seen[candidateTexts[u]] = true;
                                    unique.push(candidateTexts[u]);
                                }
                            }
                            if (unique.length >= 2) {
                                job.department = unique[0];
                                job.location = unique[1];
                            } else if (unique.length === 1) {
                                job.department = unique[0];
                            }
                        }
                    }
                }
            }
        }

        // --- EXPERIENCE ---
        var expMatch = allText.match(/(\\d+[\\s-]+\\d*\\s*years?)/i);
        if (expMatch) {
            job.experience = expMatch[1].trim();
        }

        // --- DATES ---
        var postedMatch = allText.match(/Posted\\s*On[:\\s]*([\\d]{1,2}\\s+\\w+\\s+\\d{4})/);
        if (postedMatch) {
            job.posted_date = postedMatch[1];
        }
        var endMatch = allText.match(/End\\s*Date[:\\s]*([\\d]{1,2}\\s+\\w+\\s+\\d{4})/);
        if (endMatch) {
            job.end_date = endMatch[1];
        }

        // --- SKILLS ---
        if (allText.includes('SKILLS AS PER JD')) {
            job.skills = 'SKILLS AS PER JD';
        } else {
            var skillMatch = allText.match(/Required\\s*Skills[\\s:]*(.*?)(?:Share|Apply|$)/s);
            if (skillMatch) {
                job.skills = skillMatch[1].trim().substring(0, 100);
            }
        }

        // --- DEEP LINK ---
        var applyLink = card.querySelector('a[href*="job"], a[href*="detail"], a[href*="apply"]');
        if (applyLink) {
            job.deep_link = applyLink.href;
        } else {
            job.deep_link = window.location.origin + '/job/jobdetail/' + job.jr_code;
        }

        // Only add if we have JR code
        if (job.jr_code) {
            jobs.push(job);
        }
    }

    return jobs;
}
return extractAllJobs();
"""

JS_GET_TOTAL = """
var text = document.body.textContent;
var match = text.match(/OF\\s+([\\d,]+)/);
return match ? parseInt(match[1].replace(',', '')) : 0;
"""

JS_GET_PAGE_INFO = """
var text = document.body.textContent;
var showMatch = text.match(/SHOWING\\s+(\\d+)/);
var ofMatch = text.match(/OF\\s+([\\d,]+)/);
return {
    showing: showMatch ? parseInt(showMatch[1]) : 0,
    total: ofMatch ? parseInt(ofMatch[1].replace(',', '')) : 0
};
"""


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
        time.sleep(3)
        return True
    except TimeoutException:
        return False


def go_to_next_page(driver, current_page):
    next_page = current_page + 1
    try:
        btn = driver.find_element(By.XPATH,
            f"//a[text()='{next_page}'] | //button[text()='{next_page}'] | "
            f"//*[contains(@class, 'page') and text()='{next_page}']"
        )
        driver.execute_script("arguments[0].scrollIntoView(true);", btn)
        time.sleep(0.3)
        driver.execute_script("arguments[0].click();", btn)
        time.sleep(2)
        return True
    except NoSuchElementException:
        pass

    try:
        btn = driver.find_element(By.XPATH,
            "//*[text()='>'] | //*[text()='Next'] | //*[text()='›'] | //*[contains(@class, 'next')]"
        )
        if btn.is_displayed():
            driver.execute_script("arguments[0].click();", btn)
            time.sleep(2)
            return True
    except NoSuchElementException:
        pass

    return False


def save_results(all_jobs):
    seen = set()
    unique = []
    for job in all_jobs:
        if job["jr_code"] not in seen:
            seen.add(job["jr_code"])
            unique.append(job)

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
        for job in unique:
            job["scraped_at"] = datetime.now().isoformat()
            writer.writerow({k: job.get(k, "") for k in fieldnames})

    # JSON
    json_path = OUTPUT_DIR / "bfl_jobs_complete.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(unique, f, indent=2, ensure_ascii=False)

    # Summary
    dept_counts = {}
    loc_counts = {}
    for j in unique:
        d = j.get("department") or "Unknown"
        l = j.get("location") or "Unknown"
        dept_counts[d] = dept_counts.get(d, 0) + 1
        loc_counts[l] = loc_counts.get(l, 0) + 1

    summary_path = OUTPUT_DIR / "bfl_summary.csv"
    with open(summary_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["Category", "Name", "Job Count"])
        writer.writerow([])
        for dept, count in sorted(dept_counts.items(), key=lambda x: x[1], reverse=True):
            writer.writerow(["Department", dept, count])
        writer.writerow([])
        for loc, count in sorted(loc_counts.items(), key=lambda x: x[1], reverse=True):
            writer.writerow(["Location", loc, count])

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
    print(f"\nTop Locations ({len(loc_counts)} total):")
    for l, c in sorted(loc_counts.items(), key=lambda x: x[1], reverse=True)[:15]:
        print(f"  {l:<45} {c:>5}")


def main():
    parser = argparse.ArgumentParser(description="BFL PeopleStrong FAST Scraper v3")
    parser.add_argument("--pages", type=int, default=0, help="Max pages (0=all)")
    parser.add_argument("--headless", action="store_true", help="No browser window")
    args = parser.parse_args()

    print("=" * 60)
    print("BFL PEOPLESTRONG FAST SCRAPER v3")
    print("=" * 60)
    print(f"Target: {JOB_LIST_URL}")
    print(f"Method: JavaScript DOM injection (fast)")
    print()

    driver = None
    all_jobs = []

    try:
        print("[1/3] Setting up Chrome...")
        driver = setup_driver(headless=args.headless)

        print("[2/3] Loading careers portal...")
        driver.get(JOB_LIST_URL)
        wait_for_page(driver)

        # Get total
        info = driver.execute_script(JS_GET_PAGE_INFO)
        total_jobs = info.get("total", 0)
        per_page = info.get("showing", 45) or 45
        total_pages = (total_jobs + per_page - 1) // per_page if total_jobs else 200

        print(f"  Total jobs: {total_jobs}")
        print(f"  Per page: {per_page}")
        print(f"  Total pages: {total_pages}")

        max_pages = args.pages if args.pages > 0 else total_pages

        print(f"\n[3/3] Extracting jobs (JS injection)...")

        for page in range(1, max_pages + 1):
            start_time = time.time()

            # Extract ALL jobs from current page using JavaScript
            page_jobs = driver.execute_script(JS_EXTRACT_JOBS)

            elapsed = time.time() - start_time

            if page_jobs:
                all_jobs.extend(page_jobs)
                # Show sample from first page
                if page == 1 and page_jobs:
                    j = page_jobs[0]
                    print(f"  Sample: {j['jr_code']} | {j['title']}")
                    print(f"          Dept: {j['department']} | Loc: {j['location']}")

                print(f"  Page {page}/{max_pages}: {len(page_jobs)} jobs ({elapsed:.1f}s) [Total: {len(all_jobs)}]")
            else:
                print(f"  Page {page}: No jobs found. Stopping.")
                break

            # Next page
            if page < max_pages:
                if not go_to_next_page(driver, page):
                    print(f"  Cannot go to page {page + 1}. Stopping.")
                    break
                wait_for_page(driver, timeout=10)

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

        if driver:
            try:
                driver.save_screenshot(str(OUTPUT_DIR / "error_screenshot.png"))
            except:
                pass

    finally:
        if driver:
            if not args.headless:
                input("\nPress Enter to close browser...")
            driver.quit()


if __name__ == "__main__":
    main()
