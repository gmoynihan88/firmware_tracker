from bs4 import BeautifulSoup

from src.scrapers.notes import BLOCKS, elements_of, join_notes, note_lines


def _lines(html, blocks=BLOCKS):
    soup = BeautifulSoup(html, "lxml")
    return note_lines(elements_of(soup.body.find_all(recursive=False)), blocks)


def test_notes_keep_one_line_per_item_with_nested_items_indented():
    html = """
    <h3>Bugfixes:</h3>
    <ul><li>Fixed the following issues with note repeat:
    	<ul><li>Aftertouch of 0 no longer freezes the pressure value.</li></ul></li>
    <li>Compressor's meter shows negative values again.</li></ul>
    """

    assert _lines(html) == [
        "Bugfixes:",
        "- Fixed the following issues with note repeat:",
        "  - Aftertouch of 0 no longer freezes the pressure value.",
        "- Compressor's meter shows negative values again.",
    ]


def test_notes_join_split_words_and_keep_spaces_between_elements():
    """"(t</span><span>o reduce" is one word; "or in </span><a>UAFX" is two."""
    html = (
        '<ul><li><span>Reduced Master (t</span><span>o reduce it, or in </span>'
        '<a href="#"><span><strong>UAFX Control</strong></span></a><span>, Revert)</span></li>'
        '<li>Requires <a href="#"><strong>UAFX Control </strong></a>v3</li></ul>'
    )

    assert _lines(html) == [
        "- Reduced Master (to reduce it, or in UAFX Control, Revert)",
        "- Requires UAFX Control v3",
    ]


def test_notes_keep_a_break_inside_an_item_as_a_line_under_it():
    """As served by Ableton: an item's sub-points separated by <br/>, not a nested list."""
    html = (
        '<ul><li><p data-local-id="54f67c4d1f82">Updated Max 9.1.5 to 3db35fa:<br/>\n'
        "\t- MIDI: improved recovery from bad bytes<br/>\n"
        "\t- Parameters: fixed param visibility getting stuck after saving in Live</p></li></ul>"
        "<p>Note: first line<br>second line</p>"
    )

    assert _lines(html) == [
        "- Updated Max 9.1.5 to 3db35fa:",
        "  - MIDI: improved recovery from bad bytes",
        "  - Parameters: fixed param visibility getting stuck after saving in Live",
        "Note: first line",
        "second line",
    ]


def test_notes_skip_comments_empty_paragraphs_and_paragraphs_inside_items():
    html = """
    <p> </p>
    <ul><li><p>Channel name updates after scene recall</p><!-- ID9999 - draft entry --></li></ul>
    <p></p>
    """

    assert _lines(html) == ["- Channel name updates after scene recall"]


def test_notes_indent_only_relative_to_the_items_given():
    """A notes block inside a page's own list item is not indented for it."""
    soup = BeautifulSoup(
        '<ul class="page"><li><div class="card-body"><ul><li>New</li></ul></div></li></ul>', "lxml"
    )
    body = soup.select_one("div.card-body")

    assert note_lines(body.descendants) == ["- New"]


def test_notes_can_leave_out_the_article_s_own_headings():
    html = "<h2>Previous Versions</h2><h3>Fixes</h3><p>ID1 - Fixed</p>"

    assert _lines(html, blocks=("p", "h3", "li")) == ["Fixes", "ID1 - Fixed"]


def test_join_notes_caps_the_text_and_reports_nothing_as_none():
    assert join_notes(["a", "b"]) == "a\nb"
    assert join_notes([]) is None
    # One line longer than the limit has nowhere to break.
    assert join_notes(["x" * 5000]) == "x" * 4000


def test_join_notes_cuts_at_the_last_whole_line():
    """Live 11's 11.0 notes run to 54,791 characters; a cut mid-sentence reads as a bug."""
    lines = ["- " + "a" * 1988, "- " + "b" * 1988, "- " + "c" * 1988]

    assert join_notes(lines) == lines[0] + "\n" + lines[1]
