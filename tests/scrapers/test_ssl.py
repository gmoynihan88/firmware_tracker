import json
from datetime import datetime

import pytest

from tests.support import _stub_fetch

S3 = "https://s3.dualstack.eu-west-2.amazonaws.com/zendesk.download.solidstatelogic.com/Plugins"


def _software_table(*rows):
    body = "".join(f'<tr>\n<td style="width: 33.2857%;">{label}</td>\n<td>Mac</td>\n<td>Windows</td>\n</tr>\n' for label in rows)
    return (
        '<figure class="wysiwyg-table wysiwyg-table-align-left"><table style="margin-left: 0px;"><tbody>\n'
        '<tr style="height: 22px;">\n<td><strong>Software</strong></td>\n<td colspan="2"><strong>Platform</strong></td>\n</tr>\n'
        + body + "</tbody></table></figure>"
    )


RELEASE_NOTES = (
    '<h2 id="h_1">V2.1.12</h2><p>Released: 11th August 2026</p>'
    "<p>Please update SSL 360° itself, all 360°-enabled plug-ins and UC1/UF8/UF1/SSL 18/SSL 12 firmware.</p>"
    + _software_table("SSL 360° V2.1.12", "4K B v1.10.2 (sonible add-on)")
    + '<h4 id="h_2">New in SSL 360° v2.1.12</h4><ul><li>Harrison 32C is natively 360°-enabled.</li></ul>'
    '<h2 id="h_3"> </h2>'
    '<h2 id="h_4">V1.9.12</h2><p>Released June 2025</p>' + _software_table("4K G V1.0.11")
    + '<h2 id="h_5">V1.8.10</h2><p><span style="color: #333333;"><em>Released January 2025</em></span></p>'
    '<div class="callout callout--danger"><p>After you have installed SSL 360 v1.8.10, update your SSL 18 firmware.</p></div>'
    '<h2 id="h_6"><span style="color: #333333;">V1.6.13</span></h2>'
    '<div class="callout callout--danger"><p>Please ensure you update SSL 360° and all 360°-enabled plug-ins.</p></div>'
    '<p style="background-color: white;">Released as per v1.6.12</p>'
    '<h2 id="h_7">V1.6.12</h2><p><strong>Released October 2023</strong></p><p> </p>'
)


def _plugin_row(label, *files):
    buttons = "".join(
        f'<td style="text-align: center;"><span style="color: #0000FF;"><span class="btn btn-one" '
        f'data-link="{S3}/{f}\n">{"Mac" if i == 0 else "Windows"}</span></span></td>\n'
        for i, f in enumerate(files)
    )
    return f'<tr>\n<td style="width: 339.531px;">{label}</td>\n{buttons}</tr>\n'


PLUGINS = (
    '<h3 id="01H8"><span style="color: #0000CC;">360° Enabled Plug-ins</span></h3><h2 id="h_a">V2.1.12</h2>'
    '<figure class="wysiwyg-table"><table><thead><tr><th><strong>Software</strong></th><th colspan="2">Platform</th></tr></thead><tbody>\n'
    + _plugin_row("SSL 360° V2.1.12", "SSL360/SSL%20360%20macOS%20v2.1.12.dmg")
    + _plugin_row("4K G v1.3.1 (sonible add-on)", "4KG%20sonible/2026.05.01%20-%20v1.3.1/SSL%204K%20G%20sonible%20macOS%20v1.3.1.dmg")
    + _plugin_row("4K G v1.2.7", "4KG/2025.10.28%20-%20v1.2.7/SSL%204K%20G%20macOS%20v1.2.7%20Installer.dmg",
                  "4KG/2025.10.28%20-%20v1.2.7/SSL%204K%20G%2064-bit%20v1.2.6.exe")
    + _plugin_row("Harrison 32 Classic Channel Strip V2.0.20",
                  "Harrison%2032%20Classic%20Channel%20strip/2026.07.23%20-%20v2.0.19/Harrison%2032Classic%2064-bit.exe")
    + "</tbody></table></figure>"
    '<h3 id="01H9"><span style="color: #0000CC;">SSL Plug-ins</span></h3>'
    '<figure class="wysiwyg-table"><table><thead><tr><th><strong>Plug-in</strong></th><th colspan="2">Platform</th></tr></thead><tbody>\n'
    + _plugin_row("AutoEQ v1.0.41", "AutoEQ/SSL%20autoEQ%20macOS%20v1.0.43%20Installer.dmg",
                  "AutoEQ/SSL%20autoEQ%2064-bit%20v1.0.41.exe")
    + _plugin_row("X-Phase v6.10.15", "X-Phase/SSL%20X-Phase%20macOS%20v6.9.3%20Installer.dmg",
                  "X-Phase/SSL%20X-Phase%2064-bit%20v6.10.15.exe")
    + "</tbody></table></figure>"
)

