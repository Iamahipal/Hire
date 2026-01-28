#!/usr/bin/env python3
"""
BFL PeopleStrong Career Portal Scraper (API-based)
==================================================
Attempts to scrape job data using API endpoints or direct HTTP requests.
No browser required.
"""

import csv
import json
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# Output paths
OUTPUT_DIR = Path(__file__).parent / "output" / "data"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = "https://bflcareers.peoplestrong.com"
JOB_LIST_URL = f"{BASE_URL}/job/joblist"

# Common headers to mimic browser
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# Common PeopleStrong API endpoints to try
API_ENDPOINTS = [
    "/api/jobs",
    "/api/job/list",
    "/api/v1/jobs",
    "/api/v1/job/list",
    "/api/careers/jobs",
    "/api/vacancy/list",
    "/job/api/list",
    "/career/api/jobs",
    "/rest/jobs",
    "/rest/job/list",
]


def try_api_endpoints(session):
    """Try common API endpoints to find job data."""
    print("\n[1/3] Searching for API endpoints...")

    for endpoint in API_ENDPOINTS:
        url = BASE_URL + endpoint
        try:
            # Try GET
            resp = session.get(url, timeout=10)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    if isinstance(data, (list, dict)):
                        print(f"  Found API at: {endpoint}")
                        return data, url
                except json.JSONDecodeError:
                    pass

            # Try POST (some APIs require POST)
            resp = session.post(url, json={}, timeout=10)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    if isinstance(data, (list, dict)):
                        print(f"  Found API at: {endpoint} (POST)")
                        return data, url
                except json.JSONDecodeError:
                    pass

        except requests.RequestException:
            continue

    print("  No direct API found. Will parse HTML.")
    return None, None


def scrape_html_page(session):
    """Scrape the job listing page HTML."""
    print("\n[2/3] Fetching HTML page...")

    try:
        resp = session.get(JOB_LIST_URL, timeout=30)
        resp.raise_for_status()

        # Check if we got HTML
        content_type = resp.headers.get('content-type', '')
        if 'html' not in content_type.lower():
            print(f"  Unexpected content type: {content_type}")

        return resp.text

    except requests.RequestException as e:
        print(f"  Error fetching page: {e}")
        return None


