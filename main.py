#!/usr/bin/env python3
"""
Hyper-Local Job Engine - CLI Interface
=======================================
A tool for scraping job listings, clustering by location,
and generating shareable content for hyper-local distribution.

Usage:
    python main.py scrape           # Scrape jobs from career portal
    python main.py cluster          # Cluster jobs by location
    python main.py generate         # Generate images and captions
    python main.py run              # Run full pipeline
    python main.py demo             # Run with sample data
    python main.py city <name>      # Generate for specific city

Author: Hyper-Local Job Engine
License: MIT
"""

import argparse
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from config import OUTPUT_DIR, IMAGES_DIR, DATA_DIR


def print_banner():
    """Print the application banner."""
    banner = """
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║     HYPER-LOCAL JOB ENGINE                               ║
    ║     ━━━━━━━━━━━━━━━━━━━━━                                ║
    ║     Scrape → Cluster → Distribute                         ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
    """
    print(banner)


def cmd_scrape(args):
    """Run the job scraper."""
    print("\n[SCRAPER] Starting job scraper...")

    from scraper import JobScraper

    scraper = JobScraper()

    if args.csv:
        print(f"[SCRAPER] Loading from CSV: {args.csv}")
        jobs = scraper.scrape_from_csv(args.csv)
    else:
        print(f"[SCRAPER] Scraping from: {scraper.config['target_url']}")
        jobs = scraper.scrape()

    print(f"\n[SCRAPER] Complete! {len(jobs)} new jobs found.")
    print(f"[SCRAPER] Data saved to: {scraper.config['output_file']}")


def cmd_cluster(args):
    """Run the clustering engine."""
    print("\n[CLUSTER] Starting location clustering...")

    from cluster_engine import ClusterEngine

    engine = ClusterEngine()
    clusters = engine.cluster_jobs()

    if clusters:
        engine.print_summary(clusters)

        hotspots = engine.detect_hotspots(clusters)
        if hotspots:
            print("\n[CLUSTER] HOTSPOT ALERTS:")
            for h in hotspots:
                print(f"  🔥 {h.location}: {h.job_count} jobs - {h.reason}")
    else:
        print("[CLUSTER] No jobs found. Run 'scrape' first or 'demo' for sample data.")


def cmd_generate(args):
    """Generate content assets."""
    print("\n[GENERATE] Starting content generation...")

    from content_factory import ContentFactory

    factory = ContentFactory()

    if args.city:
        print(f"[GENERATE] Generating for city: {args.city}")
        result = factory.generate_for_city(args.city)
        if result:
            print(f"\n[GENERATE] Success!")
            print(f"  City: {result['city']}, {result['state']}")
            print(f"  Jobs: {result['job_count']}")
            print(f"  Image: {result['image_path']}")
            print(f"\n  Caption:\n{result['caption']}")
        else:
            print(f"[GENERATE] City not found: {args.city}")
    else:
        results = factory.generate_all()
        if "error" not in results:
            print(f"\n[GENERATE] Complete!")
            print(f"  Images generated: {len(results['images'])}")
            print(f"  Captions generated: {len(results['captions'])}")
            print(f"  Output directory: {IMAGES_DIR}")
            print(f"  Captions file: {results.get('captions_file', 'N/A')}")
        else:
            print(f"[GENERATE] {results['error']}")
            print("[GENERATE] Run 'scrape' first or 'demo' for sample data.")


def cmd_run(args):
    """Run the full pipeline."""
    print_banner()
    print("[PIPELINE] Running full pipeline: Scrape → Cluster → Generate")

    # Step 1: Scrape
    if not args.skip_scrape:
        cmd_scrape(args)
    else:
        print("\n[PIPELINE] Skipping scrape (using existing data)")

    # Step 2: Cluster
    cmd_cluster(args)

    # Step 3: Generate
    cmd_generate(args)

    print("\n" + "=" * 60)
    print("[PIPELINE] COMPLETE!")
    print("=" * 60)
    print(f"\nOutput locations:")
    print(f"  📁 Data:    {DATA_DIR}")
    print(f"  🖼️  Images:  {IMAGES_DIR}")
    print(f"  📋 Output:  {OUTPUT_DIR}")
    print("\nNext steps:")
    print("  1. Check generated images in the output/images folder")
    print("  2. Copy captions from output/whatsapp_captions.txt")
    print("  3. Share on WhatsApp groups for your target locations!")