INTERFACES = (
    '<h1 id="h_p">Package History and Downloads</h1><p>The package history below details the changes.</p>'
    '<h2 id="h_q">V1.5</h2><p><span style="color: #0000FF;"><span class="btn btn-one" '
    'data-link="https://s3.eu-west-2.amazonaws.com/zendesk.download.solidstatelogic.com/Interfaces/SSLAudioFirmwareUpdater_V1-5.zip">'
    "Update Package for Mac and Windows</span></span></p>"
    "<p>Summary: Additional Stereo Loopback Channels and Roundtrip Latency Improvements for SSL 2 MK II and SSL 2+ MK II </p>"
    "<p><em>SSL 2 MK II/SSL 2+ MK II Firmware Number: V1.16 (UID 31852)</em></p><div>\n"
    '<p><span lang="EN-GB">• 2 </span><span lang="EN-GB">additional</span><span lang="EN-GB"> Stereo Loopback channels</span></p>\n'
    "</div>"
    '<h2 id="h_r">V1.4</h2><p><span class="btn btn-one">Update Package for Mac and Windows</span></p>'
    "<p>Summary: Bug fix for SSL 2+ MKII</p><p>SSL 2+ MKII Firmware Number: V1.08 (UID 30240)</p>"
    "<p>• Resolved polarity inversion on channels 3 &amp; 4 </p>"
    '<h2 id="h_s"> </h2>'
    '<h2 id="h_t">V1.3</h2><p><span class="btn btn-one">Update Package for Mac and Windows</span></p>'
    "<p>Summary: Bug fixes for PURE DRIVE QUAD and OCTO.</p>"
    "<p><em>PURE DRIVE QUAD and OCTO Firmware Version Number: V1.11 (UID: V29372)</em></p>"
    "<ul>\n<li>Internal clock reporting as invalid on MacOS fixed.</li>\n</ul>"
    '<h2 id="h_u">V1.2</h2><p><strong>Downloads</strong></p><p><span class="btn btn-one">Update Package for Mac and Windows</span></p>'
    "<p>Summary: Loopback added for SSL 2 and SSL 2+</p><p><em>SSL 2/2+ Firmware Version Number: V1.10 (UID28584)</em></p>"
    "<ul><li>Loopback feature added</li></ul>"
    '<h2 id="h_v">V1.1</h2><p>Summary: Bug fixes for BiG SiX</p><p><em>BiG SiX Firmware: V1.18 (UID 27922) </em></p>'
    '<h3 id="h_w">Update Instructions</h3><p>Ensure your SSL hardware device is powered on.</p>'
)

HC = "https://support.solidstatelogic.com/hc/en-gb/articles"

SOLSA_LINK = "https://support.download.solidstatelogic.com/Live/SOLSA%20Installers/Live%20SOLSA%20V{}.zip"

