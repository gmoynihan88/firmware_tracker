from datetime import datetime

import pytest

from tests.support import _stub_fetch

MECL = "https://www.mecldata.com/download/asm/"


def _button(label, filename):
    return (
        f'<div class="comp-leqvr0o1"><a aria-label="{label}" class="StylableButton2545352419__root wixui-button" '
        f'data-testid="linkElement" href="{MECL}{filename}" rel="noopener" target="_blank">'
        '<span class="StylableButton2545352419__container"><span class="wixui-button__label" '
        f'data-testid="stylablebutton-label">{label}</span></span></a></div>'
    )


def _layout(*buttons):
    return '<div class="Exmq9">' + "".join(buttons) + "</div>"


DOWNLOADS = (
    "<html><body><h6>DOWNLOADS</h6>"
    + _layout(
        _button("Hydrasynth Explorer Owner's Manual 2.2.0", "Hydrasynth_Explorer_Owners_Manual_2.2.0.pdf"),
        _button("ASM Manager 1.5.9 (Mac) [Leviasynth & Hydrasynth]", "ASM_Manager_Mac_1.5.9.zip"),
        _button("Leviasynth Desktop Firmware Pack 1.2.0", "Leviasynth_Desktop_Firmware_Pack_1.2.0.zip"),
        _button("Diosynth Firmware 1.1.4", "Diosynth_Firmware_1.1.4.dat"),
        _button("Hydrasynth Explorer Firmware Pack 2.2.0", "Hydrasynth_Explorer_Firmware_Pack_2.2.0.zip"),
    )
    + _layout(
        _button("Leviasynth Desktop Firmware Pack 1.1.1", "Leviasynth_Desktop_Firmware_Pack_1.1.1.zip"),
        _button("Hydrasynth Explorer Firmware Pack 2.2.0", "Hydrasynth_Explorer_Firmware_Pack_2.2.0.zip"),
    )
    + "</body></html>"
)
LEGACY = (
    "<html><body><h6>LEGACY FILES</h6>"
    + _layout(
        _button("Hydrasynth Updater 2.1.1 (Win)", "Hydrasynth_Updater_Win_2.1.1.zip"),
        _button("Hydrasynth Explorer Firmware Pack 2.0.0", "Hydrasynth_Explorer_Firmware_Pack_2.0.0.zip"),
        _button("Hydrasynth Explorer Firmware Pack 1.0.0", "Hydrasynth_Explorer_Firmware_Pack_1.0.0.zip"),
        _button("Hydrasynth Keyboard / Desktop Update Notes 1.5.4", "Hydrasynth_KB_DR_Update_Notes_1.5.4.pdf"),
        _button("Hydrasynth Keyboard Firmware Pack 1.5.5", "Hydrasynth_Keyboard_Firmware_Pack_1.5.5.zip"),
    )
    + "</body></html>"
)


def _item(title, date):
    return f"<item><title><![CDATA[{title}]]></title><link>https://example.invalid</link><pubDate>{date}</pubDate></item>"


FEED = (
    '<?xml version="1.0" encoding="UTF-8"?><rss><channel><title><![CDATA[Ashun Sound Machines]]></title>'
    + _item("Leviasynth firmware v1.2 is now available", "Fri, 24 Jul 2026 14:13:52 GMT")
    + _item("Introducing Leviasynth®, the 16-voice, 8-oscillator algorithmic synthesizer", "Mon, 19 Jan 2026 16:26:07 GMT")
    + _item("new 2.2 firmware for all Hydrasynth models", "Thu, 15 May 2025 13:00:18 GMT")
    + _item("Introducing Hydrasynth Explorer 888 units", "Fri, 04 Oct 2024 13:53:26 GMT")
    + "</channel></rss>"
)


def test_asm_reads_product_and_version_from_firmware_file_names_only():
    from src.scrapers.plugins.asm import ASMScraper

    scraper = ASMScraper()

    assert scraper._parse_files(DOWNLOADS) == {
        "Leviasynth Desktop": ["1.2.0", "1.1.1"], "Diosynth": ["1.1.4"], "Hydrasynth Explorer": ["2.2.0"],
    }
    assert scraper._parse_files(LEGACY) == {"Hydrasynth Explorer": ["2.0.0", "1.0.0"], "Hydrasynth Keyboard": ["1.5.5"]}


def test_asm_dates_a_version_from_the_post_that_names_it():
    from src.scrapers.plugins.asm import ASMScraper

    assert ASMScraper()._parse_feed(FEED) == {
        ("Leviasynth", (1, 2)): datetime(2026, 7, 24),
        ("Hydrasynth", (2, 2)): datetime(2025, 5, 15),
    }


@pytest.mark.asyncio
async def test_asm_merges_current_and_legacy_files_newest_first():
    from src.scrapers.plugins.asm import ASMScraper as S

    scraper = S()
    asked = _stub_fetch(scraper, {S.DOWNLOADS_URL: DOWNLOADS, S.LEGACY_URL: LEGACY, S.FEED_URL: FEED})

    devices = [d.name for d in (await scraper.fetch_device_list()).devices]
    explorer = (await scraper.fetch_firmware_versions("Hydrasynth Explorer", S.DOWNLOADS_URL)).firmware_versions
    levia = (await scraper.fetch_firmware_versions("Leviasynth Desktop", S.DOWNLOADS_URL)).firmware_versions

    assert devices == ["Leviasynth Desktop", "Diosynth", "Hydrasynth Explorer"]
    assert [(r.version, r.release_date) for r in explorer] == [
        ("2.2.0", datetime(2025, 5, 15)), ("2.0.0", None), ("1.0.0", None),
    ]
    assert [(r.version, r.release_date) for r in levia] == [("1.2.0", datetime(2026, 7, 24)), ("1.1.1", None)]
    assert len(asked) == 3


@pytest.mark.asyncio
async def test_asm_keeps_current_firmware_when_legacy_and_feed_fail():
    from src.scrapers.plugins.asm import ASMScraper as S

    scraper = S()
    _stub_fetch(scraper, {S.DOWNLOADS_URL: DOWNLOADS.replace("Pack_1.1.1", "Pack_1.10.0")})

    levia = await scraper.fetch_firmware_versions("Leviasynth Desktop", S.DOWNLOADS_URL)

    assert levia.success is True
    assert [(r.version, r.release_date) for r in levia.firmware_versions] == [("1.10.0", None), ("1.2.0", None)]


@pytest.mark.asyncio
async def test_asm_fails_loudly_without_the_downloads_page():
    from src.scrapers.plugins.asm import ASMScraper as S

    scraper = S()
    _stub_fetch(scraper, {})

    assert (await scraper.fetch_device_list()).success is False
