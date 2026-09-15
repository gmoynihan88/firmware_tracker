import pytest

SHARE = "https://downloads.waldorfmusic.com/cloud/index.php/s"


def _button(label, token):
    return (
        '<div><a class="fusion-button fusion-button-default fusion-button-span-yes fusion-button-default-type" '
        f'href="{SHARE}/{token}"><i class="fa-arrow-alt-circle-down fas awb-button__icon"></i>'
        f'<span class="fusion-button-text awb-button__text awb-button__text--default">{label}</span></a></div>'
    )


def _column(heading, buttons):
    return (
        '<div class="fusion-layout-column fusion_builder_column fusion_builder_column_1_3 1_3">'
        '<div class="fusion-column-wrapper fusion-column-has-shadow fusion-content-layout-column">'
        f'<div class="fusion-title title fusion-sep-none"><h2 class="fusion-title-heading title-heading-center">{heading}</h2></div>'
        f'{"".join(buttons)}</div></div>'
    )


def _faq(title, columns):
    return (
        f'<html><head><title>{title}</title></head><body>'
        '<div class="fusion-fullwidth fullwidth-box"><div class="fusion-builder-row fusion-row">'
        f'{"".join(columns)}</div></div></body></html>'
    )


def _index_entry(slug, label):
    # As served: an image link and a button link to the same page.
    return (
        f'<span class="fusion-imageframe imageframe-none"><a class="fusion-no-lightbox" href="/faq-{slug}/"><img class="lazyload img-responsive"/></a></span>'
        f'<div style="text-align:center;"><a class="fusion-button fusion-button-default" href="/faq-{slug}/">'
        f'<span class="fusion-button-text">go to {label} FAQ / Downloads</span></a></div>'
    )


INDEX = (
    '<html><body><a href="/produkt-faq/">FAQ</a>'
    + _index_entry("quantum", "Quantum") + _index_entry("stvc", "STVC") + _index_entry("kyra", "Kyra")
    + "</body></html>"
)

PAGES = {
    "https://waldorfmusic.com/produkt-faq/": INDEX,
    "https://waldorfmusic.com/faq-quantum/": _faq("FAQ Quantum EN – Waldorf Music", [
        _column("Manuals", [_button("manual", "JTmm"), _button("manual OS 2.0", "jAWq"), _button("QuickStart", "4BXo")]),
    ]),
    "https://waldorfmusic.com/faq-stvc/": _faq("FAQ STVC EN – Waldorf Music", [
        _column("Manuals", [_button("manual", "stvcm")]),
        _column("Firmware", [_button("version 1.30", "RaWkE4ZgZApD8RP"), _button("version 1.27", "j2CdrRWz2tH2os3")]),
    ]),
    "https://waldorfmusic.com/faq-kyra/": _faq("FAQ Kyra EN – Waldorf Music", [
        _column("Manuals", [_button("manual", "GXYN")]),
        _column("Firmware", [_button("version 1.7.8", "N9g8o8tojBTe6P8"),
                             _button("Firmware manager win", "bE2Z"), _button("Firmware manager Mac", "DFM8")]),
        _column("Other Downloads", [_button("Factory Sounds", "fs"), _button("Windows driver", "wd")]),
    ]),
}


def _scraper(pages=PAGES):
    from src.scrapers.plugins.waldorf import WaldorfScraper

    scraper = WaldorfScraper()
    fetched = []

    async def _page(url, *_args, **_kwargs):
        fetched.append(url)
        return pages.get(url)

    scraper.fetch_page = _page
    return scraper, fetched


def test_waldorf_reads_a_version_only_from_a_version_button():
    """The firmware manager apps share the Firmware column; a manual names an OS."""
    from src.scrapers.plugins.waldorf import WaldorfScraper

    scraper = WaldorfScraper()

    assert scraper._version("version 1.7.8") == "1.7.8"
    assert scraper._version("Firmware manager win") is None
    assert scraper._version("manual OS 2.0") is None


def test_waldorf_orders_versions_numerically():
    """1.10 is newer than 1.9, which comparing the text reverses."""
    from src.scrapers.plugins.waldorf import WaldorfScraper

    page = _faq("FAQ STVC EN – Waldorf Music", [
        _column("Firmware", [_button("version 1.9", "old"), _button("version 1.10", "new")]),
    ])

    name, releases = WaldorfScraper()._parse_faq(page)

    assert name == "STVC"
    assert [fw.version for fw in releases] == ["1.10", "1.9"]


@pytest.mark.asyncio
async def test_waldorf_lists_only_products_with_a_firmware_version():
    scraper, _ = _scraper()

    listing = await scraper.fetch_device_list()

    assert listing.success is True
    assert [(d.name, d.firmware_page_url) for d in listing.devices] == [
        ("STVC", "https://waldorfmusic.com/faq-stvc/"),
        ("Kyra", "https://waldorfmusic.com/faq-kyra/"),
    ]
    assert all(d.category == "synthesizer" for d in listing.devices)
    stvc = (await scraper.fetch_firmware_versions("STVC", "")).firmware_versions
    assert [(fw.version, fw.download_url, fw.release_date) for fw in stvc] == [
        ("1.30", f"{SHARE}/RaWkE4ZgZApD8RP", None),
        ("1.27", f"{SHARE}/j2CdrRWz2tH2os3", None),
    ]
    kyra = (await scraper.fetch_firmware_versions("Kyra", "")).firmware_versions
    assert [fw.version for fw in kyra] == ["1.7.8"]


@pytest.mark.asyncio
async def test_waldorf_reads_each_page_once():
    scraper, fetched = _scraper()

    listing = await scraper.fetch_device_list()
    for device in listing.devices:
        await scraper.fetch_firmware_versions(device.name, device.firmware_page_url)

    assert sorted(fetched) == sorted(PAGES)


@pytest.mark.asyncio
async def test_waldorf_fails_loudly():
    assert (await _scraper({})[0].fetch_device_list()).success is False

    no_links = {"https://waldorfmusic.com/produkt-faq/": "<html><body>Maintenance</body></html>"}
    assert (await _scraper(no_links)[0].fetch_device_list()).success is False

    missing = dict(PAGES)
    del missing["https://waldorfmusic.com/faq-quantum/"]
    assert (await _scraper(missing)[0].fetch_device_list()).success is False

    unnamed = dict(PAGES)
    unnamed["https://waldorfmusic.com/faq-stvc/"] = PAGES["https://waldorfmusic.com/faq-stvc/"].replace(
        "FAQ STVC EN – Waldorf Music", "Waldorf Music")
    assert (await _scraper(unnamed)[0].fetch_device_list()).success is False

    # Quantum's page carries manuals only.
    scraper, _ = _scraper()
    assert (await scraper.fetch_firmware_versions("Quantum", "")).success is False
