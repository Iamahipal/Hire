"""
The Cluster Engine - Location-Based Job Grouping
=================================================
Groups jobs by location (State → District → City) and
detects hiring hotspots for targeted distribution.

Usage:
    from cluster_engine import ClusterEngine
    engine = ClusterEngine()
    clusters = engine.cluster_jobs()
"""

import csv
import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import CLUSTER_CONFIG, SCRAPER_CONFIG, DATA_DIR, LOGS_DIR

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOGS_DIR / 'cluster_engine.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


@dataclass
class LocationCluster:
    """Represents a cluster of jobs in a specific location."""
    city: str
    state: str
    district: Optional[str]
    job_count: int
    departments: list[str]
    jobs: list[dict]
    is_hotspot: bool = False
    hotspot_reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class HotspotAlert:
    """Represents a hiring hotspot alert."""
    location: str
    job_count: int
    reason: str
    departments: list[str]
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


class ClusterEngine:
    """
    Clusters jobs by geographic location and detects hiring hotspots.

    Features:
    - Groups jobs by City/District/State
    - Detects sudden spikes in hiring (hotspots)
    - Normalizes location names for consistency
    - Supports custom state-district mappings
    """

    def __init__(self, config: dict = None):
        self.config = config or CLUSTER_CONFIG
        self.state_districts = self.config["state_districts"]
        self.min_threshold = self.config["min_jobs_threshold"]
        self.hotspot_threshold = self.config["hotspot_threshold"]

        # Build reverse lookup: city -> state
        self.city_to_state = {}
        for state, districts in self.state_districts.items():
            for district in districts:
                self.city_to_state[district.lower()] = state

        logger.info("ClusterEngine initialized")

    def _load_jobs(self, csv_path: Path = None) -> list[dict]:
        """Load jobs from CSV file."""
        csv_path = csv_path or SCRAPER_CONFIG["output_file"]

        if not csv_path.exists():
            logger.warning(f"Jobs file not found: {csv_path}")
            return []

        jobs = []
        try:
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    jobs.append(dict(row))

            logger.info(f"Loaded {len(jobs)} jobs from {csv_path}")
            return jobs

        except Exception as e:
            logger.error(f"Failed to load jobs: {e}")
            return []

    def _normalize_location(self, location: str) -> tuple[str, str, str]:
        """
        Normalize and parse location string.

        Returns: (city, district, state)
        """
        if not location:
            return ("Unknown", "Unknown", "Unknown")

        # Clean up the location string
        location = location.strip()
        location = re.sub(r'\s+', ' ', location)

        # Common patterns:
        # "Patna, Bihar"
        # "Patna"
        # "Sheohar District, Bihar"
        # "Mumbai - Maharashtra"

        # Split by common delimiters
        parts = re.split(r'[,\-–|/]', location)
        parts = [p.strip() for p in parts if p.strip()]

        city = parts[0] if parts else "Unknown"
        state = "Unknown"
        district = city  # Default district to city

        # Try to identify state
        if len(parts) >= 2:
            # Check if second part is a state
            potential_state = parts[-1].strip()
            if potential_state.lower() in [s.lower() for s in self.state_districts.keys()]:
                state = potential_state.title()

        # Try to find state from city name
        if state == "Unknown":
            city_lower = city.lower()
            # Remove common suffixes
            city_clean = re.sub(r'\s*(district|city|town|rural|urban)$', '', city_lower, flags=re.I)

            if city_clean in self.city_to_state:
                state = self.city_to_state[city_clean]

        # Normalize city name
        city = self._clean_city_name(city)

        return (city, district, state)

    def _clean_city_name(self, city: str) -> str:
        """Clean and standardize city name."""
        # Remove common suffixes
        city = re.sub(r'\s*(district|city|town|rural|urban)$', '', city, flags=re.I)

        # Title case
        city = city.strip().title()

        # Fix common misspellings/variations
        corrections = {
            "Patana": "Patna",
            "Mumabi": "Mumbai",
            "Banglore": "Bangalore",
            "Bangaluru": "Bangalore",
            "Calcutta": "Kolkata",
            "Bombay": "Mumbai",
            "Madras": "Chennai",
        }

        return corrections.get(city, city)

    def cluster_jobs(self, jobs: list[dict] = None) -> dict[str, LocationCluster]:
        """
        Cluster jobs by location.

        Args:
            jobs: Optional list of job dicts. If not provided, loads from CSV.

        Returns:
            Dictionary mapping location key to LocationCluster
        """
        if jobs is None:
            jobs = self._load_jobs()

        if not jobs:
            logger.warning("No jobs to cluster")
            return {}

        # Group jobs by normalized location
        location_groups = defaultdict(list)

        for job in jobs:
            city, district, state = self._normalize_location(job.get('location', ''))
            location_key = f"{city}_{state}".lower().replace(' ', '_')

            location_groups[location_key].append({
                'city': city,
                'district': district,
                'state': state,
                'job': job
            })

        # Create clusters
        clusters = {}

        for location_key, group in location_groups.items():
            if len(group) < self.min_threshold:
                continue

            city = group[0]['city']
            state = group[0]['state']
            district = group[0]['district']

            # Get unique departments
            departments = list(set(
                job['job'].get('department', 'General')
                for job in group
            ))

            # Check if hotspot
            is_hotspot = len(group) >= self.hotspot_threshold
            hotspot_reason = ""
            if is_hotspot:
                hotspot_reason = f"High hiring activity: {len(group)} jobs opened"

            cluster = LocationCluster(
                city=city,
                state=state,
                district=district,
                job_count=len(group),
                departments=departments,
                jobs=[g['job'] for g in group],
                is_hotspot=is_hotspot,
                hotspot_reason=hotspot_reason
            )

            clusters[location_key] = cluster
            logger.debug(f"Created cluster: {city}, {state} ({len(group)} jobs)")

        logger.info(f"Created {len(clusters)} location clusters")

        # Save clusters
        self._save_clusters(clusters)

        return clusters

    def _save_clusters(self, clusters: dict[str, LocationCluster]):
        """Save clusters to JSON file."""
        output_file = self.config["clustered_output"]
        output_file.parent.mkdir(parents=True, exist_ok=True)

        try:
            data = {key: cluster.to_dict() for key, cluster in clusters.items()}

            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            logger.info(f"Clusters saved to {output_file}")

        except Exception as e:
            logger.error(f"Failed to save clusters: {e}")

    def detect_hotspots(self, clusters: dict[str, LocationCluster] = None) -> list[HotspotAlert]:
        """
        Detect hiring hotspots (locations with unusually high activity).

        Args:
            clusters: Optional pre-computed clusters

        Returns:
            List of HotspotAlert objects
        """
        if clusters is None:
            clusters = self.cluster_jobs()

        hotspots = []

        for location_key, cluster in clusters.items():
            if cluster.is_hotspot:
                alert = HotspotAlert(
                    location=f"{cluster.city}, {cluster.state}",
                    job_count=cluster.job_count,
                    reason=cluster.hotspot_reason,
                    departments=cluster.departments
                )
                hotspots.append(alert)
                logger.info(f"Hotspot detected: {alert.location} ({alert.job_count} jobs)")

        # Save hotspot alerts
        if hotspots:
            self._save_hotspots(hotspots)

        return hotspots

    def _save_hotspots(self, hotspots: list[HotspotAlert]):
        """Save hotspot alerts to JSON file."""
        output_file = self.config["hotspot_report"]
        output_file.parent.mkdir(parents=True, exist_ok=True)

        try:
            data = [asdict(h) for h in hotspots]

            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            logger.info(f"Hotspot alerts saved to {output_file}")

        except Exception as e:
            logger.error(f"Failed to save hotspots: {e}")

    def get_jobs_by_state(self, state: str, clusters: dict[str, LocationCluster] = None) -> list[LocationCluster]:
        """Get all clusters for a specific state."""
        if clusters is None:
            clusters = self.cluster_jobs()

        return [
            c for c in clusters.values()
            if c.state.lower() == state.lower()
        ]

    def get_jobs_by_city(self, city: str, clusters: dict[str, LocationCluster] = None) -> Optional[LocationCluster]:
        """Get cluster for a specific city."""
        if clusters is None:
            clusters = self.cluster_jobs()

        for cluster in clusters.values():
            if cluster.city.lower() == city.lower():
                return cluster

        return None

    def get_summary(self, clusters: dict[str, LocationCluster] = None) -> dict:
        """Generate a summary of all clusters."""
        if clusters is None:
            clusters = self.cluster_jobs()

        if not clusters:
            return {"error": "No clusters available"}

        total_jobs = sum(c.job_count for c in clusters.values())
        hotspot_count = sum(1 for c in clusters.values() if c.is_hotspot)

        # Jobs by state
        state_counts = defaultdict(int)
        for c in clusters.values():
            state_counts[c.state] += c.job_count

        # Top locations
        top_locations = sorted(
            clusters.values(),
            key=lambda x: x.job_count,
            reverse=True
        )[:10]

        return {
            "total_jobs": total_jobs,
            "total_locations": len(clusters),
            "hotspot_count": hotspot_count,
            "jobs_by_state": dict(state_counts),
            "top_locations": [
                {"city": c.city, "state": c.state, "count": c.job_count}
                for c in top_locations
            ],
            "generated_at": datetime.now().isoformat()
        }

    def print_summary(self, clusters: dict[str, LocationCluster] = None):
        """Print a formatted summary to console."""
        summary = self.get_summary(clusters)

        if "error" in summary:
            print(f"Error: {summary['error']}")
            return

        print("\n" + "=" * 60)
        print("JOB CLUSTERING SUMMARY")
        print("=" * 60)

        print(f"\n{'Total Jobs:':<25} {summary['total_jobs']}")
        print(f"{'Total Locations:':<25} {summary['total_locations']}")
        print(f"{'Hotspots Detected:':<25} {summary['hotspot_count']}")

        print("\n--- Jobs by State ---")
        for state, count in sorted(summary['jobs_by_state'].items(), key=lambda x: x[1], reverse=True):
            print(f"  {state:<20} {count} jobs")

        print("\n--- Top Hiring Locations ---")
        for i, loc in enumerate(summary['top_locations'], 1):
            print(f"  {i}. {loc['city']}, {loc['state']:<15} ({loc['count']} jobs)")

        print("\n" + "=" * 60)


# Demo function
def demo_cluster():
    """Quick demo of the clustering engine."""
    print("=" * 60)
    print("CLUSTER ENGINE DEMO")
    print("=" * 60)

    engine = ClusterEngine()

    # Try to load and cluster jobs
    clusters = engine.cluster_jobs()

    if clusters:
        engine.print_summary(clusters)

        # Detect hotspots
        hotspots = engine.detect_hotspots(clusters)
        if hotspots:
            print("\n--- Hotspot Alerts ---")
            for h in hotspots:
                print(f"  ALERT: {h.location} - {h.job_count} jobs! ({h.reason})")
    else:
        print("No jobs found. Run the scraper first or load from CSV.")


if __name__ == "__main__":
    demo_cluster()
