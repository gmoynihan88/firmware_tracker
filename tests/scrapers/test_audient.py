import json

import pytest

from tests.support import _stub_fetch

EVO_8 = (
    '<h1 id="h_01JA8BRFAV5R5VNP8STP5MYSH4"> </h1>\n'
    '<h2 id="h_01JA8BRFAVDSE728J8681Q0KHD"><strong><span>v1.4.12</span></strong></h2>\n'
    "<ul>\n<li>Bug Fix: Low input signal after power up</li>\n</ul>\n"
    '<h2 id="h_01JA8BRFAV8E21A65N4VBP4HGC"><strong><span>v1.4.7 </span></strong></h2>\n'
    '<p class="wysiwyg-indent1"><span>·</span><span>       </span>'
    "<span>Host communication performance improvements with Evo v4.3.8+</span></p>\n"
)
ID14_MKII = (
    "<p><strong style=\"font-family: -apple-system, 'Segoe UI', sans-serif;\"><font size=\"4\">V1.1.2<br></font></strong></p>\n"
    "<p><strong>Changes:</strong></p>\n<ul>\n<li>Bug Fix: Talkback assignment affects Main Mix</li>\n</ul>\n"
    '<div>\n<div dir="auto">\n<p> </p>\n<hr>\n'
    '<h2 id="h_01J4229RC01EMMQ55DGR7R2GE4"><strong><font size="4"><br>V1.1.1</font></strong></h2>\n'
    "</div>\n</div>\n<p><strong>Changes:</strong></p>\n"
    '<div>\n<div dir="auto">\n<ul>\n'
    "<li>Fixed <span>firmware</span> update failure on some systems (Mac M1 &amp; Ryzen).</li>\n"
    "<li>\n<span>Fixed Alt trim speaker level bug<br></span><span></span>\n</li>\n</ul>\n"
)
EVO_16 = (
    "<div>\n<div>\n<strong><strong><br></strong></strong>\n<div>\n"
    "<div><strong>V1.3.0</strong></div>\n<div><strong>Changes:</strong></div>\n"
    "<ul>\n<li>Added a sleep timeout adjustment via Settings Menu</li>\n</ul>\n</div>\n"
    "<div><strong>____________________________________________________________________________________</strong></div>\n"
    "<div><strong>V1.2.9</strong></div>\n"
    "<ul>\n<li>Improves ADAT clocking with external devices where SMUX flags are not set correctly </li>\n</ul>\n"
    "</div>\n</div>\n"
    "<p><strong>____________________________________________________________________________________</strong></p>\n"
    "<p><strong>V1.1.0 -</strong> Initial factory firmware release.</p>\n"
)
ID14_MKI = (
    '<p class="p1"><strong>Release Notes - iD14 - Version v1.1.1</strong></p>\n'
    "<ul>\n<li>Improved debounce on buttons to remove occasional erroneous button presses.</li>\n</ul>\n"
    '<p class="p1"><strong>Release Notes - iD14 - Version v1.0.8</strong></p>\n'
    "<ul>\n<li>Added support for features in upcoming GUI release\n<ul>\n"
    "<li>Dim attenuation control for monitor controller</li>\n</ul>\n</li>\n</ul>\n"
)
ID44_MKII = (
    "<p><span><br><strong><br></strong>The Changelog for iD44 MKII can be seen below.<strong><br><br>v1.0.2: </strong></span></p>\n"
    "<ul>\n<li><span>Fixed analogue output phase alignment</span></li>\n</ul>\n"
    "<p><strong>v1.0.1: </strong></p>\n<div>\n<ul>\n<li>SPDIF 1+2 output routing fix</li>\n</ul>\n</div>"
)
ID4_MKII = "<p><strong>v1.0.11</strong></p><p>-Upgrade image format updated (.img file)</p>"


def test_audient_reads_every_heading_shape():
    from src.scrapers.plugins.audient import AudientScraper

    scraper = AudientScraper()

    assert [[r.version for r in scraper._parse_article(body)] for body in (EVO_8, ID14_MKII, EVO_16, ID14_MKI, ID44_MKII)] == [
        ["1.4.12", "1.4.7"], ["1.1.2", "1.1.1"], ["1.3.0", "1.2.9", "1.1.0"], ["1.1.1", "1.0.8"], ["1.0.2", "1.0.1"],
    ]


