# Manual Data Export Guide for BFL Careers

The BFL PeopleStrong portal blocks server/automated requests. Here's how to get the data manually:

## Option 1: Run the Local Scraper (Recommended)

```bash
# On YOUR local machine (not server):
pip install selenium webdriver-manager pandas
python LOCAL_bfl_scraper.py
```

This will open a Chrome browser and automatically extract all jobs.

---

## Option 2: Browser Developer Tools Export

### Step 1: Open the Careers Portal
1. Go to https://bflcareers.peoplestrong.com
2. Navigate to the job listings page
3. Scroll down to load ALL jobs (keep scrolling until no more load)

### Step 2: Open Developer Tools
- Chrome: Press `F12` or `Ctrl+Shift+I`
- Firefox: Press `F12`

### Step 3: Go to Network Tab
1. Click on "Network" tab
2. Filter by "XHR" or "Fetch"
3. Look for API calls like:
   - `/api/job/jobs`
   - `/api/jobs`
   - `/job/list`

### Step 4: Copy the Response
1. Click on the API request
2. Go to "Response" tab
3. Copy the JSON data
4. Save as `bfl_raw_data.json`

### Step 5: Convert to CSV
Run this script to convert:

```python
import json
import csv

with open('bfl_raw_data.json', 'r') as f:
    data = json.load(f)

# Adjust 'jobs' key based on actual structure
jobs = data.get('jobs') or data.get('data') or data

with open('bfl_jobs.csv', 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=[
        'jr_code', 'title', 'department', 'location',
        'experience', 'employment_type', 'deep_link'
    ])
    writer.writeheader()
    for job in jobs:
        writer.writerow({
            'jr_code': job.get('jobId', ''),
            'title': job.get('title', ''),
            'department': job.get('department', ''),
            'location': job.get('location', ''),
            'experience': job.get('experience', ''),
            'employment_type': job.get('employmentType', ''),
            'deep_link': job.get('link', ''),
        })
```

---

## Option 3: Copy-Paste from Table

If the portal shows jobs in a table:

1. Select all visible job data
2. Copy (`Ctrl+C`)
3. Paste into Excel/Google Sheets
4. Export as CSV
5. Rename columns to match template:
   - `jr_code, title, department, location, experience, employment_type, deep_link`

---

## CSV Structure Required

Your CSV should have these columns:

| Column | Description | Example |
|--------|-------------|---------|
| jr_code | Job ID | JR_12345 |
| title | Job Title | Sales Officer |
| department | Department/Function | Sales |
| location | City, State | Patna, Bihar |
| experience | Required Experience | 2-4 years |
| employment_type | Job Type | Full-Time |
| deep_link | Direct URL | https://... |

See `output/data/bfl_jobs_TEMPLATE.csv` for example format.

---

## After Getting the Data

Once you have the CSV, run:

```bash
# Process with the Hyper-Local Job Engine
python main.py scrape --csv your_bfl_data.csv
python main.py cluster
python main.py generate
```

This will:
1. Load your data
2. Cluster by location
3. Generate images for each location
