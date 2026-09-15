import pytest

from tests.support import _stub_fetch


def _pioneer_card(date, title, href):
    return (f'<a class="style-module__card" data-gid="prd_detail_related_news" href="{href}">'
            f'<div class="style-module__imageWrapper"><img alt=""/></div>'
            f'<div><p class="style-module__subTitle">{date}</p><p class="style-module__title">{title}</p></div></a>')


def _pioneer_product(*cards):
    return ('<html><body><header><div><p class="hamburger_title">Products</p>'
            '<p class="support_title">Keep your product up to date</p></div></header>'
            "<main>" + "".join(cards) + "</main></body></html>")


PIONEER_PLAYERS = (
    '<html><body><a href="/en/product/dj-players-turntables/">Players</a>'
    '<a href="/en/product/dj-players-turntables/cdj-3000-w/">CDJ-3000-W</a>'
    '<a href="/en/product/dj-players-turntables/cdj-3000/">CDJ-3000</a>'
    '<a href="https://www.pioneerdj.com/en/product/dj-players-turntables/cdj-3000/?color=black">CDJ-3000 again</a>'
    '<a href="/en/product/dj-mixers/djm-a9/">A mixer, listed on its own page</a></body></html>'
)


PIONEER_CDJ_3000 = _pioneer_product(
    _pioneer_card("18 March, 2026", "Update: DJM-A9 Firmware Ver. 1.11", "/en/news/2026/djm-a9-firmware-update-111/"),
    _pioneer_card("24 April, 2025", "Update: CDJ-3000 Firmware Ver. 3.20", "/en/news/2025/cdj-3000-firmware-update-320/"),
    _pioneer_card("3 December, 2024", "Important Notice Regarding CDJ-3000: Request for Updating the Firmware",
                  "/en/news/2024/important-notice-cdj-3000/"),
    _pioneer_card("25 July, 2024", "Updates: CDJ-3000 and OPUS-QUAD firmware",
                  "/en/news/2024/cdj-3000-and-opus-quad-firmware-update/"),
    _pioneer_card("5 May, 2024", "CDJ-3000 driver update (Ver.1.1.1)", "/en/news/2024/cdj-3000-driver-update/"),
    _pioneer_card("31 May, 2023", "CDJ-3000 Ver.3.12 firmware update postponed", "/en/news/2023/cdj-3000-update-postponed/"),
)


PIONEER_CDJ_3000_ARTICLE = (
    "<html><body><main><h1>Updates: CDJ-3000 and OPUS-QUAD firmware</h1>"
    '<p>CDJ-3000 Firmware ver. 3.14 <a href="#">Download page</a></p>'
    '<p>OPUS-QUAD Firmware ver. 1.20 <a href="#">Download page</a></p></main></body></html>'
)


def test_pioneer_lists_each_product_page_once_from_its_category_page():
    from src.scrapers.plugins.pioneerdj import PioneerDJScraper as P

    urls = P()._parse_listing(PIONEER_PLAYERS, "dj-players-turntables")

    assert urls == [
        "https://www.pioneerdj.com/en/product/dj-players-turntables/cdj-3000-w/",
        "https://www.pioneerdj.com/en/product/dj-players-turntables/cdj-3000/",
    ]


def test_pioneer_names_the_model_a_post_names_not_the_colour_variant_page():
    from src.scrapers.plugins.pioneerdj import PioneerDJScraper

    scraper = PioneerDJScraper()

    assert scraper._model_in("cdj-3000-w", "Update: CDJ-3000 Firmware Ver. 3.20").group(0) == "CDJ-3000"
    assert scraper._model_in("xdj-xz-n", "Update: XDJ-XZ firmware ver. 1.22").group(0) == "XDJ-XZ"
    assert scraper._model_in("toraiz-sp-16", "TORAIZ SP-16 Firmware update (Ver.1.40)").group(0) == "TORAIZ SP-16"
    # A model inside a longer one is not that model.
    assert scraper._model_in("ddj-flx6", "Update: DDJ-FLX6-GT firmware ver. 1.01") is None
    assert scraper._model_in("cdj-2000nxs", "Update: CDJ-2000NXS2 firmware ver. 1.84") is None


