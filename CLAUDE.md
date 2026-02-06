# CLAUDE.md - Hyper-Local Job Engine Project Guide

> This file is Claude's memory for this project. Update it as you learn new things.

## Project Overview

**Goal**: Build a job scraper for BFL (Bajaj Finance) PeopleStrong career portal that:
1. Extracts ALL job data accurately (JR code, title, department, location, etc.)
2. Generates hyper-local WhatsApp content for job distribution
3. Creates location-based hiring images

**Target URL**: https://bflcareers.peoplestrong.com/job/joblist

**Tech Stack**: Python, Selenium, Pillow (for images)

---

## CRITICAL LESSONS LEARNED (DO NOT REPEAT THESE MISTAKES)

### 1. Stale Element Reference Bug
**Problem**: Storing Selenium element references, then navigating away and back causes `StaleElementReferenceException`.

**Wrong approach (v4)**:
```python
cards = get_all_cards()  # Stores element references
for card in cards:
    card["element"].click()  # FAILS after first iteration - element is stale
    driver.back()
```

**Correct approach (v5+)**:
```python
jr_codes = get_jr_codes_only()  # Store ONLY strings, not elements
for jr_code in jr_codes:
    element = find_element_fresh(jr_code)  # Find fresh each time
    element.click()
    driver.back()
```

**Rule**: NEVER store element references if you plan to navigate. Store identifiers (strings) and re-find elements fresh.

---

### 2. Department/Location Extraction
**Problem**: PeopleStrong uses CSS visual separators (`|`) that don't appear in `.text` output. "Risk" and "Pune" show as "RiskPune" when concatenated.