def find_embedded_json(html):
    """Look for JSON data embedded in the HTML (common in React/Vue apps)."""
    print("  Looking for embedded JSON data...")

    # Common patterns for embedded data
    patterns = [
        r'window\.__INITIAL_STATE__\s*=\s*({.+?});',
        r'window\.INITIAL_DATA\s*=\s*({.+?});',
        r'window\.pageData\s*=\s*({.+?});',
        r'var\s+jobsData\s*=\s*(\[.+?\]);',
        r'var\s+jobs\s*=\s*(\[.+?\]);',
        r'"jobs"\s*:\s*(\[.+?\])',
        r'"jobList"\s*:\s*(\[.+?\])',
        r'data-jobs\s*=\s*\'(\[.+?\])\'',
    ]

    for pattern in patterns:
        match = re.search(pattern, html, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                print(f"  Found embedded JSON data!")
                return data
            except json.JSONDecodeError:
                continue

    return None


def parse_html_jobs(html):
    """Parse job listings from HTML."""
    print("  Parsing HTML for job listings...")

    soup = BeautifulSoup(html, 'html.parser')
    jobs = []

    # Try different selectors
    selectors = [
        ('div', {'class': re.compile(r'job[-_]?card', re.I)}),
        ('div', {'class': re.compile(r'job[-_]?item', re.I)}),
        ('div', {'class': re.compile(r'job[-_]?listing', re.I)}),
        ('article', {'class': re.compile(r'job', re.I)}),
        ('li', {'class': re.compile(r'job', re.I)}),
        ('div', {'class': 'card'}),
        ('tr', {'class': re.compile(r'job', re.I)}),
    ]

    job_elements = []
    for tag, attrs in selectors:
        elements = soup.find_all(tag, attrs)
        if elements:
            print(f"  Found {len(elements)} elements with {tag} {attrs}")
            job_elements = elements
            break

    if not job_elements:
        # Try finding all links that look like job links
        print("  Trying to find job links...")
        links = soup.find_all('a', href=re.compile(r'/job/\d+|/career/\d+|/vacancy/\d+'))
        print(f"  Found {len(links)} job links")

        for link in links:
            href = link.get('href', '')
            title = link.get_text(strip=True)

            if not title or len(title) < 3:
                continue

            # Extract job ID
            match = re.search(r'/(?:job|career|vacancy)/(\d+)', href)
            jr_code = f"JR_{match.group(1)}" if match else f"JOB_{len(jobs)}"

            # Make absolute URL
            deep_link = urljoin(BASE_URL, href)

            jobs.append({
                "jr_code": jr_code,
                "title": title,
                "location": "",
                "department": "",
                "experience": "",
                "employment_type": "",
                "posted_date": "",
                "deep_link": deep_link,
            })

    else:
        for i, elem in enumerate(job_elements):
            job = extract_job_from_element(elem, i)
            if job:
                jobs.append(job)

    return jobs


def extract_job_from_element(elem, index):
    """Extract job details from a BeautifulSoup element."""
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

    text = elem.get_text(' ', strip=True)

    # Title
    title_elem = elem.find(['h1', 'h2', 'h3', 'h4', 'a'])
    if title_elem:
        job["title"] = title_elem.get_text(strip=True)

    # Location
    loc_elem = elem.find(class_=re.compile(r'location', re.I))
    if loc_elem:
        job["location"] = loc_elem.get_text(strip=True)
    else:
        loc_match = re.search(r'(?:Location|City)[:\s]*([A-Za-z\s,]+)', text, re.I)
        if loc_match:
            job["location"] = loc_match.group(1).strip()[:50]

    # Department
    dept_elem = elem.find(class_=re.compile(r'department|category', re.I))
    if dept_elem:
        job["department"] = dept_elem.get_text(strip=True)

    # Experience
    exp_match = re.search(r'(\d+[\s-]*(?:to|-)?\s*\d*\s*(?:years?|yrs?))', text, re.I)
    if exp_match:
        job["experience"] = exp_match.group(1).strip()

    # Link
    link = elem.find('a', href=True)
    if link:
        href = link.get('href', '')
        job["deep_link"] = urljoin(BASE_URL, href)

        # Extract JR code from URL
        match = re.search(r'/(?:job|career|vacancy)/(\d+)', href)
        if match:
            job["jr_code"] = f"JR_{match.group(1)}"

    if not job["jr_code"]:
        job["jr_code"] = f"JOB_{index}"

    return job if job["title"] else None


def fetch_job_details(session, jobs, max_jobs=50):
    """Fetch detailed info for each job (rate limited)."""
    print(f"\n[3/3] Fetching details for {min(len(jobs), max_jobs)} jobs...")

    detailed_jobs = []
    for i, job in enumerate(jobs[:max_jobs]):
        if not job.get("deep_link"):
            detailed_jobs.append(job)
            continue

        try:
            resp = session.get(job["deep_link"], timeout=15)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')

                # Try to extract more details
                text = soup.get_text(' ', strip=True)

                # Location
                if not job["location"]:
                    loc_match = re.search(r'(?:Location|City|Place)[:\s]*([A-Za-z\s,]+)', text, re.I)
                    if loc_match:
                        job["location"] = loc_match.group(1).strip()[:100]

                # Department
                if not job["department"]:
                    dept_match = re.search(r'(?:Department|Function|Team)[:\s]*([A-Za-z\s&]+)', text, re.I)
                    if dept_match:
                        job["department"] = dept_match.group(1).strip()[:50]

                # Experience
                if not job["experience"]:
                    exp_match = re.search(r'(?:Experience|Exp)[:\s]*(\d+[\s-]*(?:to|-)?\s*\d*\s*(?:years?|yrs?))', text, re.I)
                    if exp_match:
                        job["experience"] = exp_match.group(1).strip()

            detailed_jobs.append(job)

            if (i + 1) % 10 == 0:
                print(f"  Fetched {i + 1}/{min(len(jobs), max_jobs)} job details...")

            time.sleep(0.5)  # Rate limiting

        except Exception as e:
            detailed_jobs.append(job)
            continue

    return detailed_jobs


def save_to_csv(jobs, filename="bfl_jobs_master.csv"):
    """Save jobs to CSV."""
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


def save_summary(jobs):
    """Print and save summary."""
    # Count by department
    dept_counts = {}
    location_counts = {}

    for job in jobs:
        dept = job.get("department") or "Unknown"
        loc = job.get("location") or "Unknown"

        dept_counts[dept] = dept_counts.get(dept, 0) + 1
        location_counts[loc] = location_counts.get(loc, 0) + 1

    # Save summary CSV
    summary_path = OUTPUT_DIR / "bfl_jobs_summary.csv"
    with open(summary_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["Category", "Name", "Job Count"])

        writer.writerow([])
        writer.writerow(["DEPARTMENT", "", ""])
        for dept, count in sorted(dept_counts.items(), key=lambda x: x[1], reverse=True):
            writer.writerow(["", dept, count])

        writer.writerow([])
        writer.writerow(["LOCATION", "", ""])
        for loc, count in sorted(location_counts.items(), key=lambda x: x[1], reverse=True):
            writer.writerow(["", loc, count])

    # Print summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    print(f"\nTotal Jobs: {len(jobs)}")

    print(f"\nBy Department:")
    for dept, count in sorted(dept_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
        print(f"  {dept:<35} {count:>5} jobs")

    print(f"\nBy Location:")
    for loc, count in sorted(location_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
        print(f"  {loc:<35} {count:>5} jobs")

    return summary_path


def main():
    """Main scraping function."""
    print("=" * 60)
    print("BFL PEOPLESTRONG CAREER SCRAPER (API/HTTP)")
    print("=" * 60)
    print(f"\nTarget: {JOB_LIST_URL}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    session = requests.Session()
    session.headers.update(HEADERS)

    jobs = []

    # Try API first
    api_data, api_url = try_api_endpoints(session)

    if api_data:
        print(f"  Processing API data...")
        if isinstance(api_data, list):
            jobs = api_data
        elif isinstance(api_data, dict):
            # Look for jobs in common keys
            for key in ['jobs', 'data', 'results', 'items', 'jobList', 'vacancies']:
                if key in api_data and isinstance(api_data[key], list):
                    jobs = api_data[key]
                    break
    else:
        # Fetch and parse HTML
        html = scrape_html_page(session)

        if html:
            # Try to find embedded JSON first
            embedded = find_embedded_json(html)
            if embedded:
                if isinstance(embedded, list):
                    jobs = embedded
                elif isinstance(embedded, dict):
                    for key in ['jobs', 'data', 'results', 'items', 'jobList']:
                        if key in embedded:
                            jobs = embedded[key]
                            break

            if not jobs:
                # Parse HTML
                jobs = parse_html_jobs(html)

    if jobs:
        print(f"\n  Found {len(jobs)} jobs!")

        # Normalize job data if it's from API
        if jobs and isinstance(jobs[0], dict):
            normalized = []
            for i, j in enumerate(jobs):
                normalized.append({
                    "jr_code": j.get('jr_code') or j.get('jobId') or j.get('id') or f"JOB_{i}",
                    "title": j.get('title') or j.get('jobTitle') or j.get('name') or "",
                    "department": j.get('department') or j.get('function') or j.get('category') or "",
                    "location": j.get('location') or j.get('city') or j.get('place') or "",
                    "experience": j.get('experience') or j.get('exp') or "",
                    "employment_type": j.get('employmentType') or j.get('type') or "",
                    "posted_date": j.get('postedDate') or j.get('createdAt') or "",
                    "deep_link": j.get('deep_link') or j.get('link') or j.get('url') or "",
                })
            jobs = normalized

        # Save to CSV
        save_to_csv(jobs)

        # Save JSON
        json_path = OUTPUT_DIR / "bfl_jobs_master.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(jobs, f, indent=2, ensure_ascii=False)
        print(f"Saved JSON to: {json_path}")

        # Summary
        save_summary(jobs)

    else:
        print("\nNo jobs found. Saving page source for analysis...")
        html = scrape_html_page(session)
        if html:
            debug_path = OUTPUT_DIR / "debug_page.html"
            with open(debug_path, 'w', encoding='utf-8') as f:
                f.write(html)
            print(f"Page saved to: {debug_path}")


if __name__ == "__main__":
    main()