def cmd_demo(args):
    """Run demo with sample data."""
    print_banner()
    print("[DEMO] Running demo with sample data...")

    # Create sample data
    from scraper import demo_scrape
    demo_scrape()

    # Run cluster and generate
    cmd_cluster(args)
    cmd_generate(args)

    print("\n" + "=" * 60)
    print("[DEMO] COMPLETE!")
    print("=" * 60)
    print(f"\nCheck these locations:")
    print(f"  📁 Images: {IMAGES_DIR}")
    print(f"  📋 Captions: {OUTPUT_DIR / 'whatsapp_captions.txt'}")


def cmd_status(args):
    """Show current status and statistics."""
    print_banner()
    print("[STATUS] Checking system status...\n")

    # Check directories
    print("Directories:")
    for name, path in [("Output", OUTPUT_DIR), ("Images", IMAGES_DIR), ("Data", DATA_DIR)]:
        exists = "✓" if path.exists() else "✗"
        print(f"  {exists} {name}: {path}")

    # Check data files
    print("\nData files:")
    from config import SCRAPER_CONFIG, CLUSTER_CONFIG

    jobs_file = SCRAPER_CONFIG["output_file"]
    clusters_file = CLUSTER_CONFIG["clustered_output"]

    if jobs_file.exists():
        import csv
        with open(jobs_file, 'r') as f:
            job_count = sum(1 for _ in csv.DictReader(f))
        print(f"  ✓ Jobs file: {job_count} jobs")
    else:
        print(f"  ✗ Jobs file: Not found (run 'scrape' first)")

    if clusters_file.exists():
        import json
        with open(clusters_file, 'r') as f:
            cluster_count = len(json.load(f))
        print(f"  ✓ Clusters file: {cluster_count} locations")
    else:
        print(f"  ✗ Clusters file: Not found (run 'cluster' first)")

    # Count images
    if IMAGES_DIR.exists():
        image_count = len(list(IMAGES_DIR.glob("*.png")))
        print(f"  {'✓' if image_count > 0 else '✗'} Images: {image_count} generated")
    else:
        print(f"  ✗ Images: None generated")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Hyper-Local Job Engine - Scrape, Cluster, Distribute",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py demo              Run with sample data
  python main.py scrape            Scrape jobs from career portal
  python main.py scrape --csv data.csv  Load from CSV file
  python main.py cluster           Cluster jobs by location
  python main.py generate          Generate all content
  python main.py generate --city Patna  Generate for specific city
  python main.py run               Run full pipeline
  python main.py status            Show current status
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Scrape command
    scrape_parser = subparsers.add_parser("scrape", help="Scrape jobs from career portal")
    scrape_parser.add_argument("--csv", type=str, help="Load from CSV file instead of scraping")

    # Cluster command
    subparsers.add_parser("cluster", help="Cluster jobs by location")

    # Generate command
    gen_parser = subparsers.add_parser("generate", help="Generate images and captions")
    gen_parser.add_argument("--city", type=str, help="Generate for specific city only")

    # Run command (full pipeline)
    run_parser = subparsers.add_parser("run", help="Run full pipeline")
    run_parser.add_argument("--skip-scrape", action="store_true", help="Skip scraping, use existing data")
    run_parser.add_argument("--csv", type=str, help="Load from CSV file instead of scraping")

    # Demo command
    subparsers.add_parser("demo", help="Run demo with sample data")

    # Status command
    subparsers.add_parser("status", help="Show current status")

    # City shortcut command
    city_parser = subparsers.add_parser("city", help="Generate content for specific city")
    city_parser.add_argument("name", type=str, help="City name")

    args = parser.parse_args()

    if not args.command:
        print_banner()
        parser.print_help()
        return

    # Route to command handler
    commands = {
        "scrape": cmd_scrape,
        "cluster": cmd_cluster,
        "generate": cmd_generate,
        "run": cmd_run,
        "demo": cmd_demo,
        "status": cmd_status,
    }

    if args.command == "city":
        # Special handling for city command
        args.city = args.name
        cmd_generate(args)
    elif args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