def test_audient_notes_keep_inline_words_together_and_drop_typed_bullets_and_rules():
    from src.scrapers.plugins.audient import AudientScraper

    scraper = AudientScraper()
    id14 = scraper._parse_article(ID14_MKII)
    evo8, evo16 = scraper._parse_article(EVO_8), scraper._parse_article(EVO_16)

    assert id14[1].changelog == (
        "Changes:\nFixed firmware update failure on some systems (Mac M1 & Ryzen).\nFixed Alt trim speaker level bug"
    )
    assert evo8[1].changelog == "Host communication performance improvements with Evo v4.3.8+"
    assert evo16[0].changelog == "Changes:\nAdded a sleep timeout adjustment via Settings Menu"
    assert [r.changelog for r in evo16[1:]] == [
        "Improves ADAT clocking with external devices where SMUX flags are not set correctly",
        "Initial factory firmware release.",
    ]
    assert scraper._parse_article(ID4_MKII)[0].changelog == "Upgrade image format updated (.img file)"


def test_audient_notes_start_at_the_first_version_and_keep_nested_items():
    from src.scrapers.plugins.audient import AudientScraper

    scraper = AudientScraper()

    assert scraper._parse_article(ID44_MKII)[0].changelog == "Fixed analogue output phase alignment"
    assert scraper._parse_article(ID14_MKI)[1].changelog == (
        "Added support for features in upcoming GUI release\nDim attenuation control for monitor controller"
    )


def test_audient_names_products_only_from_firmware_change_log_titles():
    from src.scrapers.plugins.audient import AudientScraper

    scraper = AudientScraper()
    titles = ["EVO SP8 - Firmware Change Log", "ORIA Mini Firmware Changelog", "iD14 (MKI) - Firmware Change Log",
              "ID4 - Firmware Change Log", "EVO Drivers - Change Log", "ORIA Control Desktop Software Changelog",
              "iD48 Firmware Update Procedure"]

    assert [scraper._product_name(t) for t in titles] == [
        "EVO SP8", "ORIA Mini", "iD14 MKI", "iD4 MKI", None, None, None,
    ]


def _articles(page_count, *articles):
    return json.dumps({"articles": list(articles), "page_count": page_count})


def _article(title, body, draft=False):
    return {"title": title, "body": body, "draft": draft, "created_at": "2015-08-03T13:05:04Z",
            "html_url": f"https://support.audient.com/hc/en-us/articles/1-{title.replace(' ', '-')}"}


@pytest.mark.asyncio
async def test_audient_reads_every_help_centre_page():
    from src.scrapers.plugins.audient import AudientScraper as S

    scraper = S()
    asked = _stub_fetch(scraper, {
        S.ARTICLES_URL: _articles(2, _article("EVO 8 Firmware Changelog", EVO_8),
                                  _article("EVO Drivers - Change Log", "<p>V4.3.10</p><p>Driver fix</p>")),
        S.ARTICLES_URL + "&page=2": _articles(2, _article("EVO SP8 - Firmware Change Log", EVO_16),
                                              _article("iD48 - Firmware Changelog", ID44_MKII, draft=True),
                                              _article("iD22 - Firmware Change Log", "<p>No versions yet</p>")),
    })

    devices = {d.name: (d.category, d.firmware_page_url) for d in (await scraper.fetch_device_list()).devices}
    evo8 = await scraper.fetch_firmware_versions("EVO 8", devices["EVO 8"][1])

    assert devices == {
        "EVO 8": ("audio_interface", "https://support.audient.com/hc/en-us/articles/1-EVO-8-Firmware-Changelog"),
        "EVO SP8": ("other", "https://support.audient.com/hc/en-us/articles/1-EVO-SP8---Firmware-Change-Log"),
    }
    assert [(r.version, r.release_date) for r in evo8.firmware_versions] == [("1.4.12", None), ("1.4.7", None)]
    assert len(asked) == 2


@pytest.mark.asyncio
async def test_audient_fails_loudly_without_the_help_centre():
    from src.scrapers.plugins.audient import AudientScraper as S

    scraper = S()
    _stub_fetch(scraper, {})

    assert (await scraper.fetch_device_list()).success is False
