"""
Configuration for the Hyper-Local Job Engine
============================================
Modify these settings to customize the scraper behavior.
"""

import os
from pathlib import Path

# ============================================================================
# PATHS
# ============================================================================
BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
IMAGES_DIR = OUTPUT_DIR / "images"
DATA_DIR = OUTPUT_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
TEMPLATES_DIR = BASE_DIR / "templates"

# Create directories if they don't exist
for dir_path in [OUTPUT_DIR, IMAGES_DIR, DATA_DIR, LOGS_DIR, TEMPLATES_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)

# ============================================================================
# SCRAPER SETTINGS
# ============================================================================
SCRAPER_CONFIG = {
    # Target URL - Change this to scrape different career portals
    "target_url": "https://bflcareers.peoplestrong.com/job/joblist",

    # Request settings (be respectful!)
    "request_delay": 2.0,  # Seconds between requests
    "page_load_timeout": 30,  # Seconds to wait for page load
    "max_retries": 3,
    "retry_delay": 5,  # Seconds between retries

    # Scroll settings for infinite scroll pages
    "scroll_pause_time": 2.0,
    "max_scroll_attempts": 50,  # Prevent infinite loops

    # User agent rotation (appear as normal browser)
    "user_agents": [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    ],

    # Output file
    "output_file": DATA_DIR / "master_jobs.csv",
    "archive_dir": DATA_DIR / "archive",
}

# ============================================================================
# LOCATION CLUSTERING
# ============================================================================
CLUSTER_CONFIG = {
    # Minimum jobs to consider a location "active"
    "min_jobs_threshold": 1,

    # Hotspot detection - alert if jobs spike above this
    "hotspot_threshold": 5,

    # State to District mapping for India (expandable)
    "state_districts": {
        "Bihar": [
            "Patna", "Gaya", "Bhagalpur", "Muzaffarpur", "Purnia", "Darbhanga",
            "Arrah", "Begusarai", "Katihar", "Munger", "Chhapra", "Saharsa",
            "Sasaram", "Hajipur", "Dehri", "Siwan", "Motihari", "Nawada",
            "Bagaha", "Buxar", "Kishanganj", "Sitamarhi", "Jamalpur", "Jehanabad",
            "Aurangabad", "Sheohar", "Madhubani", "Samastipur", "Bettiah"
        ],
        "Maharashtra": [
            "Mumbai", "Pune", "Nagpur", "Thane", "Nashik", "Aurangabad",
            "Solapur", "Kolhapur", "Amravati", "Nanded", "Sangli", "Jalgaon"
        ],
        "Uttar Pradesh": [
            "Lucknow", "Kanpur", "Ghaziabad", "Agra", "Varanasi", "Meerut",
            "Allahabad", "Bareilly", "Aligarh", "Moradabad", "Gorakhpur"
        ],
        # Add more states as needed
    },

    # Output files
    "clustered_output": DATA_DIR / "jobs_by_location.json",
    "hotspot_report": DATA_DIR / "hotspot_alerts.json",
}

# ============================================================================
# CONTENT GENERATION
# ============================================================================
CONTENT_CONFIG = {
    # WhatsApp caption template
    "caption_template": """🚨 *{city} Hiring Alert!*

We have *{count} open roles* in {departments}

📍 Location: {city}
🏢 Company: Bajaj Finance

🔗 Apply Now: {link}

👇 *Forward to help someone find their dream job!*

#Jobs #{city_tag} #Hiring #BajajFinance""",

    # Image generation settings
    "image": {
        "width": 1080,
        "height": 1080,
        "background_color": "#1a365d",  # Dark blue
        "accent_color": "#f6ad55",  # Orange accent
        "text_color": "#ffffff",  # White text

        # Font sizes (will auto-scale if needed)
        "title_font_size": 72,
        "subtitle_font_size": 48,
        "body_font_size": 36,

        # You can specify a custom font path, or use default
        "font_path": None,  # Set to path like "/path/to/font.ttf" for custom font
    },

    # Output
    "captions_file": OUTPUT_DIR / "whatsapp_captions.txt",
    "images_dir": IMAGES_DIR,
}

# ============================================================================
# LOGGING
# ============================================================================
LOGGING_CONFIG = {
    "level": "INFO",
    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    "file": LOGS_DIR / "job_engine.log",
}
