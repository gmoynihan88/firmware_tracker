import json

import pytest

from tests.support import _stub_fetch


CG_BUILD = "ccf31331-e8aa-44f2-93ca-f56d6307b248"


def _cg_page(build=CG_BUILD):
    """The products page: nav links, and the build id the payload is keyed on."""
    meta = f'<link rel="modulepreload" href="/_nuxt/builds/meta/{build}.json">' if build else ""
    return (f"<html><head>{meta}</head><body>"
            '<a href="/shaperbox">ShaperBox</a><a href="/curve">Curve</a><a href="/products">All</a>'
            "</body></html>")


def _cg_payload(*products):
    """A devalue payload: one flat array, every object's values indices into it.

    Each product's price lands before its version in the array, so reading the
    next version-shaped string after a name picks up the price.
    """
    data = [{"data": 1}, []]
    for name, price, version, for_sale in products:
        at = len(data)
        data[1].append(at)
        data += [{"name": at + 1, "price": at + 2, "version": at + 3, "for_sale": at + 4},
                 name, price, version, for_sale]
    return json.dumps(data)


CG_PAYLOAD = _cg_payload(
    ("ShaperBox 3", "89.00", "3.6.3", True),
    ("Curve 2", "29.00", "2.6.3", True),
    ("Curve 2 BE", "0.00", "2.6.2", False),
    ("Curve CM", "0.00", "1.4.5", False),
    ("VolumeShaper Sound Sonic Edition", "0.00", "2.2.4", False),
    ("VolumeShaper 3", "19.00", "3.2.2", False),
)


def test_cableguys_reads_each_products_own_version_not_its_price():
    from src.scrapers.plugins.cableguys import CableguysScraper

    products = CableguysScraper()._parse_payload(CG_PAYLOAD)

    assert products["ShaperBox 3"] == "3.6.3"
    assert products["VolumeShaper 3"] == "3.2.2"  # discontinued, still listed


def test_cableguys_skips_magazine_and_bundle_editions():
    """Curve 2 BE is a release behind Curve 2; it is a variant, not a product."""
    from src.scrapers.plugins.cableguys import CableguysScraper

    assert sorted(CableguysScraper()._parse_payload(CG_PAYLOAD)) == ["Curve 2", "ShaperBox 3", "VolumeShaper 3"]


@pytest.mark.asyncio
async def test_cableguys_fetches_the_payload_for_this_deploys_build():
    from src.scrapers.plugins.cableguys import CableguysScraper as CG

    scraper = CG()
    payload_url = f"{CG.PRODUCTS_URL}/_payload.json?{CG_BUILD}"
    asked = _stub_fetch(scraper, {CG.PRODUCTS_URL: _cg_page(), payload_url: CG_PAYLOAD})

    devices = (await scraper.fetch_device_list()).devices
    result = await scraper.fetch_firmware_versions("Curve 2", CG.PRODUCTS_URL)

    assert asked == [CG.PRODUCTS_URL, payload_url]
    assert {d.name: d.product_url for d in devices} == {
        "Curve 2": "https://www.cableguys.com/curve",
        "ShaperBox 3": "https://www.cableguys.com/shaperbox",
        "VolumeShaper 3": CG.PRODUCTS_URL,  # no page of its own in the nav
    }
    assert [fw.version for fw in result.firmware_versions] == ["2.6.3"]


@pytest.mark.asyncio
async def test_cableguys_fails_loudly_without_a_build_id():
    from src.scrapers.plugins.cableguys import CableguysScraper as CG

    scraper = CG()
    _stub_fetch(scraper, {CG.PRODUCTS_URL: _cg_page(build=None)})

    assert (await scraper.fetch_device_list()).success is False
