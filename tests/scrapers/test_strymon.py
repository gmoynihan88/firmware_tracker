def test_strymon_reads_all_three_firmware_spellings():
    """Strymon writes the same thing three ways across its range.

    The old parser looked for "firmware v1.49" and Strymon writes "Firmware Rev.
    1.49", so fourteen of fifteen products stored nothing at all while the scrape
    reported no failures.
    """
    from src.scrapers.plugins.strymon import StrymonScraper

    html = """
      <p>BigSky Firmware Rev. 1.49 (Released March 2019):</p>
      <p>NightSky Firmware REV v1.07 (Released March 2021)</p>
      <p>Sunset Firmware REV v 1.23 (Release August 2018)</p>
      <p>Firmware Rev. 1.15</p>
    """
    versions = StrymonScraper()._parse_firmware(html)
    dates = {f.version: f.release_date for f in versions}

    assert set(dates) == {"1.49", "1.07", "1.23", "1.15"}
    assert dates["1.49"].strftime("%Y-%m-%d") == "2019-03-01"   # month precision
    assert dates["1.07"].strftime("%Y-%m-%d") == "2021-03-01"   # "REV v1.07"
    assert dates["1.23"].strftime("%Y-%m-%d") == "2018-08-01"   # "Release", not "Released"
    assert dates["1.15"] is None                                 # no date given


def test_strymon_ignores_versions_that_are_not_releases():
    """The same pages carry the Nixie editor and MIDI compatibility prose.

    "must have firmware version 1.20 or later" is a requirement, not a release, and a
    pattern accepting "firmware version" would report it as one.
    """
    from src.scrapers.plugins.strymon import StrymonScraper

    html = """
      <p>Nixie 1.0</p><p>Version: 0.9.4.3</p>
      <p>Mac OS X - 10.6.8, 10.7.x</p>
      <p>***In order to control Sunset with MIDI, it must have firmware version 1.20 or later</p>
    """
    assert StrymonScraper()._parse_firmware(html) == []
