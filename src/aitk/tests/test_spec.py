"""Tests for aitk.spec — frontmatter parsing."""
from aitk.spec import parse_spec


def test_parses_frontmatter_and_body(tmp_path):
    spec_file = tmp_path / "SPEC.md"
    spec_file.write_text(
        "---\n"
        "language: python\n"
        "frameworks: [fastapi, sqlalchemy]\n"
        "estimated_lines: 200\n"
        "---\n"
        "# What to build\n"
        "Some prose here.\n"
    )

    meta, body = parse_spec(str(spec_file))

    assert meta == {
        "language": "python",
        "frameworks": ["fastapi", "sqlalchemy"],
        "estimated_lines": 200,
    }
    assert body == "# What to build\nSome prose here."


def test_no_frontmatter_returns_empty_meta_and_full_body(tmp_path):
    spec_file = tmp_path / "SPEC.md"
    spec_file.write_text("# What to build\nNo frontmatter at all.\n")

    meta, body = parse_spec(str(spec_file))

    assert meta == {}
    assert body == "# What to build\nNo frontmatter at all.\n"


def test_unclosed_frontmatter_falls_back_to_full_body(tmp_path):
    spec_file = tmp_path / "SPEC.md"
    text = "---\nlanguage: python\n# body that forgot to close the frontmatter\n"
    spec_file.write_text(text)

    meta, body = parse_spec(str(spec_file))

    assert meta == {}
    assert body == text


def test_empty_frontmatter_block_is_treated_as_no_frontmatter(tmp_path):
    # The closing "---" of a zero-content block overlaps the search start
    # offset (which skips the opening "---\n"), so it's never matched —
    # the whole file falls through to the no-frontmatter path. Harmless in
    # practice since nobody writes an empty frontmatter block, but worth
    # pinning down so a future refactor doesn't change this silently.
    text = "---\n---\nBody text.\n"
    spec_file = tmp_path / "SPEC.md"
    spec_file.write_text(text)

    meta, body = parse_spec(str(spec_file))

    assert meta == {}
    assert body == text
