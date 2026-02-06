#!/usr/bin/env python3
"""
BFL PeopleStrong AGENTIC Scraper v6
===================================
Smart, self-healing scraper that extracts ALL data from detail pages.

Fields extracted:
- jr_code, title, job_level
- department, org_unit
- country, state, region, city, location_name, tier
- experience, posted_date, end_date
- skills (all tags)
- min_qualification
- job_purpose, responsibilities, qualifications (full JD)
- deep_link

Features:
- Multiple extraction strategies (tries alternatives if one fails)
- Data validation (retries if data quality is poor)
- Progress checkpointing (resume if interrupted)
- Self-recovery from errors

Usage:
    python bfl_scraper_v6.py --pages 1      # Test with 1 page
    python bfl_scraper_v6.py --pages 5      # First 5 pages
    python bfl_scraper_v6.py --resume       # Resume from checkpoint
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

CHECKPOINT_FILE = OUTPUT_DIR / "checkpoint.json"


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
        time.sleep(1)
        return True
    except TimeoutException:
        return False


def get_jr_codes_on_page(driver):
    """Get list of JR codes on current page. NO element references stored."""
    jr_codes = []
    try:
        elements = driver.find_elements(By.XPATH, "//*[contains(text(), 'JR00')]")
        for el in elements:
            try:
                text = el.text.strip()
                match = re.search(r'(JR\d{8})', text)
                if match:
                    code = match.group(1)
                    if code not in jr_codes:
                        jr_codes.append(code)
            except:
                continue
    except Exception as e:
        print(f"  Error getting JR codes: {e}")
    return jr_codes


def find_and_click_job(driver, jr_code):
    """Find job by JR code and click to open detail page."""
    try:
        # Strategy 1: Find JR code element and click its parent card/link
        jr_element = driver.find_element(By.XPATH, f"//*[contains(text(), '{jr_code}')]")

        # Walk up to find clickable card
        card = jr_element
        for _ in range(10):
            card = card.find_element(By.XPATH, "..")
            try:
                # Look for title link in this container
                title_link = card.find_element(By.CSS_SELECTOR, "a")
                if title_link:
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", title_link)
                    time.sleep(0.3)
                    try:
                        title_link.click()
                    except:
                        driver.execute_script("arguments[0].click();", title_link)
                    return True
            except:
                pass

            # Check if this is the card container
            card_text = card.text
            if 'Apply' in card_text and 'Share' in card_text:
                # Found the card, look for any link
                links = card.find_elements(By.TAG_NAME, "a")
                for link in links:
                    href = link.get_attribute("href") or ""
                    if "job" in href or "detail" in href or jr_code in href:
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", link)
                        time.sleep(0.3)
                        try:
                            link.click()
                        except:
                            driver.execute_script("arguments[0].click();", link)
                        return True
                break

        # Strategy 2: Direct URL navigation
        detail_url = f"{BASE_URL}/job/detail/{jr_code}"
        driver.get(detail_url)
        return True

    except Exception as e:
        # Strategy 3: Navigate directly by URL
        try:
            detail_url = f"{BASE_URL}/job/detail/{jr_code}"
            driver.get(detail_url)
            return True
        except:
            return False


def extract_detail_page_complete(driver, jr_code):
    """
    Extract ALL fields from detail page using multiple strategies.
    This is the AGENTIC part - tries multiple methods to get each field.
    """
    job = {
        "jr_code": jr_code,
        "title": "",
        "job_level": "",
        "department": "",
        "org_unit": "",
        "country": "",
        "state": "",
        "region": "",
        "city": "",
        "location_name": "",
        "tier": "",
        "experience": "",
        "posted_date": "",
        "end_date": "",
        "skills": "",
        "min_qualification": "",
        "job_purpose": "",
        "responsibilities": "",
        "qualifications": "",
        "deep_link": driver.current_url,
    }

    time.sleep(1.5)

    # Get page text for fallback parsing
    try:
        page_text = driver.find_element(By.TAG_NAME, "body").text
    except:
        page_text = ""

    # ==================== JAVASCRIPT EXTRACTION ====================
    # This extracts data from the structured elements on the page
    js_extract = """
    var data = {};

    // Helper to get text by label - looks for label and returns adjacent value
    function getFieldValue(labelText) {
        var allElements = document.querySelectorAll('*');
        for (var el of allElements) {
            var text = el.textContent.trim();
            // Match exact label or label with colon
            if (text === labelText || text === labelText + ':') {
                // Look for value in next sibling
                var next = el.nextElementSibling;
                if (next && next.textContent.trim().length > 0) {
                    var val = next.textContent.trim();
                    // Don't return if it's another label
                    if (val !== labelText && !val.endsWith(':')) {
                        return val;
                    }
                }
                // Try parent's structure (common in PeopleStrong)
                var parent = el.parentElement;
                if (parent) {
                    var siblings = parent.parentElement ? parent.parentElement.children : [];
                    for (var i = 0; i < siblings.length; i++) {
                        if (siblings[i] === parent && siblings[i+1]) {
                            return siblings[i+1].textContent.trim();
                        }
                    }
                }
            }
        }
        return '';
    }

    // ===== TITLE EXTRACTION =====
    // Try multiple approaches to get the job title

    // Method 1: Look for heading elements
    var titleEl = document.querySelector('h1, h2');
    if (titleEl) {
        var titleText = titleEl.textContent.trim();
        // Make sure it's not navigation or other header
        if (titleText.length > 5 && titleText.length < 150 &&
            !titleText.includes('Sign In') && !titleText.includes('Register') &&
            !titleText.includes('All Jobs')) {
            data.title = titleText;
        }
    }

    // Method 2: Look for job title in page structure
    if (!data.title) {
        // PeopleStrong often has title near JR code
        var jrEl = document.evaluate("//*[contains(text(), 'JR00')]", document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
        if (jrEl) {
            var parent = jrEl.parentElement;
            for (var i = 0; i < 5 && parent; i++) {
                var h = parent.querySelector('h1, h2, h3, h4, [class*="title"]');
                if (h) {
                    var t = h.textContent.trim();
                    if (t.length > 5 && !t.includes('JR00')) {
                        data.title = t;
                        break;
                    }
                }
                parent = parent.parentElement;
            }
        }
    }

    // Method 3: Get from Job Title field in BASIC SECTION
    if (!data.title) {
        var jobTitleField = getFieldValue('Job Title');
        if (jobTitleField && jobTitleField.length > 5) {
            data.title = jobTitleField.split(',')[0].trim(); // Take first part before comma
        }
    }

    // ===== DEPARTMENT EXTRACTION =====
    // Look for department in the header area (format: "Dept | Location")
    var bodyText = document.body.innerText;
    var deptMatch = bodyText.match(/^([A-Z][A-Za-z\s]+(?:South|North|East|West|MFI|GL|Rural|Urban)?)\s*\|\s*[A-Za-z]/m);
    if (deptMatch) {
        data.department = deptMatch[1].trim();
    }

    // Also try org unit patterns
    var orgMatch = bodyText.match(/(?:MFI\s+(?:South|North|East|West)|GL\s+(?:North|South|East|West)\s*(?:West)?|Rural|Urban\s+Finance)/i);
    if (orgMatch) {
        data.org_unit = orgMatch[0].trim();
    }

    // BASIC SECTION fields
    data.job_level = getFieldValue('Job Level');

    // JOB LOCATION fields
    data.country = getFieldValue('Country');
    data.state = getFieldValue('State');
    data.region = getFieldValue('Region');
    data.city = getFieldValue('City');
    data.location_name = getFieldValue('Location Name');
    data.tier = getFieldValue('Tier');

    // ===== SKILLS EXTRACTION =====
    // Look for skill tags with star icons (★)
    var skills = [];
    var skillSection = bodyText.match(/Skills[\s\S]*?(?=Minimum Qualification|JOB DESCRIPTION)/i);
    if (skillSection) {
        var skillText = skillSection[0];
        // Extract skills after ★ or • markers
        var skillMatches = skillText.match(/[★•]\s*([A-Z][A-Z\s&]+?)(?=[★•\n]|$)/g);
        if (skillMatches) {
            skillMatches.forEach(function(s) {
                var skill = s.replace(/^[★•]\s*/, '').trim();
                if (skill.length > 1 && skill.length < 40 &&
                    skill !== 'SKILL' && !skill.includes('Skills as per')) {
                    skills.push(skill);
                }
            });
        }

        // Also try comma-separated skills
        if (skills.length === 0) {
            var commaSkills = skillText.match(/([A-Z][A-Z\s&]{2,30})(?:,|$)/g);
            if (commaSkills) {
                commaSkills.forEach(function(s) {
                    var skill = s.replace(/,/g, '').trim();
                    if (skill.length > 2 && skill !== 'SKILL') {
                        skills.push(skill);
                    }
                });
            }
        }
    }

    // Try getting from DOM elements with skill-like classes
    if (skills.length === 0) {
        document.querySelectorAll('[class*="chip"], [class*="tag"], [class*="badge"], [class*="pill"]').forEach(function(el) {
            var t = el.textContent.trim();
            if (t.length > 1 && t.length < 40 &&
                !t.includes('Apply') && !t.includes('Share') &&
                !t.includes('Posted') && !t.includes('SKILL') &&
                !t.includes('Skills as per')) {
                skills.push(t.replace(/^[★•]\s*/, ''));
            }
        });
    }

    data.skills = [...new Set(skills)].filter(s => s.length > 1).join(', ');

    // Minimum Qualification
    data.min_qualification = getFieldValue('Minimum Qualification');
    if (!data.min_qualification) {
        var qualMatch = document.body.innerText.match(/Minimum Qualification[\\s\\S]*?([A-Z][A-Za-z\\s]+?)(?=\\n|Skills|JOB)/i);
        if (qualMatch) data.min_qualification = qualMatch[1].trim();
    }

    // Experience from header or field
    var expMatch = document.body.innerText.match(/Required Experience[\\s\\S]*?(\\d+\\s*[-–]\\s*\\d+\\s*[Yy]ears?)/);
    if (expMatch) data.experience = expMatch[1];
    if (!data.experience) {
        expMatch = document.body.innerText.match(/(\\d+\\s*[-–]\\s*\\d+\\s*[Yy]ears?)/);
        if (expMatch) data.experience = expMatch[1];
    }

    // Dates
    var postedMatch = document.body.innerText.match(/Posted\\s*On[:\\s]*(\\d{1,2}\\s+\\w+\\s+\\d{4}|\\d{2}-\\w{3}-\\d{2,4})/i);
    if (postedMatch) data.posted_date = postedMatch[1];

    var endMatch = document.body.innerText.match(/End\\s*Date[:\\s]*(\\d{1,2}\\s+\\w+\\s+\\d{4}|\\d{2}-\\w{3}-\\d{2,4})/i);
    if (endMatch) data.end_date = endMatch[1];

    // JOB DESCRIPTION sections
    var jdSection = document.body.innerText;

    // Job Purpose
    var purposeMatch = jdSection.match(/Job\\s*Purpose[\\s\\S]*?([\\s\\S]{10,500}?)(?=Duties|Responsibilities|Required|$)/i);
    if (purposeMatch) data.job_purpose = purposeMatch[1].trim().substring(0, 500);

    // Responsibilities
    var respMatch = jdSection.match(/(?:Duties and Responsibilities|Responsibilities)[\\s\\S]*?([\\s\\S]{10,1000}?)(?=Required|Qualifications|$)/i);
    if (respMatch) data.responsibilities = respMatch[1].trim().substring(0, 1000);

    // Required Qualifications
    var qualReqMatch = jdSection.match(/Required Qualifications[\\s\\S]*?([\\s\\S]{10,500}?)(?=©|$)/i);
    if (qualReqMatch) data.qualifications = qualReqMatch[1].trim().substring(0, 500);

    // Department from header (format: "Department | Location")
    var deptLocMatch = document.body.innerText.match(/^([A-Za-z\\s]+)\\s*\\|\\s*([A-Za-z\\s\\-]+)$/m);
    if (deptLocMatch) {
        data.department = deptLocMatch[1].trim();
    }

    return data;
    """

    try:
        extracted = driver.execute_script(js_extract)
        if extracted:
            for key, value in extracted.items():
                if value and not job.get(key):
                    job[key] = value
    except Exception as e:
        print(f"    JS extraction error: {e}")

    # ==================== FALLBACK: REGEX ON PAGE TEXT ====================

    # Title - multiple strategies
    if not job["title"]:
        lines = [l.strip() for l in page_text.split('\n') if l.strip()]
        for line in lines[:15]:
            # Look for job title patterns
            if any(kw in line for kw in ['Manager', 'Executive', 'Officer', 'Engineer', 'Analyst', 'Specialist', 'Associate', 'Lead', 'Head', 'Director']):
                if 'JR00' not in line and len(line) > 10 and len(line) < 120:
                    if not any(skip in line for skip in ['Sign In', 'Register', 'Posted', 'End Date', 'Apply', 'Share']):
                        job["title"] = line
                        break

    # If still no title, try getting first substantial line
    if not job["title"]:
        lines = [l.strip() for l in page_text.split('\n') if l.strip()]
        for line in lines[:20]:
            if len(line) > 15 and len(line) < 100:
                if not any(skip in line for skip in ['Sign In', 'Register', 'Posted', 'End Date', 'Apply', 'Share', 'JR00', 'All Jobs', 'Filter']):
                    job["title"] = line
                    break

    # Department - look for pattern like "GL North West | Bhopal" or "MFI South | Location"
    if not job["department"]:
        # Common BFL department patterns
        dept_patterns = [
            r'(MFI\s+(?:South|North|East|West))',
            r'(GL\s+(?:North|South|East|West)(?:\s+West)?)',
            r'(Rural\s+Finance)',
            r'(Urban\s+Finance)',
            r'(Consumer\s+Finance)',
            r'(Business\s+Loans?)',
        ]
        for pattern in dept_patterns:
            match = re.search(pattern, page_text, re.I)
            if match:
                job["department"] = match.group(1).strip()
                break

    # Location fields from text
    if not job["country"]:
        if "India" in page_text:
            job["country"] = "India"

    if not job["state"]:
        state_match = re.search(r'State\s*[:\s]+([A-Z\s]+?)(?:\n|Region)', page_text)
        if state_match:
            job["state"] = state_match.group(1).strip()

    if not job["city"]:
        city_match = re.search(r'City\s*[:\s]+([A-Za-z\s]+?)(?:\n|Location)', page_text)
        if city_match:
            job["city"] = city_match.group(1).strip()

    if not job["location_name"]:
        loc_match = re.search(r'Location Name\s*[:\s]+([A-Za-z\s\-]+?)(?:\n|Tier)', page_text)
        if loc_match:
            job["location_name"] = loc_match.group(1).strip()

    if not job["tier"]:
        tier_match = re.search(r'Tier\s*[:\s]+(Tier\s*\d+|\d+)', page_text, re.I)
        if tier_match:
            job["tier"] = tier_match.group(1).strip()

    # Skills - extract all skill-like words from Skills section
    if not job["skills"] or job["skills"] == "AS PER JD":
        skills_section = re.search(r'Skills\s*([\s\S]*?)(?:Minimum Qualification|JOB DESCRIPTION)', page_text, re.I)
        if skills_section:
            skill_text = skills_section.group(1)
            # Extract capitalized words/phrases that look like skills
            skills = re.findall(r'[A-Z][A-Z\s&]+(?=[A-Z]|\n|$)', skill_text)
            skills = [s.strip() for s in skills if len(s.strip()) > 2 and len(s.strip()) < 40]
            if skills:
                job["skills"] = ", ".join(skills[:20])  # Limit to 20 skills

    # Experience
    if not job["experience"]:
        exp_match = re.search(r'(\d+\s*[-–]\s*\d+\s*[Yy]ears?)', page_text)
        if exp_match:
            job["experience"] = exp_match.group(1)

    # Dates
    if not job["posted_date"]:
        posted_match = re.search(r'Posted\s*On[:\s]*(\d{1,2}\s+\w+\s+\d{4})', page_text, re.I)
        if posted_match:
            job["posted_date"] = posted_match.group(1)

    if not job["end_date"]:
        end_match = re.search(r'End\s*Date[:\s]*(\d{1,2}\s+\w+\s+\d{4})', page_text, re.I)
        if end_match:
            job["end_date"] = end_match.group(1)

    return job


def validate_job_data(job):
    """
    Check if job data is valid. Returns quality score 0-100.
    Agentic: If score is low, we should retry extraction.
    """
    score = 0

    # Required fields (40 points)
    if job.get("jr_code"): score += 10
    if job.get("title") and len(job["title"]) > 5: score += 15
    if job.get("deep_link"): score += 15

    # Location fields (30 points)
    if job.get("city"): score += 10
    if job.get("state"): score += 10
    if job.get("location_name"): score += 10

    # Other fields (30 points)
    if job.get("experience"): score += 5
    if job.get("skills") and job["skills"] != "AS PER JD": score += 10
    if job.get("department"): score += 5
    if job.get("posted_date"): score += 5
    if job.get("job_purpose") or job.get("responsibilities"): score += 5

    return score


def go_to_page(driver, page_num):
    """Navigate to specific page number."""
    if page_num == 1:
        return True
    try:
        btn = driver.find_element(By.XPATH,
            f"//a[text()='{page_num}'] | //button[text()='{page_num}'] | "
            f"//*[contains(@class, 'page') and text()='{page_num}']"
        )
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
        time.sleep(0.3)
        driver.execute_script("arguments[0].click();", btn)
        time.sleep(2)
        wait_for_page(driver)
        return True
    except:
        return False


def reload_and_navigate(driver, page_num=1):
    """Reset to job listing and navigate to page."""
    try:
        driver.get(JOB_LIST_URL)
        wait_for_page(driver)
        time.sleep(1)
        if page_num > 1:
            go_to_page(driver, page_num)
        return True
    except:
        return False


def save_checkpoint(jobs, current_page, processed_jr_codes):
    """Save progress for resume capability."""
    checkpoint = {
        "jobs": jobs,
        "current_page": current_page,
        "processed_jr_codes": list(processed_jr_codes),
        "timestamp": datetime.now().isoformat()
    }
    with open(CHECKPOINT_FILE, 'w', encoding='utf-8') as f:
        json.dump(checkpoint, f, indent=2, ensure_ascii=False)


def load_checkpoint():
    """Load checkpoint if exists."""
    if CHECKPOINT_FILE.exists():
        try:
            with open(CHECKPOINT_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data.get("jobs", []), data.get("current_page", 1), set(data.get("processed_jr_codes", []))
        except:
            pass
    return [], 1, set()


def save_results(all_jobs):
    """Save final results to CSV and JSON."""
    # Deduplicate
    seen = set()
    unique = []
    for job in all_jobs:
        if job.get("jr_code") and job["jr_code"] not in seen:
            seen.add(job["jr_code"])
            unique.append(job)

    # CSV with all fields
    csv_path = OUTPUT_DIR / "bfl_jobs_complete.csv"
    fieldnames = [
        "jr_code", "title", "job_level", "department", "org_unit",
        "country", "state", "region", "city", "location_name", "tier",
        "experience", "posted_date", "end_date",
        "skills", "min_qualification",
        "job_purpose", "responsibilities", "qualifications",
        "deep_link", "scraped_at", "quality_score"
    ]

    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for job in unique:
            job["scraped_at"] = datetime.now().isoformat()
            job["quality_score"] = validate_job_data(job)
            writer.writerow({k: job.get(k, "") for k in fieldnames})

    # JSON
    json_path = OUTPUT_DIR / "bfl_jobs_complete.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(unique, f, indent=2, ensure_ascii=False)

    return unique, csv_path


def print_summary(jobs):
    """Print summary statistics."""
    # Quality stats
    scores = [validate_job_data(j) for j in jobs]
    avg_score = sum(scores) / len(scores) if scores else 0

    # Location stats
    city_counts = {}
    state_counts = {}
    for j in jobs:
        city = j.get("city") or "Unknown"
        state = j.get("state") or "Unknown"
        city_counts[city] = city_counts.get(city, 0) + 1
        state_counts[state] = state_counts.get(state, 0) + 1

    print(f"\n{'='*60}")
    print(f"SCRAPING COMPLETE")
    print(f"{'='*60}")
    print(f"Total jobs: {len(jobs)}")
    print(f"Average quality score: {avg_score:.1f}/100")
    print(f"\nTop States:")
    for s, c in sorted(state_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
        print(f"  {s:<30} {c:>5}")
    print(f"\nTop Cities:")
    for city, c in sorted(city_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
        print(f"  {city:<30} {c:>5}")


def main():
    parser = argparse.ArgumentParser(description="BFL Agentic Scraper v6")
    parser.add_argument("--pages", type=int, default=1, help="Number of pages to scrape")
    parser.add_argument("--headless", action="store_true", help="Run headless")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    args = parser.parse_args()

    print("=" * 60)
    print("BFL PEOPLESTRONG AGENTIC SCRAPER v6")
    print("=" * 60)
    print("Features: Multi-strategy extraction, validation, checkpointing")
    print(f"Pages: {args.pages}")
    print()

    driver = None
    all_jobs = []
    processed_jr_codes = set()
    start_page = 1

    # Resume from checkpoint if requested
    if args.resume:
        all_jobs, start_page, processed_jr_codes = load_checkpoint()
        if all_jobs:
            print(f"Resuming from checkpoint: {len(all_jobs)} jobs, page {start_page}")

    try:
        print("[1/3] Setting up Chrome...")
        driver = setup_driver(headless=args.headless)

        print("[2/3] Loading careers portal...")
        driver.get(JOB_LIST_URL)
        wait_for_page(driver)

        print("[3/3] Scraping jobs...\n")

        for page in range(start_page, args.pages + 1):
            print(f"--- PAGE {page} ---")

            # Navigate to page
            if page > 1:
                if not go_to_page(driver, page):
                    reload_and_navigate(driver, page)
                time.sleep(1)

            # Get JR codes (no element refs!)
            jr_codes = get_jr_codes_on_page(driver)
            new_codes = [c for c in jr_codes if c not in processed_jr_codes]
            print(f"  Found {len(jr_codes)} jobs, {len(new_codes)} new")

            if not jr_codes:
                print("  No jobs found. Stopping.")
                break

            # Process each job
            for idx, jr_code in enumerate(new_codes):
                print(f"  [{idx+1}/{len(new_codes)}] {jr_code}:", end=" ", flush=True)

                try:
                    # Click into detail page
                    if not find_and_click_job(driver, jr_code):
                        print("Click failed")
                        reload_and_navigate(driver, page)
                        continue

                    time.sleep(2)
                    wait_for_page(driver, timeout=10)

                    # Extract all data
                    job = extract_detail_page_complete(driver, jr_code)

                    # Validate quality
                    score = validate_job_data(job)

                    # If low quality, try once more
                    if score < 40:
                        time.sleep(1)
                        job = extract_detail_page_complete(driver, jr_code)
                        score = validate_job_data(job)

                    all_jobs.append(job)
                    processed_jr_codes.add(jr_code)

                    city = job.get("city", "?")[:15]
                    state = job.get("state", "?")[:15]
                    print(f"✓ {city}, {state} (score: {score})")

                    # Go back
                    driver.back()
                    time.sleep(1)
                    wait_for_page(driver)

                    # Verify on listing
                    if 'joblist' not in driver.current_url:
                        reload_and_navigate(driver, page)

                except Exception as e:
                    print(f"✗ {str(e)[:30]}")
                    reload_and_navigate(driver, page)
                    continue

            # Checkpoint after each page
            save_checkpoint(all_jobs, page + 1, processed_jr_codes)
            print(f"  Page {page} done. Total: {len(all_jobs)} jobs\n")

        # Final save
        print(f"\nSaving {len(all_jobs)} jobs...")
        unique_jobs, csv_path = save_results(all_jobs)
        print(f"  Saved to: {csv_path}")

        # Clean up checkpoint
        if CHECKPOINT_FILE.exists():
            CHECKPOINT_FILE.unlink()

        print_summary(unique_jobs)

    except KeyboardInterrupt:
        print("\n\nInterrupted! Saving progress...")
        if all_jobs:
            save_checkpoint(all_jobs, page, processed_jr_codes)
            save_results(all_jobs)
            print("Progress saved. Run with --resume to continue.")

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        if all_jobs:
            save_checkpoint(all_jobs, page, processed_jr_codes)
            save_results(all_jobs)

    finally:
        if driver:
            if not args.headless:
                input("\nPress Enter to close browser...")
            driver.quit()


if __name__ == "__main__":
    main()