def test_pioneer_reads_a_version_from_every_title_wording():
    from src.scrapers.plugins.pioneerdj import PioneerDJScraper

    scraper = PioneerDJScraper()

    def version(slug, title):
        return scraper._title_version(title, scraper._model_in(slug, title))

    assert version("cdj-3000", "Update: CDJ-3000 Firmware Ver. 3.20") == "3.20"
    assert version("toraiz-sp-16", "TORAIZ SP-16 firmware update (ver 1.50) introduces live sampling") == "1.50"
    assert version("cdj-3000", "Major CDJ-3000 firmware update – ver. 2.0 – introduces rekordbox CloudDirectPlay") == "2.0"
    assert version("xdj-rx2", "XDJ-RX2 Firmware update (Ver.1.32) / Driver for Windows update (Ver.1.020)") == "1.32"
    # Several models and several versions pair in order; several models and one version share it.
    assert version("djm-900nxs2", "CDJ-2000NXS2 / DJM-900NXS2 Firmware update (Ver.1.40 / Ver.1.30)") == "1.30"
    assert version("djm-v10", "Update: DJM-V10/DJM-V10-LF Firmware Ver. 1.16") == "1.16"
    assert version("xdj-rx2", "Update: XDJ-RX2 firmware") is None


def test_pioneer_reads_a_versionless_posts_version_from_the_post():
    from src.scrapers.plugins.pioneerdj import PioneerDJScraper

    scraper = PioneerDJScraper()

    assert scraper._article_version(PIONEER_CDJ_3000_ARTICLE, "CDJ-3000") == "3.14"
    assert scraper._article_version(PIONEER_CDJ_3000_ARTICLE, "OPUS-QUAD") == "1.20"
    assert scraper._article_version(PIONEER_CDJ_3000_ARTICLE, "XDJ-RR") is None


@pytest.mark.asyncio
async def test_pioneer_keeps_firmware_releases_for_the_model_and_opens_versionless_posts_once():
    """Notices, postponements, drivers and another product's posts are not the CDJ-3000's firmware."""
    from src.scrapers.plugins.pioneerdj import PioneerDJScraper as P

    scraper = P()
    base = "https://www.pioneerdj.com"
    asked = _stub_fetch(scraper, {
        P.CATEGORY_URL.format(category="dj-players-turntables"): PIONEER_PLAYERS,
        base + "/en/product/dj-players-turntables/cdj-3000-w/": PIONEER_CDJ_3000,
        base + "/en/product/dj-players-turntables/cdj-3000/": PIONEER_CDJ_3000,
        base + "/en/news/2024/cdj-3000-and-opus-quad-firmware-update/": PIONEER_CDJ_3000_ARTICLE,
    })

    devices = (await scraper.fetch_device_list()).devices
    result = await scraper.fetch_firmware_versions("CDJ-3000", devices[0].firmware_page_url)

    assert [(d.name, d.category, d.firmware_page_url) for d in devices] == [
        ("CDJ-3000", "other", base + "/en/product/dj-players-turntables/cdj-3000/"),
    ]
    assert [(fw.version, fw.release_date.date().isoformat()) for fw in result.firmware_versions] == [
        ("3.20", "2025-04-24"), ("3.14", "2024-07-25"),
    ]
    assert result.firmware_versions[1].download_url == base + "/en/news/2024/cdj-3000-and-opus-quad-firmware-update/"
    assert asked.count(base + "/en/news/2024/cdj-3000-and-opus-quad-firmware-update/") == 1
    assert not [url for url in asked if "/en/news/" in url and "opus-quad" not in url]


@pytest.mark.asyncio
async def test_pioneer_fails_loudly_without_firmware_posts():
    from src.scrapers.plugins.pioneerdj import PioneerDJScraper as P

    scraper = P()
    _stub_fetch(scraper, {})

    assert (await scraper.fetch_device_list()).success is False
