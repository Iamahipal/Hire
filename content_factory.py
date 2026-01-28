"""
The Content Factory - Viral Asset Generator
============================================
Generates WhatsApp-ready captions and hiring images
for each location cluster.

Usage:
    from content_factory import ContentFactory
    factory = ContentFactory()
    factory.generate_all()
"""

import json
import logging
import re
from pathlib import Path
from datetime import datetime
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from config import CONTENT_CONFIG, CLUSTER_CONFIG, OUTPUT_DIR, IMAGES_DIR, TEMPLATES_DIR, LOGS_DIR
from cluster_engine import ClusterEngine, LocationCluster

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOGS_DIR / 'content_factory.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class ContentFactory:
    """
    Generates shareable content assets for job distribution.

    Features:
    - WhatsApp-optimized captions with emojis and formatting
    - Auto-generated hiring images with customizable templates
    - Batch processing for all location clusters
    - Location-specific folders for easy distribution
    """

    def __init__(self, config: dict = None):
        self.config = config or CONTENT_CONFIG
        self.image_config = self.config["image"]
        self.caption_template = self.config["caption_template"]
        self.cluster_engine = ClusterEngine()

        # Ensure output directories exist
        IMAGES_DIR.mkdir(parents=True, exist_ok=True)

        logger.info("ContentFactory initialized")

    def _get_font(self, size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
        """
        Get font for image text rendering.

        Tries custom font first, then falls back to system fonts.
        """
        custom_font = self.image_config.get("font_path")

        font_paths = [
            custom_font,
            # Linux system fonts
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/TTF/DejaVuSans.ttf",
            # macOS system fonts
            "/System/Library/Fonts/Helvetica.ttc",
            "/Library/Fonts/Arial Bold.ttf" if bold else "/Library/Fonts/Arial.ttf",
            # Windows fonts
            "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/calibrib.ttf" if bold else "C:/Windows/Fonts/calibri.ttf",
        ]

        for font_path in font_paths:
            if font_path and Path(font_path).exists():
                try:
                    return ImageFont.truetype(font_path, size)
                except Exception:
                    continue

        # Fallback to default font
        logger.warning("Using default font - custom fonts not available")
        return ImageFont.load_default()

    def _hex_to_rgb(self, hex_color: str) -> tuple[int, int, int]:
        """Convert hex color to RGB tuple."""
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

    def _create_gradient_background(self, width: int, height: int,
                                    color1: str, color2: str) -> Image.Image:
        """Create a gradient background image."""
        img = Image.new('RGB', (width, height))
        draw = ImageDraw.Draw(img)

        r1, g1, b1 = self._hex_to_rgb(color1)
        r2, g2, b2 = self._hex_to_rgb(color2)

        for y in range(height):
            ratio = y / height
            r = int(r1 + (r2 - r1) * ratio)
            g = int(g1 + (g2 - g1) * ratio)
            b = int(b1 + (b2 - b1) * ratio)
            draw.line([(0, y), (width, y)], fill=(r, g, b))

        return img

    def _add_decorative_elements(self, draw: ImageDraw.Draw, width: int, height: int,
                                  accent_color: tuple):
        """Add decorative elements to the image."""
        # Top accent bar
        draw.rectangle([(0, 0), (width, 8)], fill=accent_color)

        # Bottom accent bar
        draw.rectangle([(0, height - 8), (width, height)], fill=accent_color)

        # Corner accents
        corner_size = 60
        draw.polygon([(0, 0), (corner_size, 0), (0, corner_size)], fill=accent_color)
        draw.polygon([(width, 0), (width - corner_size, 0), (width, corner_size)], fill=accent_color)

    def _text_wrap(self, text: str, font: ImageFont.FreeTypeFont,
                   max_width: int, draw: ImageDraw.Draw) -> list[str]:
        """Wrap text to fit within max_width."""
        words = text.split()
        lines = []
        current_line = []

        for word in words:
            test_line = ' '.join(current_line + [word])
            bbox = draw.textbbox((0, 0), test_line, font=font)
            if bbox[2] <= max_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(' '.join(current_line))
                current_line = [word]

        if current_line:
            lines.append(' '.join(current_line))

        return lines

    def generate_hiring_image(self, city_name: str, role_count: int,
                               departments: list[str] = None,
                               template_path: Path = None) -> Path:
        """
        Generate a hiring announcement image for a specific city.

        Args:
            city_name: Name of the city
            role_count: Number of open positions
            departments: List of departments with openings
            template_path: Optional path to custom background template

        Returns:
            Path to the generated image
        """
        width = self.image_config["width"]
        height = self.image_config["height"]

        # Load template or create gradient background
        if template_path and template_path.exists():
            img = Image.open(template_path)
            img = img.resize((width, height), Image.Resampling.LANCZOS)
        else:
            bg_color = self.image_config["background_color"]
            # Create gradient from dark to slightly lighter
            img = self._create_gradient_background(width, height, bg_color, "#2d4a73")

        draw = ImageDraw.Draw(img)

        # Colors
        text_color = self._hex_to_rgb(self.image_config["text_color"])
        accent_color = self._hex_to_rgb(self.image_config["accent_color"])

        # Add decorative elements
        self._add_decorative_elements(draw, width, height, accent_color)

        # Fonts
        title_size = self.image_config["title_font_size"]
        subtitle_size = self.image_config["subtitle_font_size"]
        body_size = self.image_config["body_font_size"]

        title_font = self._get_font(title_size, bold=True)
        subtitle_font = self._get_font(subtitle_size, bold=True)
        body_font = self._get_font(body_size)

        # Content positioning
        y_offset = 120

        # "WE ARE" text
        we_are_text = "WE ARE"
        bbox = draw.textbbox((0, 0), we_are_text, font=subtitle_font)
        text_width = bbox[2] - bbox[0]
        draw.text(((width - text_width) // 2, y_offset), we_are_text,
                  font=subtitle_font, fill=accent_color)
        y_offset += 80

        # "HIRING" - Large text
        hiring_text = "HIRING"
        bbox = draw.textbbox((0, 0), hiring_text, font=title_font)
        text_width = bbox[2] - bbox[0]
        draw.text(((width - text_width) // 2, y_offset), hiring_text,
                  font=title_font, fill=text_color)
        y_offset += 120

        # "IN" text
        in_text = "IN"
        bbox = draw.textbbox((0, 0), in_text, font=subtitle_font)
        text_width = bbox[2] - bbox[0]
        draw.text(((width - text_width) // 2, y_offset), in_text,
                  font=subtitle_font, fill=accent_color)
        y_offset += 80

        # City name - with box
        city_upper = city_name.upper()
        bbox = draw.textbbox((0, 0), city_upper, font=title_font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        # Draw accent box behind city name
        box_padding = 20
        box_left = (width - text_width) // 2 - box_padding
        box_top = y_offset - box_padding // 2
        box_right = (width + text_width) // 2 + box_padding
        box_bottom = y_offset + text_height + box_padding // 2

        draw.rectangle([box_left, box_top, box_right, box_bottom], fill=accent_color)
        draw.text(((width - text_width) // 2, y_offset), city_upper,
                  font=title_font, fill=self._hex_to_rgb(self.image_config["background_color"]))
        y_offset += text_height + 80

        # Role count
        count_text = f"{role_count} OPEN POSITIONS"
        bbox = draw.textbbox((0, 0), count_text, font=subtitle_font)
        text_width = bbox[2] - bbox[0]
        draw.text(((width - text_width) // 2, y_offset), count_text,
                  font=subtitle_font, fill=text_color)
        y_offset += 80

        # Departments (if provided)
        if departments and len(departments) > 0:
            dept_text = " | ".join(departments[:3])  # Limit to 3 departments
            if len(departments) > 3:
                dept_text += f" +{len(departments) - 3} more"

            wrapped = self._text_wrap(dept_text, body_font, width - 100, draw)
            for line in wrapped:
                bbox = draw.textbbox((0, 0), line, font=body_font)
                text_width = bbox[2] - bbox[0]
                draw.text(((width - text_width) // 2, y_offset), line,
                          font=body_font, fill=accent_color)
                y_offset += 45

        # Bottom text - Apply now
        y_offset = height - 120
        apply_text = "APPLY NOW"
        bbox = draw.textbbox((0, 0), apply_text, font=subtitle_font)
        text_width = bbox[2] - bbox[0]
        draw.text(((width - text_width) // 2, y_offset), apply_text,
                  font=subtitle_font, fill=text_color)

        # Save image
        city_slug = re.sub(r'[^a-zA-Z0-9]', '_', city_name.lower())
        output_path = IMAGES_DIR / f"hiring_{city_slug}.png"

        img.save(output_path, "PNG", quality=95)
        logger.info(f"Generated image: {output_path}")

        return output_path

    def generate_caption(self, cluster: LocationCluster) -> str:
        """
        Generate WhatsApp-ready caption for a location cluster.

        Args:
            cluster: LocationCluster object

        Returns:
            Formatted caption string
        """
        # Get the first job's deep link or a generic one
        link = cluster.jobs[0].get('deep_link', 'https://careers.example.com') if cluster.jobs else 'https://careers.example.com'

        # Format departments
        departments = ", ".join(cluster.departments[:3])
        if len(cluster.departments) > 3:
            departments += f" & {len(cluster.departments) - 3} more"

        # Create city tag (for hashtags)
        city_tag = re.sub(r'[^a-zA-Z0-9]', '', cluster.city)

        caption = self.caption_template.format(
            city=cluster.city,
            count=cluster.job_count,
            departments=departments,
            link=link,
            city_tag=city_tag
        )

        return caption

    def generate_all(self, clusters: dict[str, LocationCluster] = None) -> dict:
        """
        Generate all content assets for all location clusters.

        Args:
            clusters: Optional pre-computed clusters

        Returns:
            Dictionary with generation results
        """
        if clusters is None:
            clusters = self.cluster_engine.cluster_jobs()

        if not clusters:
            logger.warning("No clusters to generate content for")
            return {"error": "No clusters available"}

        results = {
            "generated_at": datetime.now().isoformat(),
            "images": [],
            "captions": [],
            "locations": []
        }

        all_captions = []

        for location_key, cluster in clusters.items():
            try:
                # Generate image
                image_path = self.generate_hiring_image(
                    city_name=cluster.city,
                    role_count=cluster.job_count,
                    departments=cluster.departments
                )
                results["images"].append(str(image_path))

                # Generate caption
                caption = self.generate_caption(cluster)
                all_captions.append(f"=== {cluster.city}, {cluster.state} ===\n{caption}\n")
                results["captions"].append({
                    "location": f"{cluster.city}, {cluster.state}",
                    "caption": caption
                })

                results["locations"].append({
                    "city": cluster.city,
                    "state": cluster.state,
                    "job_count": cluster.job_count,
                    "image_path": str(image_path),
                    "is_hotspot": cluster.is_hotspot
                })

                logger.info(f"Generated content for {cluster.city}, {cluster.state}")

            except Exception as e:
                logger.error(f"Failed to generate content for {location_key}: {e}")

        # Save all captions to a single file
        captions_file = self.config["captions_file"]
        try:
            with open(captions_file, 'w', encoding='utf-8') as f:
                f.write("WHATSAPP CAPTIONS - GENERATED BY HYPER-LOCAL JOB ENGINE\n")
                f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=" * 60 + "\n\n")
                f.write("\n".join(all_captions))

            logger.info(f"All captions saved to {captions_file}")
            results["captions_file"] = str(captions_file)

        except Exception as e:
            logger.error(f"Failed to save captions file: {e}")

        # Save results summary
        summary_file = OUTPUT_DIR / "generation_summary.json"
        try:
            with open(summary_file, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=2)
            logger.info(f"Summary saved to {summary_file}")
        except Exception as e:
            logger.error(f"Failed to save summary: {e}")

        return results

    def generate_for_city(self, city_name: str) -> Optional[dict]:
        """
        Generate content for a specific city.

        Args:
            city_name: Name of the city

        Returns:
            Dictionary with image path and caption, or None if city not found
        """
        cluster = self.cluster_engine.get_jobs_by_city(city_name)

        if not cluster:
            logger.warning(f"No cluster found for city: {city_name}")
            return None

        image_path = self.generate_hiring_image(
            city_name=cluster.city,
            role_count=cluster.job_count,
            departments=cluster.departments
        )

        caption = self.generate_caption(cluster)

        return {
            "city": cluster.city,
            "state": cluster.state,
            "job_count": cluster.job_count,
            "image_path": str(image_path),
            "caption": caption
        }


# Demo function
def demo_content():
    """Quick demo of content generation."""
    print("=" * 60)
    print("CONTENT FACTORY DEMO")
    print("=" * 60)

    factory = ContentFactory()

    # Generate sample image
    print("\nGenerating sample hiring image...")
    image_path = factory.generate_hiring_image(
        city_name="Sheohar",
        role_count=5,
        departments=["Sales", "Collections", "Credit"]
    )
    print(f"Image saved to: {image_path}")

    # Try full generation if clusters exist
    print("\nAttempting full content generation...")
    results = factory.generate_all()

    if "error" not in results:
        print(f"\nGenerated {len(results['images'])} images")
        print(f"Generated {len(results['captions'])} captions")
        print(f"Captions file: {results.get('captions_file', 'N/A')}")
    else:
        print(f"Note: {results['error']}")
        print("Run the scraper first to populate job data.")


if __name__ == "__main__":
    demo_content()
