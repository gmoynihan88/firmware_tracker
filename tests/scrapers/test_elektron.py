ELEKTRON_PAGE = """
<div class="group-content">
  <div><h3>Digitakt OS 1.53</h3></div>
  <div><h3>Sept 9, 2026</h3></div>
  <div class="rich-text"><p>Adds Outbox 8 configuration support.</p>
    <p><a href="../wp-content/uploads/2026/09/Digitakt_OS1.53_dist.zip">DOWNLOAD OS</a></p>
  </div>
</div>
<div class="group-content">
  <div><h3>Elektron Transfer 1.10.4</h3></div>
  <div><h3>Jun 23, 2026</h3></div>
  <div class="rich-text"><p>Transfer is the go to tool for samples.</p></div>
</div>
"""


def test_elektron_reads_the_os_and_ignores_companion_software():
    """The same page lists the instrument OS and Elektron Transfer.

    Transfer is a desktop app with its own numbering. Requiring "OS" in the heading
    is what separates them, the way Eventide's H90 page needs its companion apps kept
    apart from the pedal.
    """
    from src.scrapers.plugins.elektron import ElektronScraper

    versions = ElektronScraper()._parse_updates(
        ELEKTRON_PAGE, "https://www.elektron.se/support-downloads/digitakt"
    )

    assert [f.version for f in versions] == ["1.53"]
    assert "1.10.4" not in [f.version for f in versions]


def test_elektron_accepts_a_four_letter_month():
    """Pages use both "Sep 9, 2026" and "Sept 9, 2026".

    strptime's %b accepts the first and rejects the second, so a pattern matching
    both while parsing with %b dropped the date on every MKII page while looking
    like it handled them.
    """
    from src.scrapers.plugins.elektron import ElektronScraper

    versions = ElektronScraper()._parse_updates(ELEKTRON_PAGE, "https://e.invalid/x")
    assert versions[0].release_date.strftime("%Y-%m-%d") == "2026-09-09"

    short = ELEKTRON_PAGE.replace("Sept 9, 2026", "Sep 9, 2026")
    assert ElektronScraper()._parse_updates(short, "https://e.invalid/x")[0].release_date


def test_elektron_resolves_the_relative_download_url():
    """Elektron writes "../wp-content/...", which needs joining to the page.

    Storing it unjoined produces the same broken shape an older TAL scraper left in
    the database: dot-segments in the hostname, resolving nowhere.
    """
    from src.scrapers.plugins.elektron import ElektronScraper
    from src.scrapers.service import _clean_url

    versions = ElektronScraper()._parse_updates(
        ELEKTRON_PAGE, "https://www.elektron.se/support-downloads/digitakt"
    )
    url = versions[0].download_url

    assert url == "https://www.elektron.se/wp-content/uploads/2026/09/Digitakt_OS1.53_dist.zip"
    assert _clean_url(url) == url
