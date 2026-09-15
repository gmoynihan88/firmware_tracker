import pytest

from tests.support import _stub_fetch


def _neural_index() -> str:
    return """
    <article><a href="/us/quad-cortex-updates/coros-4-1-0-and-cortex-control-4-1-0-are-now-available">x</a>
      <time>August 26, 2026</time></article>
    <article><a href="/us/quad-cortex-updates/coros-3-3-1-and-cortex-control-1-4-1-are-now-available">x</a>
      <time>December 15, 2025</time></article>
    <article><a href="/us/quad-cortex-updates/coros-and-cortex-control-4-2-0-are-now-available">x</a>
      <time>September 2, 2026</time></article>
    <article><a href="/us/quad-cortex-updates/coros-3-0-0-release-schedule">x</a>
      <time>July 30, 2024</time></article>
    <article><a href="/us/quad-cortex-updates/quad-cortex-development-update-59">x</a>
      <time>June 1, 2026</time></article>
    """


def test_neural_takes_coros_not_cortex_control():
    """Each slug names the firmware and the desktop editor.

    CorOS 3.3.1 shipped with Cortex Control 1.4.1; on recent releases the two have
    converged, which is what would make taking the wrong one invisible until they
    diverge again.
    """
    from src.scrapers.plugins.neural_dsp import NeuralDSPScraper as N

    versions = {fw.version for fw in N()._parse_index(_neural_index())}

    assert "3.3.1" in versions
    assert "1.4.1" not in versions, "took the Cortex Control editor version"


def test_neural_handles_both_slug_shapes():
    """"coros-4-1-0-and-..." and "coros-and-cortex-control-4-2-0-..." both appear."""
    from src.scrapers.plugins.neural_dsp import NeuralDSPScraper as N

    versions = [fw.version for fw in N()._parse_index(_neural_index())]

    assert versions[:2] == ["4.2.0", "4.1.0"]


def test_neural_skips_posts_that_are_not_releases():
    """The index also carries release schedules and development updates, several of
    which name a version that had not shipped."""
    from src.scrapers.plugins.neural_dsp import NeuralDSPScraper as N

    versions = {fw.version for fw in N()._parse_index(_neural_index())}

    assert "3.0.0" not in versions, "took the release-schedule post"
    assert versions == {"4.2.0", "4.1.0", "3.3.1"}


def test_neural_dates_each_release_from_its_card():
    from src.scrapers.plugins.neural_dsp import NeuralDSPScraper as N

    by_version = {fw.version: fw for fw in N()._parse_index(_neural_index())}

    assert by_version["4.1.0"].release_date.strftime("%Y-%m-%d") == "2026-08-26"
    assert by_version["3.3.1"].release_date.strftime("%Y-%m-%d") == "2025-12-15"


@pytest.mark.asyncio
async def test_neural_lists_quad_cortex_and_reads_the_index_once():
    from src.scrapers.plugins.neural_dsp import NeuralDSPScraper as N

    scraper = N()
    asked = _stub_fetch(scraper, {N.UPDATES_URL: _neural_index()})

    devices = await scraper.fetch_device_list()
    await scraper.fetch_firmware_versions("Quad Cortex", "")

    assert [d.name for d in devices.devices] == ["Quad Cortex"]
    assert len(asked) == 1


@pytest.mark.asyncio
async def test_neural_fails_when_no_release_post_is_found():
    """An index of development updates and nothing shipped is a changed page.

    Nano and Mini Cortex have their own lines this page does not cover, so an
    empty read here is not "Neural published nothing".
    """
    from src.scrapers.plugins.neural_dsp import NeuralDSPScraper as N

    scraper = N()
    _stub_fetch(scraper, {N.UPDATES_URL:
                '<a href="/us/quad-cortex-updates/quad-cortex-development-update-60">x</a>'})

    assert (await scraper.fetch_device_list()).success is False