**What doesn't work**:
- Looking for `|` character in text (it's CSS, not text)
- Assuming single line contains both dept and location

**What works**:
- **Detail page extraction**: Click into job detail page where data is properly labeled
- **Positional logic**: After JR code, next 2 lines are typically dept and location (separate lines)
- **JavaScript DOM inspection**: Query specific elements by class names

**Card text order** (from PeopleStrong):
```
[Title]
[JR Code]
[Department]        <- Line after JR code
[Location]          <- Next line
Posted On: XX | End Date: YY
[Experience]
```

---

### 3. Title Truncation
**Problem**: List view truncates long job titles with "..."

**Solution**: Click into detail page to get full title, OR use JavaScript to read the full `title` attribute or `data-*` attributes.

---

### 4. Pagination
**Site has**: ~7,000+ jobs across ~156 pages (45 jobs per page)

**Navigation**: Look for page number buttons/links. Use XPath:
```python
f"//a[text()='{page_num}'] | //button[text()='{page_num}']"
```

---

## WORKING EXTRACTION STRATEGIES

### Strategy A: Detail Page Click (Most Accurate, Slowest)
1. Get list of JR codes on page
2. For each JR code: find element fresh → click → extract from detail page → back
3. Detail page has labeled fields: "Department:", "Location:", etc.

### Strategy B: Positional Text Parsing (Fast, Less Accurate)
1. Get page text
2. Find JR codes, title is line before
3. Lines after JR code (before "Posted") are dept/location

### Strategy C: JavaScript DOM Injection (Fast, Medium Accuracy)
1. Inject JS to query specific CSS selectors
2. Extract data directly from DOM structure
3. Requires knowing exact class names (inspect the site first)

---

## FILE STRUCTURE

```
Hire/
├── CLAUDE.md              # This file - Claude's memory
├── bfl_scraper_v5.py      # Current working scraper (detail page click)
├── bfl_scraper_v4.py      # Broken - stale element bug
├── bfl_scraper_v3.py      # JS injection approach
├── bfl_scraper_v2.py      # Positional parsing
├── bfl_output/            # Scraper output directory
│   ├── bfl_jobs_complete.csv
│   └── bfl_jobs_complete.json
├── output/                # WhatsApp content output
│   ├── data/master_jobs.csv
│   └── whatsapp_captions.txt
├── config.py              # Configuration
├── scraper.py             # Generic scraper module
├── cluster_engine.py      # Location grouping
├── content_factory.py     # Image/caption generation
└── main.py                # CLI entry point
```

---

## AGENTIC SCRAPER PRINCIPLES

When building scrapers, make them **self-healing** and **adaptive**:

### 1. Multiple Extraction Strategies
Try multiple methods, pick best result:
```python
def extract_job(driver, jr_code):
    strategies = [
        extract_from_detail_page,
        extract_from_card_dom,
        extract_from_page_text,
    ]
    for strategy in strategies:
        result = strategy(driver, jr_code)
        if is_valid(result):
            return result
    return None
```

### 2. Data Validation
Check if extraction was successful:
```python
def is_valid_job(job):
    required = ["jr_code", "title"]
    has_required = all(job.get(f) for f in required)
    has_location = bool(job.get("location") or job.get("department"))
    return has_required and has_location
```

### 3. Automatic Recovery
If something fails, recover automatically:
```python
try:
    click_and_extract(jr_code)
except Exception:
    driver.get(JOB_LIST_URL)  # Reset to known state
    go_to_page(current_page)   # Navigate back
    continue                    # Try next job
```

### 4. Progress Saving
Save progress so you can resume:
```python
# Save after each page
save_checkpoint(all_jobs, current_page)

# On startup, check for checkpoint
if checkpoint_exists():
    all_jobs, start_page = load_checkpoint()
```

### 5. Smart Retries
Different retry strategies for different failures:
- Network error → Wait and retry (exponential backoff)
- Element not found → Try alternative selector
- Page not loaded → Increase wait time
- Stale element → Re-find element fresh

---

## KNOWN ISSUES & SOLUTIONS

| Issue | Solution |
|-------|----------|
| Can't access BFL from server | Run scraper on local machine |
| Stale element reference | Re-find elements fresh after navigation |
| Dept/location merged | Use detail page or positional parsing |
| Title truncated | Extract from detail page |
| Slow scraping | Use headless mode, reduce waits |
| Jobs missing | Check pagination, verify page loaded |

---

## COMMANDS

```bash
# Test scraper (1 page)
python bfl_scraper_v5.py --pages 1

# Full scrape (all pages) - takes time
python bfl_scraper_v5.py --pages 156

# Headless mode (no browser window)
python bfl_scraper_v5.py --pages 5 --headless

# Generate WhatsApp content from scraped data
python main.py generate --input bfl_output/bfl_jobs_complete.csv
```

---

## DETAIL PAGE STRUCTURE (v6 extraction targets)

The detail page (`/job/detail/JR00XXXXXX`) has these sections:

```
HEADER:
- Title, JR Code
- Department | Location (e.g., "GL North West | Bhopal - Kolar Road")
- Posted On, End Date, Required Experience

BASIC SECTION:
- Job Level: GB03
- Job Title: Full title with department

JOB LOCATION:
- Country: India
- State: MADHYA PRADESH
- Region: West
- City: Bhopal
- Location Name: Bhopal - Kolar Road
- Tier: Tier 2

SKILLS:
- List of skill tags (SALES, CASH MANAGEMENT, KYC, etc.)

MINIMUM QUALIFICATION:
- OTHERS, Graduate, etc.

JOB DESCRIPTION:
- Job Purpose
- Duties and Responsibilities
- Required Qualifications and Experience
```

**Key insight**: The card view shows "Country" as a label, not as location data!
Extract City, State, Location Name from the LABELED fields on detail page.

---

## NEXT STEPS / TODO

- [x] Create v6 "agentic" scraper with multi-strategy extraction
- [x] Add progress checkpointing for resume capability
- [x] Add data quality scoring
- [ ] Implement parallel extraction (multiple browser tabs)
- [ ] Add WhatsApp image generation from real scraped data
- [ ] Add location-based filtering to scraper

---

## UPDATE LOG

| Date | Update |
|------|--------|
| 2026-02-06 | Created CLAUDE.md with lessons from v1-v5 scrapers |
| 2026-02-06 | Documented stale element fix (v5) |
| 2026-02-06 | Added agentic scraper principles |
| 2026-02-07 | Created v6 agentic scraper with full detail page extraction |
| 2026-02-07 | Documented detail page structure (City, State, Location Name fields) |

---

*Last updated by Claude on 2026-02-06*
