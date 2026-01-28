# Hyper-Local Job Engine

A Python tool that scrapes job listings, clusters them by geographic location, and auto-generates shareable content (images + captions) for hyper-local distribution on WhatsApp/Telegram.

## The Problem It Solves

National job portals are "one-size-fits-all." A candidate in Sheohar, Bihar doesn't care about 500 national listings - they care about opportunities within 10km. This tool:

1. **Harvests** job data from career portals
2. **Clusters** jobs by city/district (not just state)
3. **Generates** ready-to-post content for each location
4. **Detects** hiring hotspots (sudden spikes in activity)

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run demo with sample data
python main.py demo

# Check generated content
ls output/images/
cat output/whatsapp_captions.txt
```

## Commands

| Command | Description |
|---------|-------------|
| `python main.py demo` | Run with sample data to test |
| `python main.py scrape` | Scrape jobs from career portal |
| `python main.py scrape --csv data.csv` | Load jobs from CSV file |
| `python main.py cluster` | Group jobs by location |
| `python main.py generate` | Create images and captions |
| `python main.py generate --city Patna` | Generate for specific city |
| `python main.py run` | Full pipeline (scrape → cluster → generate) |
| `python main.py status` | Check current data status |

## Output Structure

```
output/
├── data/
│   ├── master_jobs.csv          # All scraped jobs
│   ├── jobs_by_location.json    # Clustered data
│   └── hotspot_alerts.json      # Spike detection
├── images/
│   ├── hiring_patna.png
│   ├── hiring_sheohar.png
│   └── ...
└── whatsapp_captions.txt        # Copy-paste ready captions
```

## Configuration

Edit `config.py` to customize:

```python
# Change target URL
SCRAPER_CONFIG = {
    "target_url": "https://your-career-portal.com/jobs",
    ...
}

# Adjust image colors
CONTENT_CONFIG = {
    "image": {
        "background_color": "#1a365d",  # Dark blue
        "accent_color": "#f6ad55",       # Orange
        ...
    }
}
```

## Custom Template

To use your own background image:

1. Save your template as `templates/template.png` (1080x1080 recommended)
2. The engine will auto-overlay text on your template

## Architecture

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  SCRAPER    │───▶│  CLUSTER    │───▶│  CONTENT    │
│  (Selenium) │    │  (Location) │    │  (Pillow)   │
└─────────────┘    └─────────────┘    └─────────────┘
      │                  │                  │
      ▼                  ▼                  ▼
  master_jobs.csv   jobs_by_location   images + captions
```

## Ethical Usage

This tool is designed for **legitimate recruitment marketing**:

- Respect robots.txt and rate limits
- Don't scrape sites that explicitly prohibit it
- Get proper authorization before using company branding
- Don't spam - target relevant audiences only

## Dependencies

- `selenium` - Web scraping
- `Pillow` - Image generation
- `pandas` - Data processing (optional)
- `webdriver-manager` - Chrome driver management

## License

MIT License - Use responsibly.
