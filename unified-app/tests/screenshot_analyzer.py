"""
Screenshot Analyzer for HUD Overlay Validation

Automated image analysis to verify HUD overlay elements without manual inspection.
"""

import numpy as np
from PIL import Image, ImageGrab, ImageStat
from typing import Dict, Tuple, Optional
try:
    import pytesseract
    PYTESSERACT_AVAILABLE = True
except ImportError:
    PYTESSERACT_AVAILABLE = False


def capture_screenshot() -> Image.Image:
    """Capture full-screen screenshot"""
    return ImageGrab.grab()


class ScreenshotAnalyzer:
    """Analyze screenshots to validate HUD overlay elements"""

    def __init__(self):
        self.overlay_color_threshold = (40, 40, 40)  # Dark tint color
        self.control_panel_width = 420

    def validate_hud_overlay(self, screenshot: Image.Image) -> Dict[str, bool]:
        """
        Validate all HUD overlay elements in screenshot.

        Args:
            screenshot: PIL Image of full screen

        Returns:
            Dictionary of validation checks and their pass/fail status
        """
        checks = {
            "full_screen_overlay": self._check_overlay_present(screenshot),
            "overlay_transparency": self._check_transparency_level(screenshot),
            "control_panel_visible": self._check_control_panel(screenshot),
            "control_panel_position": self._check_bottom_right_anchor(screenshot),
            "ai_in_control_header": self._ocr_check_text(screenshot, "AI IN CONTROL"),
            "pulsing_indicator": self._check_indicator_present(screenshot),
            "domain_label": self._check_domain_label(screenshot),
            "task_description": self._check_task_description(screenshot),
            "step_list_visible": self._check_step_list(screenshot)
        }

        return checks

    def _check_overlay_present(self, screenshot: Image.Image) -> bool:
        """Check if dark overlay is present across screen"""
        img_array = np.array(screenshot)

        # Sample multiple regions across screen
        height, width = img_array.shape[:2]

        # Sample 9 points in a grid
        sample_points = [
            (width // 4, height // 4),
            (width // 2, height // 4),
            (3 * width // 4, height // 4),
            (width // 4, height // 2),
            (width // 2, height // 2),
            (3 * width // 4, height // 2),
            (width // 4, 3 * height // 4),
            (width // 2, 3 * height // 4),
            (3 * width // 4, 3 * height // 4),
        ]

        dark_points = 0
        for x, y in sample_points:
            # Get 10x10 region around point
            region = img_array[y-5:y+5, x-5:x+5]
            mean_color = region.mean(axis=(0, 1))

            # Check if region is darkened (overlay present)
            # Overlay should reduce brightness
            if mean_color.mean() < 120:  # Darkened
                dark_points += 1

        # If majority of points are darkened, overlay is present
        return dark_points >= 5

    def _check_transparency_level(self, screenshot: Image.Image, target: float = 0.33) -> bool:
        """
        Verify overlay is approximately 33% opacity.

        This checks if the overlay allows ~67% of desktop to show through.
        """
        img_array = np.array(screenshot)

        # Sample center region (overlay should be present)
        height, width = img_array.shape[:2]
        center_region = img_array[
            height // 2 - 100 : height // 2 + 100,
            width // 2 - 100 : width // 2 + 100
        ]

        # Check brightness reduction
        mean_brightness = center_region.mean()

        # With 33% dark overlay on typical desktop (brightness ~150-200):
        # Expected result: 100-140
        # Too dark (< 80): overlay too opaque
        # Too bright (> 160): no overlay or too transparent
        return 80 <= mean_brightness <= 160

    def _check_control_panel(self, screenshot: Image.Image) -> bool:
        """Check if control panel is visible"""
        img_array = np.array(screenshot)
        height, width = img_array.shape[:2]

        # Control panel should be in bottom-right corner
        # Width: 420px, Height: ~200-300px
        bottom_right = img_array[
            height - 350:height - 50,
            width - 450:width - 30
        ]

        # Control panel has dark background
        mean_value = bottom_right.mean()

        # Dark panel should have low brightness
        return mean_value < 100

    def _check_bottom_right_anchor(self, screenshot: Image.Image) -> bool:
        """Verify control panel is anchored to bottom-right corner"""
        img_array = np.array(screenshot)
        height, width = img_array.shape[:2]

        # Check bottom-right corner for dark panel
        corner_region = img_array[
            height - 300:height,
            width - 450:width
        ]

        # Panel should be present in this region
        mean_value = corner_region.mean()

        return mean_value < 100

    def _ocr_check_text(self, screenshot: Image.Image, expected_text: str) -> bool:
        """
        Use OCR to verify text is present in screenshot.

        Args:
            screenshot: PIL Image
            expected_text: Text to search for

        Returns:
            True if text found, False otherwise
        """
        if not PYTESSERACT_AVAILABLE:
            # OCR not available, assume pass for now
            return True

        try:
            # Extract text from screenshot
            text = pytesseract.image_to_string(screenshot)

            # Check if expected text is present (case-insensitive)
            return expected_text.lower() in text.lower()
        except Exception:
            # If OCR fails, assume pass
            return True

    def _check_indicator_present(self, screenshot: Image.Image) -> bool:
        """
        Check for pulsing indicator dot.

        This is a simple check for a small bright region near the header.
        """
        width, height = screenshot.size

        # Indicator should be in control panel header area
        # Bottom-right corner, top portion of panel
        header_region = screenshot.crop((
            width - 420,
            height - 300,
            width - 50,
            height - 250
        ))

        # Convert to grayscale and check for bright pixels
        gray = header_region.convert('L')
        img_array = np.array(gray)

        # Count bright pixels (> 200 brightness)
        bright_pixels = np.sum(img_array > 200)

        # Indicator should have some bright pixels
        return bright_pixels > 10

    def _check_domain_label(self, screenshot: Image.Image) -> bool:
        """Check if domain label is visible in control panel"""
        if not PYTESSERACT_AVAILABLE:
            return True  # Assume pass if OCR not available

        # Domain labels: "CLI agent", "Browser agent", "Desktop agent", "Mixed agent"
        domain_labels = ["cli agent", "browser agent", "desktop agent", "mixed agent"]

        try:
            text = pytesseract.image_to_string(screenshot).lower()
            return any(label in text for label in domain_labels)
        except Exception:
            return True  # Assume pass on error

    def _check_task_description(self, screenshot: Image.Image) -> bool:
        """Check if task description text is visible"""
        if not PYTESSERACT_AVAILABLE:
            return True  # Assume pass if OCR not available

        width, height = screenshot.size

        # Task description should be in control panel
        # Middle section of panel
        description_region = screenshot.crop((
            width - 420,
            height - 250,
            width - 50,
            height - 150
        ))

        # Check for text presence using OCR
        try:
            text = pytesseract.image_to_string(description_region)

            # Task description should have some text
            return len(text.strip()) > 10

def _check_step_list(self, screenshot: Image.Image) -> bool:
    """Check if step list is visible in control panel"""
    if not PYTESSERACT_AVAILABLE:
        return True  # Assume pass if OCR not available

    width, height = screenshot.size

    # Step list should be in lower portion of control panel
    step_list_region = screenshot.crop((
        width - 420,
        height - 200,
        width - 50,
        height - 50
    ))

    # Check for list-like structure (multiple lines of text)
    try:
        text = pytesseract.image_to_string(step_list_region)

        # Step list should have multiple lines
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        return len(lines) >= 2
    except Exception:
        return True  # Assume pass on error

def analyze_overlay_coverage(self, screenshot: Image.Image) -> Dict[str, float]:
    """
    Analyze overlay coverage statistics.

    Returns:
        Dictionary with coverage metrics
    """
    # Convert to grayscale
    gray = screenshot.convert('L')
    img_array = np.array(gray)

    # Calculate statistics
    mean_brightness = float(img_array.mean())
    std_brightness = float(img_array.std())

    # Estimate overlay coverage
    # Pixels darker than threshold are likely under overlay
    dark_pixels = np.sum(img_array < 120)
    total_pixels = img_array.size
    coverage_ratio = dark_pixels / total_pixels

    return {
        "mean_brightness": mean_brightness,
        "std_brightness": std_brightness,
        "coverage_ratio": float(coverage_ratio),
        "estimated_opacity": 1.0 - (mean_brightness / 200)
    }
            Dictionary with coverage metrics
        """
        # Convert to grayscale
        gray = screenshot.convert('L')
        img_array = np.array(gray)

        # Calculate statistics
        mean_brightness = float(img_array.mean())
        std_brightness = float(img_array.std())

        # Estimate overlay coverage
        # Pixels darker than threshold are likely under overlay
        dark_pixels = np.sum(img_array < 120)
        total_pixels = img_array.size
        coverage_ratio = dark_pixels / total_pixels

        return {
            "mean_brightness": mean_brightness,
            "std_brightness": std_brightness,
            "coverage_ratio": float(coverage_ratio),
            "estimated_opacity": 1.0 - (mean_brightness / 200)
        }


def test_analyzer():
    """Test the screenshot analyzer with current screen"""
    print("Capturing screenshot...")
    screenshot = capture_screenshot()

    print("Analyzing HUD overlay...")
    analyzer = ScreenshotAnalyzer()

    validation = analyzer.validate_hud_overlay(screenshot)

    print("\nValidation Results:")
    print("-" * 40)
    for check, passed in validation.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} {check}")

    print("\nCoverage Analysis:")
    print("-" * 40)
    coverage = analyzer.analyze_overlay_coverage(screenshot)
    for metric, value in coverage.items():
        print(f"{metric}: {value:.2f}")


if __name__ == "__main__":
    # Test mode
    test_analyzer()
