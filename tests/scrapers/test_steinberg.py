import pytest


def test_steinberg_title_pattern_ignores_user_threads():
    """Only maintenance announcements count -- not threads that quote a version.

    The forum is full of titles carrying a real version number that announce
    nothing, and a loose pattern reads a user's bug report as a release.
    """
    from src.scrapers.plugins.steinberg import SteinbergScraper

    pat = SteinbergScraper._title_pattern("HALion")

    assert pat.match("HALion 7.1.40 Maintenance available").group(1) == "7.1.40"
    assert pat.match("New HALion (HS) 7.1.10 Maintenance available").group(1) == "7.1.10"
    assert pat.match("HALion (Sonic) 7.0.10 Maintenance Update available now").group(1) == "7.0.10"
    assert pat.match("HALion 7.1.20 and HALion Sonic 7.1.20 Maintenance").group(1) == "7.1.20"

    # A user reporting a problem with a release is not the release announcement.
    assert pat.match("Error messages after installing HALion (Sonic) 7.1.30 maintenance update") is None
    # Anchored at the product, so a thread that merely mentions it does not match.
    assert pat.match("Problem in Dorico with Update of Halion 7.1.30 / Halion Sonic 7.1.30") is None
    # No version at all.
    assert pat.match("HALion Maintenance Update available now") is None


@pytest.mark.asyncio
async def test_steinberg_wrong_category_announcements_are_dropped():
    """Category is checked as well as title, so a same-named thread elsewhere is ignored."""
    from src.scrapers.plugins.steinberg import SteinbergScraper

    scraper = SteinbergScraper()
    scraper._categories = {1: "Groove Agent", 2: "Cubase"}
    scraper._searches["Groove Agent maintenance"] = [
        {"title": "New Groove Agent (SE) 5.2.30 Maintenance available",
         "category_id": 1, "created_at": "2025-10-15T09:00:00.000Z", "id": 11, "slug": "ga-5-2-30"},
        {"title": "Groove Agent 5.1.20 Maintenance available",
         "category_id": 2, "created_at": "2023-04-13T09:00:00.000Z", "id": 12, "slug": "elsewhere"},
    ]

    result = await scraper.fetch_firmware_versions("Groove Agent SE", "https://www.steinberg.net")

    assert result.success is True
    assert [fw.version for fw in result.firmware_versions] == ["5.2.30"]
    assert result.firmware_versions[0].release_date.strftime("%Y-%m-%d") == "2025-10-15"


@pytest.mark.asyncio
async def test_steinberg_unreadable_forum_fails_rather_than_reporting_no_firmware():
    """A dead search API must not look like a product with no releases."""
    from src.scrapers.plugins.steinberg import SteinbergScraper

    scraper = SteinbergScraper()

    async def no_json(url):
        return None

    scraper._get_json = no_json
    result = await scraper.fetch_firmware_versions("Cubase", "https://www.steinberg.net")

    assert result.success is False
    assert "search api" in result.error.lower()


@pytest.mark.asyncio
async def test_steinberg_cubase_tiers_stay_on_their_own_major():
    """An Elements 13 owner must not be told 15.0.30 is their update.

    Cubase tiers share numbering within a major but do not move between majors,
    so a per-major device only reads announcements from its own train.
    """
    from src.scrapers.plugins.steinberg import SteinbergScraper

    scraper = SteinbergScraper()
    scraper._categories = {1: "Cubase"}
    scraper._searches["Cubase maintenance update"] = [
        {"title": "Cubase 15.0.30 Maintenance Update", "category_id": 1,
         "created_at": "2026-06-03T09:00:00.000Z", "id": 1, "slug": "c15"},
        {"title": "Cubase 13.0.50 maintenance update", "category_id": 1,
         "created_at": "2024-09-10T09:00:00.000Z", "id": 2, "slug": "c13-50"},
        {"title": "Cubase 13.0.40 Maintenance Update", "category_id": 1,
         "created_at": "2024-05-14T09:00:00.000Z", "id": 3, "slug": "c13-40"},
        {"title": "Cubase 12.0.70 maintenance update", "category_id": 1,
         "created_at": "2023-02-08T09:00:00.000Z", "id": 4, "slug": "c12-70"},
    ]

    thirteen = await scraper.fetch_firmware_versions("Cubase 13", "https://www.steinberg.net")
    assert [fw.version for fw in thirteen.firmware_versions] == ["13.0.50", "13.0.40"]

    # The unversioned entry tracks the current line and still sees everything.
    every = await scraper.fetch_firmware_versions("Cubase", "https://www.steinberg.net")
    assert every.firmware_versions[0].version == "15.0.30"
