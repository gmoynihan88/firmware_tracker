import asyncio
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _script(name):
    """Import a script from scripts/, which is not a package."""
    spec = importlib.util.spec_from_file_location(f"scripts_{name}", ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- sweep_scrapers ------------------------------------------------------------


@pytest.mark.asyncio
async def test_sweep_reports_every_scraper_and_survives_one_blowing_up(monkeypatch):
    """A crash, a timeout and failed devices are each a failure; none of them ends the sweep."""
    sweep = _script("sweep_scrapers")
    monkeypatch.setattr(sweep, "PER_SCRAPER_TIMEOUT", 0.05)

    async def scrape(slug):
        if slug == "crashes":
            raise RuntimeError("boom")
        if slug == "hangs":
            await asyncio.sleep(1)
        if slug == "partial":
            return {"success": True, "devices_synced": {"total": 3, "created": 0}, "devices_failed": ["X"]}
        return {"success": True, "devices_synced": {"total": 5, "created": 2}, "devices_failed": []}

    lines = []
    outcomes = await sweep.run_sweep(["crashes", "fine", "hangs", "partial"], scrape, lines.append)

    assert [(o.slug, o.ok) for o in outcomes] == [("crashes", False), ("fine", True), ("hangs", False), ("partial", False)]
    assert "RuntimeError: boom" in outcomes[0].detail
    assert "TimeoutError" in outcomes[2].detail
    assert outcomes[1].created == 2 and outcomes[3].failed == 1
    assert len(lines) == 4 and lines[1].startswith("fine") and " ok " in lines[1]


def test_sweep_selects_slugs_and_refuses_unknown_ones():
    sweep = _script("sweep_scrapers")

    assert sweep.select(["b", "a", "c"], [], ["c"]) == ["a", "b"]
    assert sweep.select(["b", "a", "c"], ["c", "a"], []) == ["a", "c"]
    with pytest.raises(SystemExit):
        sweep.select(["a"], ["typo"], [])


# --- update_readme_counts ------------------------------------------------------


README_SAMPLE = """This scrapes 3 manufacturers on a schedule.

- **Scrapes 3 manufacturers** — A, B

**Add devices** from the catalogue. 1,000 devices across 3 vendors, so it pages.

## Supported manufacturers

| Hardware | Plugins |
|---|---|
| Arturia\\* | Apple (Logic Pro, MainStage) |
| Keith McMillen | Arturia\\* |

    plugins/           # One file per manufacturer (3 scrapers)
"""


def test_readme_counts_rewrite_every_place_the_count_appears():
    counts = _script("update_readme_counts")

    text, unmatched = counts.apply_counts(README_SAMPLE, counts.README_SCRAPER_COUNTS, 4)
    text, unmatched_devices = counts.apply_devices(text, 1234, 4)

    assert not unmatched and not unmatched_devices
    assert "This scrapes 4 manufacturers" in text and "**Scrapes 4 manufacturers**" in text
    assert "(4 scrapers)" in text and "1,234 devices across 4 vendors" in text


def test_readme_counts_leave_the_device_count_alone_without_a_database():
    counts = _script("update_readme_counts")

    text, _ = counts.apply_devices(README_SAMPLE, None, 4)

    assert "1,000 devices across 4 vendors" in text


def test_readme_counts_say_when_a_sentence_was_reworded():
    counts = _script("update_readme_counts")

    _, unmatched = counts.apply_counts("We scrape lots of vendors.", counts.README_SCRAPER_COUNTS, 4)

    assert len(unmatched) == 3


def test_readme_table_matches_names_without_asterisks_brackets_or_suffixes():
    counts = _script("update_readme_counts")

    missing = counts.missing_from_table(README_SAMPLE, ["Arturia", "Apple", "Keith McMillen Instruments", "Waves"])

    assert missing == ["Waves"]


def test_readme_counts_match_the_registry():
    """A scraper PR that forgets the counts fails here; update_readme_counts.py fixes it."""
    counts = _script("update_readme_counts")
    from src.scrapers.registry import ScraperRegistry

    scrapers = ScraperRegistry.get_all_scrapers()
    readme = (ROOT / "README.md").read_text()
    claude = (ROOT / "CLAUDE.md").read_text()

    assert counts.apply_counts(readme, counts.README_SCRAPER_COUNTS, len(scrapers)) == (readme, [])
    assert counts.apply_devices(readme, None, len(scrapers)) == (readme, [])
    assert counts.apply_counts(claude, [counts.CLAUDE_SCRAPER_COUNT], len(scrapers)) == (claude, [])
    assert counts.missing_from_table(readme, [cls.manufacturer_name for cls in scrapers.values()]) == []


# --- compare_css ---------------------------------------------------------------


def test_compare_css_reports_only_properties_that_changed():
    compare = _script("compare_css")

    before = {"color": "red", "margin": "0px", "--accent": "amber"}
    after = {"color": "red", "margin": "8px", "padding": "1px"}

    assert compare.differences(before, after) == {
        "--accent": ("amber", None), "margin": ("0px", "8px"), "padding": (None, "1px"),
    }
    assert compare.differences(before, dict(before)) == {}


def test_compare_css_covers_device_pages_only_when_a_device_exists():
    compare = _script("compare_css")

    assert "/devices/7/edit" in compare.default_pages(7)
    assert not [p for p in compare.default_pages(None) if p.startswith("/devices/") and p != "/devices/add"]
    assert "/catalog#dialog" in compare.default_pages(None)
