from datetime import datetime

import pytest

from tests.support import _stub_fetch

CDN = "https://cdn.shopify.com/s/files/1/0757/8429/0571/files"


def _block(title, *parts):
    return (
        '<section class="shopify-section section"><div class="rich-text content-container color-scheme-1 gradient">'
        '<div class="rich-text__wrapper rich-text__wrapper--center page-width"><div class="rich-text__blocks center">'
        f'<h2 class="rich-text__heading rte inline-richtext h1 scroll-trigger animate--slide-in" data-cascade> {title} </h2>'
        + "".join(parts) + "</div></div></div></section>"
    )


def _text(html):
    return f'<div class="rich-text__text rte scroll-trigger animate--slide-in" data-cascade> {html} </div>'


def _download(label, date, filename):
    return (
        _text(f"<p>{label}</p>")
        + f'<p class="rich-text__caption caption-with-letter-spacing caption-with-letter-spacing--medium"> {date} </p>'
        + f'<div class="rich-text__buttons"><a href="{CDN}/{filename}?v=1724665865" class="button button--primary">Download</a></div>'
    )


PAGE = (
    "<html><body><main class=\"content-for-layout focus-none\">"
    + _block("Cirklon Firmware",
             _text("<p><strong>Please ensure you download the correct file for your unit - Cirklon and Cirklon 2 "
                   "DO NOT USE THE SAME FIRMWARE IMAGES</strong></p>"),
             _text("<p>Current <strong>Cirklon 2</strong> Release OS v1.22d<br/>11/12/2024</p>"),
             f'<div class="rich-text__buttons"><a href="{CDN}/ck2-v1.22d.zip?v=1" class="button">DOWNLOAD CIRKLON2 FIRMWARE</a></div>',
             _text("<p>Current <strong>Cirklon</strong> Release OS v1.22e <br/>24/2/2025</p>"),
             f'<div class="rich-text__buttons"><a href="{CDN}/ck1-v1.22e.zip?v=1" class="button">DOWNLOAD CIRKLON FIRMWARE</a></div>')
    + _block("Cirklon Sequencer Operation Manual v1.22", _text("<p>The manual for OS v1.22</p>"))
    + _block("P3 Firmware - Version 4 BETA",
             _download("P3 OS v4.5 beta 3 <strong>SYX format</strong>", "30/03/2011", "p3v4.5b3.syx"),
             _download("P3 OS v4.5 beta Usage Notes", "18/12/2011", "p3v4.5b-use.txt"))
    + _block("Beta", _download("P3 OS v3.1.007 beta 13 <strong>MID format</strong>", "2/12/2007", "p3v3.1.7b13.mid"))
    + _block("Release Version",
             _download("P3 OS v3.1.006 rev C <strong>SYX format</strong>", "26/05/2006", "p3fw-3.1.006revC.syx"),
             _download("P3 OS v3.1.006 rev C <strong>MID format</strong>", "26/05/2006", "p3fw-3.1.006revC.mid"),
             _download("P3 OS v3.1.006 rev B Release Notes", "26/05/2006", "p3fw-revision.txt"))
    + "</main></body></html>"
)


def test_sequentix_reads_each_cirklon_as_its_own_product_with_its_letter():
    from src.scrapers.plugins.sequentix import SequentixScraper

    devices = SequentixScraper()._parse(PAGE)

    assert [(r.version, r.release_date) for r in devices["Cirklon 2"]] == [("1.22d", datetime(2024, 12, 11))]
    assert [(r.version, r.release_date) for r in devices["Cirklon"]] == [("1.22e", datetime(2025, 2, 24))]


def test_sequentix_reads_dates_day_first():
    from src.scrapers.plugins.sequentix import SequentixScraper

    scraper = SequentixScraper()

    assert scraper._parse_date("11/12/2024") == datetime(2024, 12, 11)
    assert scraper._parse_date("24/2/2025") == datetime(2025, 2, 24)
    assert scraper._parse_date("2/31/2025") is None


def test_sequentix_takes_only_released_p3_firmware_files():
    from src.scrapers.plugins.sequentix import SequentixScraper

    devices = SequentixScraper()._parse(PAGE)

    assert [(r.version, r.release_date) for r in devices["P3"]] == [("3.1.006C", datetime(2006, 5, 26))]


@pytest.mark.asyncio
async def test_sequentix_lists_three_products_from_one_page():
    from src.scrapers.plugins.sequentix import SequentixScraper as S

    scraper = S()
    asked = _stub_fetch(scraper, {S.DOWNLOADS_URL: PAGE})

    devices = [(d.name, d.category) for d in (await scraper.fetch_device_list()).devices]
    p3 = await scraper.fetch_firmware_versions("P3", S.DOWNLOADS_URL)

    assert devices == [("Cirklon 2", "midi_controller"), ("Cirklon", "midi_controller"), ("P3", "midi_controller")]
    assert [r.version for r in p3.firmware_versions] == ["3.1.006C"]
    assert len(asked) == 1


@pytest.mark.asyncio
async def test_sequentix_fails_loudly_without_the_page():
    from src.scrapers.plugins.sequentix import SequentixScraper as S

    scraper = S()
    _stub_fetch(scraper, {})

    assert (await scraper.fetch_device_list()).success is False
