import pytest

from tests.support import _stub_fetch


def _uhe_notes(title, *entries):
    """A legacy releasenotes.html: one div per release, the date before the heading."""
    body = "".join(
        f'<div class="releasenote" id="{rev}"><div class="rn-date w-6c"> {date} </div>'
        f'<div class="rn-info"><h3 class="head1">{heading}</h3><p>Notes</p></div></div>'
        for heading, rev, date in entries
    )
    return f"<h2>Release notes: {title}</h2><p>beta versions and latest builds not included</p>{body}"


def _uhe_releases(*entries):
    """A new-section releases/ page: a version heading, then published and revision."""
    return "".join(
        f'<h2><span class="anchor">anchor</span> {version}</h2>'
        + (f"<p>{preface}</p>" if preface else "")
        + f"<dl><dt>published</dt><dd>{date}</dd><dt>revision</dt><dd>{revision}</dd></dl>"
          "<h3>Fixed bugs</h3><ul><li>fix</li></ul>"
        for version, date, revision, preface in entries
    )


def _uhe_stub(target):
    return (f"<!doctype html><html><head><title>{target}</title>"
            f"<link rel=canonical href={target}>"
            f'<meta http-equiv=refresh content="0; url={target}"></head></html>')


def test_uhe_pairs_each_version_with_the_date_in_its_own_note():
    """The date comes before the heading, so reading onward from a heading finds none."""
    from src.scrapers.plugins.uhe import UHeScraper

    title, versions = UHeScraper()._parse_notes(_uhe_notes(
        "Triple Cheese",
        ("Triple Cheese 1.3 (revision 12092)", "12092", "August 10, 2021"),
        ("Triple Cheese 1.2.1 (revision 9000)", "9000", "March 04, 2019"),
    ))

    assert title == "Triple Cheese"
    assert [(fw.version, fw.release_date.date().isoformat()) for fw in versions] == [
        ("1.3", "2021-08-10"),
        ("1.2.1", "2019-03-04"),
    ]


def test_uhe_reads_the_new_releases_pages():
    from src.scrapers.plugins.uhe import UHeScraper

    versions = UHeScraper()._parse_releases(_uhe_releases(
        ("3.0.2", "Wednesday, July 15, 2026", "22175", None),
        ("3.0.0", "Monday, April 20, 2026", "21799", "Initial release"),
    ))

    assert [(fw.version, fw.release_date.date().isoformat()) for fw in versions] == [
        ("3.0.2", "2026-07-15"),
        ("3.0.0", "2026-04-20"),
    ]


def test_uhe_matches_installers_however_they_are_named():
    from src.scrapers.plugins.uhe import UHeScraper

    scraper = UHeScraper()
    index = scraper.parse_html("".join(
        f'<a href="https://dl.u-he.com/releases/{f}">macOS</a>' for f in (
            "Zebra_Legacy_294_16765_Mac.zip",
            "TyrellN6_300_public_beta_16976_Mac.zip",
            "Zebralette3_300_20399__Win.zip",
            "zebralette3_300_20399_Linux.tar.xz",
            "TripleCheese_13_12092_Mac.zip",
            "Twangstrom_102_16742_Mac.zip",
        )
    ))

    found = scraper._installer_versions(index)

    assert found == {
        "zebralegacy": {"2.9.4"},
        "tyrelln6": {"3.0.0"},
        "zebralette3": {"3.0.0"},
        "triplecheese": {"1.3"},
        "twangstrom": {"1.0.2"},
    }
    assert scraper._key("Twangström") == "twangstrom"


@pytest.mark.asyncio
async def test_uhe_follows_redirects_and_adds_installers_newer_than_the_notes():
    """One catalogue run over every kind of link the index has."""
    from src.scrapers.plugins.uhe import UHeScraper as U

    base = "https://u-he.com/products/"
    plug = "https://u-he.com/products/plug-ins/zebra3/"
    index = (
        '<a href="/products/hive/">Hive</a>'
        '<a href="/products/zebra3/">Zebra 3</a><a href="/products/synths/zebra3">Zebra 3</a>'
        '<a href="/products/wiretap/">Wiretap</a><a href="/products/tyrelln6/">TyrellN6</a>'
        '<a href="/products/soundsets/">Soundsets</a><a href="/products/bundles/all-effects.html">All</a>'
        '<a href="https://dl.u-he.com/releases/Hive_213_16600_Mac.zip">macOS</a>'
        '<a href="https://dl.u-he.com/releases/Zebra3_302_22175_Mac.zip">macOS</a>'
    )
    pages = {
        U.INDEX_URL: index,
        base + "hive/releasenotes.html": _uhe_notes("Hive 2", ("Hive 2.1.2 (revision 16520)", "16520", "August 27, 2024")),
        base + "zebra3/releasenotes.html": _uhe_stub(plug),
        base + "zebra3/": _uhe_stub(plug),
        base + "synths/zebra3/": _uhe_stub(plug),
        plug: "<html><head><title>Zebra 3 | u-he</title></head><body></body></html>",
        plug + "releases/": _uhe_releases(("3.0.2", "Wednesday, July 15, 2026", "22175", None)),
        base + "wiretap/releasenotes.html": _uhe_notes("Wiretap"),
        base + "wiretap/": "<html><head><title>Wiretap: Every melody deserves a rhythm! | u-he</title></head></html>",
        base + "tyrelln6/releasenotes.html": _uhe_notes("TyrellN6 Beta", ("TyrellN6 3.0.0 (revision 16976)", "16976", "March 18, 2025")),
    }
    scraper = U()
    asked = _stub_fetch(scraper, pages)

    devices = (await scraper.fetch_device_list()).devices
    listed = {d.name: (d.category, d.firmware_availability, d.firmware_page_url) for d in devices}
    versions = {}
    for d in devices:
        result = await scraper.fetch_firmware_versions(d.name, d.firmware_page_url)
        versions[d.name] = [(fw.version, fw.release_date.date().isoformat() if fw.release_date else None)
                            for fw in result.firmware_versions]

    assert listed == {
        "Hive 2": ("vst_plugin", None, base + "hive/"),
        "Zebra 3": ("vst_plugin", None, plug),                   # two stubs, one product
        "Wiretap": ("synthesizer", "not_published", base + "wiretap/"),
        "TyrellN6": ("vst_plugin", None, base + "tyrelln6/"),    # "Beta" is not the name
    }
    assert versions["Hive 2"] == [("2.1.3", None), ("2.1.2", "2024-08-27")]  # installer ahead of notes
    assert versions["Zebra 3"] == [("3.0.2", "2026-07-15")]
    assert versions["Wiretap"] == []
    assert len(asked) == len(set(asked)), "a page was fetched twice"


@pytest.mark.asyncio
async def test_uhe_fails_loudly_without_the_product_index():
    from src.scrapers.plugins.uhe import UHeScraper as U

    scraper = U()
    _stub_fetch(scraper, {})

    assert (await scraper.fetch_device_list()).success is False