# As served: one button per release. V5.2.18's item carries a second, empty span
# pointing at the older V5.1.14 installer.
SOLSA = (
    '<h3>Remote Control &amp; Offline Setup Software</h3><p>SOLSA is a standalone version of Live console software.</p><ul>\n'
    '<li class="wysiwyg-list-color" data-list-item-id="e261"><span style="color: #0000CC;"><span class="btn btn-one wysiwyg-text-align-left" data-link="' + SOLSA_LINK.format("6.2.14") + '">V6.2.14 SOLSA Installer and Documentation</span></span></li>\n'
    '<li data-list-item-id="eecb">\n<span style="color: #0000CC;"><span class="btn btn-one wysiwyg-text-align-left" data-link="' + SOLSA_LINK.format("5.2.18") + '">V5.2.18 SOLSA Installer and Documentation</span></span><span style="color: #000000;"><span class="btn btn-one wysiwyg-text-align-left" style="color: #0000CC;" data-link="' + SOLSA_LINK.format("5.1.14") + '"></span></span>\n</li>\n'
    '<li class="wysiwyg-list-color" data-list-item-id="e549"><span style="color: #0000CC;"><span class="btn btn-one wysiwyg-text-align-left" data-link="' + SOLSA_LINK.format("5.1.14") + '">V5.1.14 SOLSA Installer and Documentation</span></span></li>\n'
    '<li class="wysiwyg-list-color" data-list-item-id="e523">\n<span style="color: #0000CC;"><span class="btn btn-one wysiwyg-text-align-left" data-link="' + SOLSA_LINK.format("4.10.17") + '">V4.10.17 SOLSA Installer and Documentation</span></span><br>\xa0</li>\n'
    '</ul><h3>\n<br><span style="color: #990000;">Requirements</span>\n</h3><p>Microsoft Windows 10 64-bit or Windows 11.</p>'
)


def _search(*articles):
    return json.dumps({"count": len(articles), "results": [
        {"title": title, "body": body, "html_url": f"{HC}/{i}-{title.replace(' ', '-')}", "locale": "en-gb"}
        for i, (title, body) in enumerate(articles)
    ]})


def test_ssl_dates_each_360_release_from_its_own_release_line():
    from src.scrapers.plugins.ssl import SSLScraper

    releases = SSLScraper()._parse_release_notes(RELEASE_NOTES)

    assert [(r.version, r.release_date) for r in releases] == [
        ("2.1.12", datetime(2026, 8, 11)), ("1.9.12", datetime(2025, 6, 1)), ("1.8.10", datetime(2025, 1, 1)),
        ("1.6.13", None), ("1.6.12", datetime(2023, 10, 1)),
    ]
    assert releases[0].changelog == (
        "Please update SSL 360° itself, all 360°-enabled plug-ins and UC1/UF8/UF1/SSL 18/SSL 12 firmware.\n"
        "New in SSL 360° v2.1.12\nHarrison 32C is natively 360°-enabled."
    )


def test_ssl_reads_plugin_versions_from_the_newest_download_file():
    from src.scrapers.plugins.ssl import SSLScraper

    assert SSLScraper()._parse_plugins(PLUGINS) == {
        "4K G (sonible add-on)": "1.3.1",
        "4K G": "1.2.7",
        "Harrison 32 Classic Channel Strip": "2.0.20",
        "AutoEQ": "1.0.43",
        "X-Phase": "6.10.15",
    }


def test_ssl_splits_each_firmware_line_into_its_models():
    from src.scrapers.plugins.ssl import SSLScraper

    firmware = SSLScraper()._parse_interfaces(INTERFACES)

    assert {model: [r.version for r in rs] for model, rs in firmware.items()} == {
        "SSL 2 MKII": ["1.16"], "SSL 2+ MKII": ["1.16", "1.08"], "PureDrive Quad": ["1.11"],
        "PureDrive Octo": ["1.11"], "SSL 2": ["1.10"], "SSL 2+": ["1.10"], "BiG SiX": ["1.18"],
    }
    assert firmware["SSL 2+ MKII"][1].changelog == (
        "Summary: Bug fix for SSL 2+ MKII\n• Resolved polarity inversion on channels 3 & 4"
    )


