"""The one rule for ordering versions, and the encoding the database sorts by.

These matter more than their size suggests: `parse_version` decides which firmware row
is `is_latest`, and `version_sort_key` decides what order the catalogue shows. If the
two ever disagree, the page sorts one way while the app believes another -- and nothing
raises.
"""

import pytest

from src.devices.versions import parse_version, version_sort_key


def test_eleven_ranks_above_nine():
    """The case that rules out sorting version strings as text: 1.11 is after 1.9."""
    assert parse_version("1.11") > parse_version("1.9")
    assert version_sort_key("1.11") > version_sort_key("1.9")
    assert sorted(["1.9", "1.11", "1.2"], key=version_sort_key) == ["1.2", "1.9", "1.11"]


@pytest.mark.parametrize(
    "versions",
    [
        ["1.0", "1.0.1", "1.1", "2.0", "10.0"],
        ["0.9.9", "1.0.0", "1.0.1", "1.10.0", "1.9.0"],
        ["2.50a", "2.60", "3.0", "10.1"],
        ["1.82", "1.9", "1.100"],
    ],
)
def test_the_key_orders_exactly_like_the_tuple(versions):
    """The encoding is only worth having while it reproduces the comparison."""
    assert sorted(versions, key=version_sort_key) == sorted(versions, key=parse_version)


def test_a_version_with_no_digits_sorts_below_every_real_one():
    """`parse_version` falls back to (0,), and the key has to agree with that."""
    assert parse_version("unknown") == (0,)
    assert version_sort_key("unknown") < version_sort_key("0.1")
    assert sorted(["1.0", "unknown", "0.5"], key=version_sort_key)[0] == "unknown"


def test_a_suffix_compares_on_the_numbers_around_it():
    """Zoom ships 2.50a as a real release; the letter is not a segment."""
    assert parse_version("2.50a") == (2, 50)
    assert version_sort_key("2.50a") == version_sort_key("2.50")
    assert version_sort_key("2.50a") < version_sort_key("2.60")


def test_a_date_shaped_build_fits_the_segment_width():
    """Roland writes some builds as a date. Nine digits is chosen to hold these."""
    assert version_sort_key("20240115") < version_sort_key("20240116")
    assert version_sort_key("20240115") > version_sort_key("9.9.9")


def test_versions_of_unequal_length_keep_the_tuple_order():
    """The non-obvious half: a shorter version encodes to a prefix of a longer one.

    (1, 2) sorts before (1, 2, 0) as tuples, and "…002" is a prefix of "…002.…000",
    which sorts first as a string for the same reason. The separator is "." -- below
    every digit in ASCII -- so a segment boundary can never outrank a segment.
    """
    assert parse_version("1.2") < parse_version("1.2.0")
    assert version_sort_key("1.2") < version_sort_key("1.2.0")
    assert sorted(["1.2.0", "1.2"], key=version_sort_key) == ["1.2", "1.2.0"]
    assert sorted(["1.2.1", "1.2"], key=version_sort_key) == ["1.2", "1.2.1"]


def test_both_services_use_this_rule_rather_than_their_own_copy():
    """Each service had its own identical copy; a third encoding is the danger.

    Pinned by identity, so re-introducing a local copy fails here instead of silently
    disagreeing with the stored sort key once the two implementations drift.
    """
    from src.devices import service as device_service
    from src.scrapers import service as scraper_service

    assert scraper_service.parse_version is parse_version
    assert device_service._parse_version is parse_version
