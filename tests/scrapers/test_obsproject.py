import json

import pytest

from tests.support import _stub_fetch


def _obs_release(tag, published, prerelease=False, draft=False, body="Notes"):
    return {"tag_name": tag, "name": f"OBS Studio {tag}", "published_at": published,
            "prerelease": prerelease, "draft": draft, "body": body,
            "html_url": f"https://github.com/obsproject/obs-studio/releases/tag/{tag}"}


def test_obs_reads_only_stable_releases():
    """Pre-releases are flagged, and a tag that is not a plain version is refused even when it is not."""
    import json
    from src.scrapers.plugins.obsproject import OBSProjectScraper

    versions = OBSProjectScraper()._parse_releases(json.dumps([
        _obs_release("32.2.2", "2026-08-14T17:02:11Z", body="Fixed NVENC on driver 570"),
        _obs_release("32.2.0-rc1", "2026-07-10T12:00:00Z", prerelease=True),
        _obs_release("32.1.0-beta2", "2026-03-01T12:00:00Z", prerelease=True),
        _obs_release("32.3.0", "2026-09-01T12:00:00Z", draft=True),
        _obs_release("31.0.0-rc2", "2025-11-01T12:00:00Z", prerelease=False),
        _obs_release("0.4.2", "2014-07-17T08:00:00Z"),
    ]))

    assert [(fw.version, fw.release_date.date().isoformat()) for fw in versions] == [
        ("32.2.2", "2026-08-14"), ("0.4.2", "2014-07-17"),
    ]
    assert versions[0].changelog == "Fixed NVENC on driver 570"
    assert versions[0].download_url.endswith("/tag/32.2.2")


@pytest.mark.asyncio
async def test_obs_follows_pages_until_a_short_one():
    import json
    from src.scrapers.plugins.obsproject import OBSProjectScraper as OBS

    scraper = OBS()
    scraper.PER_PAGE = 2
    pages = {
        scraper._page_url(1): json.dumps([_obs_release("32.2.2", "2026-08-14T00:00:00Z"), _obs_release("32.2.1", "2026-07-24T00:00:00Z")]),
        scraper._page_url(2): json.dumps([_obs_release("32.2.0", "2026-07-21T00:00:00Z"), _obs_release("32.1.2", "2026-04-21T00:00:00Z")]),
        scraper._page_url(3): json.dumps([_obs_release("0.4.0", "2014-07-14T00:00:00Z")]),
    }
    asked = _stub_fetch(scraper, pages)

    result = await scraper.fetch_firmware_versions("OBS Studio", scraper.PRODUCT_URL)

    assert asked == [scraper._page_url(1), scraper._page_url(2), scraper._page_url(3)]
    assert [fw.version for fw in result.firmware_versions] == ["32.2.2", "32.2.1", "32.2.0", "32.1.2", "0.4.0"]


@pytest.mark.asyncio
async def test_obs_fails_loudly_when_a_page_does_not_load():
    """A rate-limited later page would otherwise pass for a shorter history."""
    import json
    from src.scrapers.plugins.obsproject import OBSProjectScraper as OBS

    scraper = OBS()
    scraper.PER_PAGE = 2
    _stub_fetch(scraper, {
        scraper._page_url(1): json.dumps([_obs_release("32.2.2", "2026-08-14T00:00:00Z"), _obs_release("32.2.1", "2026-07-24T00:00:00Z")]),
    })

    assert (await scraper.fetch_device_list()).success is False


@pytest.mark.asyncio
async def test_obs_is_one_device():
    import json
    from src.scrapers.plugins.obsproject import OBSProjectScraper as OBS

    scraper = OBS()
    _stub_fetch(scraper, {scraper._page_url(1): json.dumps([_obs_release("32.2.2", "2026-08-14T00:00:00Z")])})

    devices = (await scraper.fetch_device_list()).devices

    assert [(d.name, d.category) for d in devices] == [("OBS Studio", "vst_plugin")]
