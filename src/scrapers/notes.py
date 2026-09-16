"""Release notes as lines: one per paragraph, heading and list item.

`get_text(" ")` over a notes block runs every bullet into the next, and the result
reads as one sentence -- "Fixed pairing issue if pedal was previously paired First
MIDI CC now responds correctly". The catalog dialog and the device page both keep
line breaks, so the stored text should carry them.

Three traps, all from live vendor markup:

- Editors split words across inline elements: `(t</span><span>o reduce`. Joining
  text nodes with a space writes "(t o reduce".
- Collapsing whitespace inside each element loses the space *between* elements:
  `or in </span><a>UAFX Control` becomes "inUAFX". Whitespace is collapsed once, over
  the whole line.
- A `<br>` is a line the author meant. Ableton writes a list item's sub-points as
  "Updated Max 9.1.5 to 3db35fa:<br/>- MIDI: ...<br/>- Parameters: ...", and reading
  the break as a space runs them together again.
"""
from typing import Iterable, Iterator, List, Optional, Sequence

from bs4 import Comment, Tag

BLOCKS = ("p", "h2", "h3", "h4", "h5", "h6", "li")
LISTS = ("ul", "ol")
SKIPPED = ("script", "style")
NOTES_LIMIT = 4000
_BREAK = "\x00"


def inline_lines(element: Tag) -> List[str]:
    """An element's text, one entry per `<br>`-separated line, nested lists excluded."""

    def raw(node: Tag) -> str:
        parts = []
        for child in node.children:
            if isinstance(child, Comment):
                continue
            name = getattr(child, "name", None)
            if name in LISTS or name in SKIPPED:
                continue
            if name == "br":
                parts.append(_BREAK)
            elif name:
                parts.append(raw(child))
            else:
                parts.append(str(child))
        return "".join(parts)

    return [line for line in (" ".join(part.split()) for part in raw(element).split(_BREAK)) if line]


def inline_text(element: Tag) -> str:
    """An element's text on one line."""
    return " ".join(inline_lines(element))


def elements_of(nodes: Iterable[Tag]) -> Iterator:
    """Each node followed by everything inside it, in document order."""
    for node in nodes:
        yield node
        yield from node.descendants


def note_lines(elements: Iterable, blocks: Sequence[str] = BLOCKS) -> List[str]:
    """Lines from elements in document order: "- item", nested items indented.

    A paragraph inside a list item is part of that item, not a line of its own, and
    a break inside an item continues under it. Nesting is counted only among the
    items passed in, so a notes block that sits inside a page's own list is not
    indented for it.
    """
    lines: List[str] = []
    items = set()
    for element in elements:
        if not isinstance(element, Tag) or element.name not in blocks:
            continue
        depth = sum(1 for parent in element.parents if id(parent) in items)
        if element.name != "li" and depth:
            continue
        text = inline_lines(element)
        if element.name == "li":
            items.add(id(element))
            indent = "  " * depth
            lines.extend(
                indent + ("- " if index == 0 else "  ") + line for index, line in enumerate(text)
            )
        else:
            lines.extend(text)
    return lines


def join_notes(lines: Iterable[str], limit: int = NOTES_LIMIT) -> Optional[str]:
    """The lines as stored, cut at the last whole line that fits the limit."""
    text = "\n".join(lines)
    if len(text) > limit:
        cut = text.rfind("\n", 0, limit + 1)
        text = text[:cut] if cut > 0 else text[:limit]
    return text or None
