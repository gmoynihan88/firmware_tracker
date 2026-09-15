import pytest

from tests.support import _stub_fetch


def _serato_page(product, heading, *sections):
    body = "".join(f"<h3>{title}</h3><p>{text}</p>" for title, text in sections)
    return (
        '<html><body><section class="spacing-default"><div class="col-span-12">'
        f'<h1 class="mb-0 mt-0 text-center">Download {product}</h1><h4>Get the latest version</h4></div>'
        '<div class="col-span-12 grid"><article class="col-span-12"><div class="pb-10"><!--[-->'
        f"<h2>{heading}</h2>{body}<h2>System Requirements</h2><p>macOS 26, macOS 15</p>"
        "</div></article></div></section></body></html>"
    )


DJ_PRO = _serato_page("Serato DJ Pro", "What’s New in 4.0.9",
                      ("AlphaTheta XDJ-AN Support", "All-in-one DJ performance."),
                      ("Bug Fixes", "Fixed a crash on Windows."))
STUDIO = _serato_page("Serato Studio", "What’s New in Studio 2.5.0", ("Stems", "Separate vocals."))
NO_RELEASE = _serato_page("Serato Hex FX", "Features")

HOME = (
    '<html><body><nav><a href="/dj/pro">DJ Pro</a><a href="/dj/pro/downloads">Download</a>'
    '<a href="https://serato.com/studio/downloads">Download</a><a href="/hex-fx/downloads">Download</a>'
    '<a href="/dj/pro/downloads#system">again</a><a href="/legacy-products">Legacy Software</a>'
    '<a href="https://support.serato.com/hc/en-us">Support</a></nav></body></html>'
)


def test_serato_reads_the_current_version_from_either_heading_shape():
    from src.scrapers.plugins.serato import SeratoScraper

    scraper = SeratoScraper()
    dj_pro, studio = scraper._parse_page(DJ_PRO), scraper._parse_page(STUDIO)

    assert (dj_pro[0], dj_pro[1].version, dj_pro[1].release_date) == ("Serato DJ Pro", "4.0.9", None)
    assert (studio[0], studio[1].version) == ("Serato Studio", "2.5.0")


def test_serato_notes_stop_at_the_next_section():
    from src.scrapers.plugins.serato import SeratoScraper

    _name, firmware = SeratoScraper()._parse_page(DJ_PRO)

    assert firmware.changelog.splitlines() == [
        "AlphaTheta XDJ-AN Support", "All-in-one DJ performance.", "Bug Fixes", "Fixed a crash on Windows.",
    ]


def test_serato_discovers_downloads_pages_from_the_home_page():
    from src.scrapers.plugins.serato import SeratoScraper as S

    assert S()._parse_home(HOME) == [
        S.BASE_URL + "/dj/pro/downloads", S.BASE_URL + "/studio/downloads", S.BASE_URL + "/hex-fx/downloads",
    ]


@pytest.mark.asyncio
async def test_serato_lists_products_that_name_a_current_version():
    from src.scrapers.plugins.serato import SeratoScraper as S

    scraper = S()
    asked = _stub_fetch(scraper, {
        S.BASE_URL + "/": HOME,
        S.BASE_URL + "/dj/pro/downloads": DJ_PRO,
        S.BASE_URL + "/studio/downloads": STUDIO,
        S.BASE_URL + "/hex-fx/downloads": NO_RELEASE,
    })

    devices = {d.name: d.category for d in (await scraper.fetch_device_list()).devices}
    dj_pro = await scraper.fetch_firmware_versions("Serato DJ Pro", S.BASE_URL + "/dj/pro/downloads")

    assert devices == {"Serato DJ Pro": "vst_plugin", "Serato Studio": "vst_plugin"}
    assert [fw.version for fw in dj_pro.firmware_versions] == ["4.0.9"]
    assert len(asked) == 4


@pytest.mark.asyncio
async def test_serato_fails_loudly_without_the_home_page():
    from src.scrapers.plugins.serato import SeratoScraper as S

    scraper = S()
    _stub_fetch(scraper, {})

    assert (await scraper.fetch_device_list()).success is False
