import re
from dataclasses import dataclass
from typing import Optional

from packaging.version import Version

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


@dataclass
class VersionSource:
    """A source for fetching version information."""
    name: str
    url: str
    pattern: re.Pattern  # must capture version in group(1)


class IKMultimediaScraper(BaseScraper):
    """Scraper for IK Multimedia virtual instruments and effects.

    Uses KVR Audio and MacUpdater as version sources with consensus voting.
    """

    manufacturer_name = "IK Multimedia"
    manufacturer_slug = "ikmultimedia"
    manufacturer_website = "https://www.ikmultimedia.com"

    # KVR pattern: "Product Version</...><...>1.2.3"
    KVR_PATTERN = re.compile(r"Product Version\s*</[^>]+>\s*<[^>]+>\s*([\d.]+)", re.I)

    # MacUpdater pattern: version in title "v1.2.3" or in table "Version String:</td><td>1.2.3"
    MACUPDATER_PATTERN = re.compile(r"(?:Version String:</td>\s*<td>|<title>[^<]*v)([\d.]+)", re.I)

    # Known IK Multimedia products with version sources
    # Format: (name, category, kvr_slug, macupdater_bundle_id, product_url)
    KNOWN_PRODUCTS = [
        ("Hammond B-3X", "vst_plugin", "hammond-b-3x-by-ik-multimedia", "com.ikmultimedia.hammondb3x", "https://www.ikmultimedia.com/products/hammondb3x/"),
        ("MODO BASS 2", "vst_plugin", "modo-bass-2-by-ik-multimedia", "com.ikmultimedia.MODOBASS2", "https://www.ikmultimedia.com/products/modobass2/"),
        ("MODO DRUM", "vst_plugin", "modo-drum-by-ik-multimedia", "com.ikmultimedia.MODODRUM", "https://www.ikmultimedia.com/products/mododrum/"),
        ("SampleTank 4", "vst_plugin", "sampletank-4-by-ik-multimedia", "com.ikmultimedia.SampleTank4", "https://www.ikmultimedia.com/products/sampletank4/"),
        ("AmpliTube 5", "vst_plugin", "amplitube-5-by-ik-multimedia", "com.ikmultimedia.AmpliTube5", "https://www.ikmultimedia.com/products/amplitube5/"),
        ("T-RackS 5", "vst_plugin", "t-racks-5-by-ik-multimedia", "com.ikmultimedia.TRackS5", "https://www.ikmultimedia.com/products/trs5/"),
        ("Syntronik 2", "vst_plugin", "syntronik-2-by-ik-multimedia", "com.ikmultimedia.Syntronik2", "https://www.ikmultimedia.com/products/syntronik2/"),
        ("Miroslav Philharmonik 2", "vst_plugin", "miroslav-philharmonik-2-by-ik-multimedia", "com.ikmultimedia.Philharmonik2", "https://www.ikmultimedia.com/products/philharmonik2/"),
    ]

    # Fallback known versions when scraping fails (manually maintained)
    KNOWN_VERSIONS = {
        "Hammond B-3X": "1.3.5",
        "MODO BASS 2": "2.0.4",
        "MODO DRUM": "1.5.0",
        "SampleTank 4": "4.2.5",
        "AmpliTube 5": "5.10.9",
        "T-RackS 5": "5.10.1",
        "Syntronik 2": "2.1.3",
        "Miroslav Philharmonik 2": "2.1.0",
    }

    def _get_sources_for_product(self, kvr_slug: str, macupdater_bundle: str) -> list[VersionSource]:
        """Get version sources for a product."""
        sources = []
        if kvr_slug:
            sources.append(VersionSource(
                name="KVR",
                url=f"https://www.kvraudio.com/product/{kvr_slug}",
                pattern=self.KVR_PATTERN,
            ))
        if macupdater_bundle:
            sources.append(VersionSource(
                name="MacUpdater",
                url=f"https://macupdater.org/app_updates/appinfo/{macupdater_bundle}/index.html",
                pattern=self.MACUPDATER_PATTERN,
            ))
        return sources

    async def _fetch_version_from_source(self, source: VersionSource) -> Optional[str]:
        """Fetch version from a single source."""
        html = await self.fetch_page(source.url)
        if not html:
            return None
        match = source.pattern.search(html)
        return match.group(1) if match else None

    def _select_best_version(self, found: list[tuple[str, str]]) -> Optional[str]:
        """Select best version using consensus voting.

        Prefers version with highest count; breaks ties by highest semver.
        """
        if not found:
            return None

        # Parse versions
        parsed = []
        for name, v in found:
            try:
                parsed.append((name, Version(v), v))
            except Exception:
                # Invalid version format, skip
                continue

        if not parsed:
            return found[0][1]  # Return first raw version if none parse

        # Count occurrences per version
        counts: dict[Version, int] = {}
        for _, v, _ in parsed:
            counts[v] = counts.get(v, 0) + 1

        # Sort by (count, version) and pick best
        best = sorted(counts.items(), key=lambda kv: (kv[1], kv[0]))[-1][0]
        return str(best)

    async def fetch_device_list(self) -> ScraperResult:
        """Return the list of known IK Multimedia products."""
        devices = [
            ScrapedDevice(
                name=name,
                category=category,
                firmware_page_url=product_url,  # Use product URL as firmware page
                product_url=product_url,
            )
            for name, category, _, _, product_url in self.KNOWN_PRODUCTS
        ]
        return ScraperResult(success=True, devices=devices)

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        """Fetch versions from KVR and MacUpdater sources."""
        # Find product info
        product_info = None
        for name, category, kvr_slug, macupdater_bundle, product_url in self.KNOWN_PRODUCTS:
            if name == device_name or product_url == firmware_page_url:
                product_info = (kvr_slug, macupdater_bundle)
                break

        if not product_info:
            return ScraperResult(success=False, error=f"Unknown product: {device_name}")

        kvr_slug, macupdater_bundle = product_info
        sources = self._get_sources_for_product(kvr_slug, macupdater_bundle)

        # Fetch from all sources
        found: list[tuple[str, str]] = []
        for source in sources:
            version = await self._fetch_version_from_source(source)
            if version:
                found.append((source.name, version))

        # Select best version using consensus
        best_version = self._select_best_version(found) if found else None

        # Fall back to known versions if scraping fails
        if not best_version and device_name in self.KNOWN_VERSIONS:
            best_version = self.KNOWN_VERSIONS[device_name]

        firmware_versions = []
        if best_version:
            firmware_versions.append(ScrapedFirmware(version=best_version))

        return ScraperResult(success=True, firmware_versions=firmware_versions)
