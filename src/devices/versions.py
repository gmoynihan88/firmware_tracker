"""One rule for ordering version strings, and its sortable encoding.

`parse_version` is the rule this app already used in two places: pull the runs of
digits out of a version string and compare them as integers, so 1.11 ranks above 1.9
and `2.50a` compares as `(2, 50)`. It is what decides which firmware row carries
`is_latest`, so anything that claims to order versions has to agree with it -- or the
catalogue sorts one way while the app believes another, which is exactly the kind of
quiet disagreement this project is arranged against.

`version_sort_key` is that same rule encoded as a string a database can `ORDER BY`:
each run of digits zero-padded to a fixed width and joined, so lexicographic order
reproduces the tuple order. The catalogue sorts every product by version and then
shows a page of them, and the sort has to happen in SQL -- before the slice, not after
it -- which rules out comparing tuples in Python.

The encoding holds for versions of unequal length too, which is not obvious. `1.2`
encodes to a prefix of what `1.2.0` encodes to, and a shorter prefix sorts first in
string comparison exactly as `(1, 2)` sorts before `(1, 2, 0)`. The separator is "."
(ASCII 46), below every digit, so a boundary can never outrank a segment either.
"""

import re

# Nine digits holds any release number these vendors publish, including the date-shaped
# builds (Roland writes some as 20240115). A segment wider than this would sort wrong
# rather than raise, so the width is deliberately generous.
_SEGMENT_WIDTH = 9


def parse_version(version: str) -> tuple:
    """A version string as the tuple of numbers in it, for comparison."""
    parts = re.findall(r"\d+", version or "")
    return tuple(int(part) for part in parts) if parts else (0,)


def version_sort_key(version: str) -> str:
    """`parse_version`'s ordering, encoded so a database can sort by it."""
    return ".".join(f"{part:0{_SEGMENT_WIDTH}d}" for part in parse_version(version))
