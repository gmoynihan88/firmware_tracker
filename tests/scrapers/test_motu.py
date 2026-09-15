import json
from datetime import datetime

import pytest

from tests.support import _stub_fetch


def _motu_row(name, platform_icon, version, date):
    return (
        f'<tr><td align="middle"><b>{name}</b><br/><span class="platform-logos"><i class="fab {platform_icon}"></i></span>'
        f'<span class="vnum nobreak">{version}</span><span class="vnum nobreak"> | {date} </span>'
        '<div class="mobile-only"><a href="/en-us/download/file/1/">DOWNLOAD</a></div></td>'
        "<td>macOS 15, macOS 14</td><td class=\"desktop-only\"></td></tr>"
    )


def _motu_section(title, *rows):
    return (f'<thead><tr><th colspan=1 align="bottom"><b> {title} </b></th><th><b>Supports</b></th></tr></thead>'
            f"<tbody>{''.join(rows)}</tbody>")


def _motu_page(*sections):
    return (
        "<html><body><p>Some downloads available only to registered users of this product. To view these, please log in.</p>"
        f'<table class="table">{"".join(sections)}</table></body></html>'
    )


DP11 = _motu_page(
    _motu_section("Installer",
                  _motu_row("Digital Performer 11", "fa-apple", "Mac v11.36+101486", "Jan. 29, 2026"),
                  _motu_row("Digital Performer 11", "fa-windows", "PC v11.36+101486", "Jan. 29, 2026")),
    _motu_section("Soundbank", _motu_row("MOTU Instruments Soundbank", "fa-apple", "Mac v2.0.1", "Feb. 2, 2026")),
)

PERFORMER_LITE_DE = _motu_page(_motu_section(
    "Installer",
    _motu_row("Performer Lite 11 DE", "fa-apple", "Mac v11.23+94286", "Oct. 24, 2023"),
    _motu_row("Performer Lite 11", "fa-apple", "Mac v11.36+101486", "Jan. 29, 2026"),
))

DP8 = _motu_page(_motu_section("Installer", _motu_row("Digital Performer 8.07", "fa-apple", "Mac v8.07", "Sept. 3, 2014")))

M_SERIES = _motu_page(
    _motu_section("Driver", _motu_row("MOTU M-Series Installer", "fa-apple", "Mac v2.0.2+b72db03fb", "March 25, 2026")),
    _motu_section("Firmware", _motu_row("MOTU M-Series Universal Firmware Updater", "fa-apple", "Mac v2026.2", "Feb. 11, 2026")),
)

MACHFIVE_3 = _motu_page(_motu_section("User Guide"))


def test_motu_reads_the_installer_version_without_its_build_and_the_rows_date():
    from src.scrapers.plugins.motu import MOTUScraper

    scraper = MOTUScraper()
    dp11, dp8 = scraper._parse_page(DP11), scraper._parse_page(DP8)

    assert (dp11.version, dp11.release_date) == ("11.36", datetime(2026, 1, 29))
    assert (dp8.version, dp8.release_date) == ("8.07", datetime(2014, 9, 3))


def test_motu_reads_only_the_installer_section():
    """A soundbank beside the application is not its version; a driver and firmware updater are not either."""
    from src.scrapers.plugins.motu import MOTUScraper

    scraper = MOTUScraper()

    assert scraper._parse_page(DP11).changelog == "Installer: Digital Performer 11"
    assert scraper._parse_page(M_SERIES) is None
    assert scraper._parse_page(MACHFIVE_3) is None


def test_motu_takes_the_newest_installer_when_a_page_keeps_an_older_one():
    """Performer Lite 11 DE's own 11.23 installer sits beside the generic 11.36 that now installs it."""
    from src.scrapers.plugins.motu import MOTUScraper

    firmware = MOTUScraper()._parse_page(PERFORMER_LITE_DE)

    assert (firmware.version, firmware.release_date) == ("11.36", datetime(2026, 1, 29))


@pytest.mark.asyncio
async def test_motu_lists_software_categories_only_and_skips_pages_without_an_installer():
    from src.scrapers.plugins.motu import MOTUScraper as M

    scraper = M()
    asked = _stub_fetch(scraper, {
        M.FILTER_URL.format(category=5): json.dumps({"products": [
            {"id": 489, "title": "Digital Performer 11"}, {"id": 407, "title": "Performer Lite 11 DE"}]}),
        M.FILTER_URL.format(category=6): json.dumps({"products": [{"id": 274, "title": "MachFive 3"}]}),
        M.PRODUCT_URL.format(id=489): DP11,
        M.PRODUCT_URL.format(id=407): PERFORMER_LITE_DE,
        M.PRODUCT_URL.format(id=274): MACHFIVE_3,
    })

    devices = {d.name: d.category for d in (await scraper.fetch_device_list()).devices}
    dp = await scraper.fetch_firmware_versions("Digital Performer 11", M.PRODUCT_URL.format(id=489))

    assert devices == {"Digital Performer 11": "vst_plugin", "Performer Lite 11 DE": "vst_plugin"}
    assert dp.firmware_versions[0].version == "11.36"
    assert not [url for url in asked if "category=1" in url]
    assert len(asked) == 5


@pytest.mark.asyncio
async def test_motu_fails_loudly_without_the_product_lists():
    from src.scrapers.plugins.motu import MOTUScraper as M

    scraper = M()
    _stub_fetch(scraper, {})

    assert (await scraper.fetch_device_list()).success is False