@pytest.mark.asyncio
async def test_ssl_takes_each_article_by_its_exact_title():
    from src.scrapers.plugins.ssl import SSLScraper as S

    scraper = S()
    asked = _stub_fetch(scraper, {
        S.search_url(S.RELEASE_NOTES): _search(("Rolling back to a previous version of SSL 360°", "<h2>V9.9.9</h2>"),
                                               (S.RELEASE_NOTES, RELEASE_NOTES)),
        S.search_url(S.PLUGINS): _search(("Legacy plugin downloads", _plugin_row("Blitzer V1.0.5*")), (S.PLUGINS, PLUGINS)),
        S.search_url(S.INTERFACES): _search((S.INTERFACES, INTERFACES)),
        S.search_url(S.SOLSA): _search(("Live Operational and Install Guides", "<p>V9.9.9 SOLSA Installer</p>"), (S.SOLSA, SOLSA)),
    })

    devices = {d.name: (d.category, d.firmware_page_url) for d in (await scraper.fetch_device_list()).devices}
    app = await scraper.fetch_firmware_versions("SSL 360°", devices["SSL 360°"][1])

    assert devices["SSL 360°"] == ("other", f"{HC}/1-SSL-360°-Downloads-and-Release-Notes")
    assert devices["AutoEQ"][0] == "vst_plugin" and devices["BiG SiX"][0] == "audio_interface"
    assert "Blitzer" not in devices and len(devices) == 14
    assert devices["SOLSA"] == ("other", f"{HC}/1-Live-SOLSA-Downloads")
    assert app.firmware_versions[0].version == "2.1.12"
    solsa = await scraper.fetch_firmware_versions("SOLSA", devices["SOLSA"][1])
    assert solsa.firmware_versions[0].version == "6.2.14", "read the install guide's version"
    assert len(asked) == 4


@pytest.mark.asyncio
async def test_ssl_fails_loudly_when_any_article_is_missing():
    from src.scrapers.plugins.ssl import SSLScraper as S

    scraper = S()
    _stub_fetch(scraper, {
        S.search_url(S.RELEASE_NOTES): _search((S.RELEASE_NOTES, RELEASE_NOTES)),
        S.search_url(S.PLUGINS): _search(("SSL Download Manager - Getting Started", "<p>Install it.</p>")),
        S.search_url(S.INTERFACES): _search((S.INTERFACES, INTERFACES)),
        S.search_url(S.SOLSA): _search((S.SOLSA, SOLSA)),
    })

    assert (await scraper.fetch_device_list()).success is False

    scraper = S()
    _stub_fetch(scraper, {
        S.search_url(S.RELEASE_NOTES): _search((S.RELEASE_NOTES, RELEASE_NOTES)),
        S.search_url(S.PLUGINS): _search((S.PLUGINS, PLUGINS)),
        S.search_url(S.INTERFACES): _search((S.INTERFACES, INTERFACES)),
        S.search_url(S.SOLSA): _search(("Live Operational and Install Guides", "<p>Guides.</p>")),
    })

    assert (await scraper.fetch_device_list()).success is False


def test_ssl_reads_solsa_releases_from_their_download_buttons():
    """Each button's own text, not the empty span beside V5.2.18 that links V5.1.14."""
    from src.scrapers.plugins.ssl import SSLScraper

    releases = SSLScraper()._parse_solsa(SOLSA)

    assert [(r.version, r.release_date) for r in releases] == [
        ("6.2.14", None), ("5.2.18", None), ("5.1.14", None), ("4.10.17", None),
    ]
    assert releases[1].download_url == SOLSA_LINK.format("5.2.18")
