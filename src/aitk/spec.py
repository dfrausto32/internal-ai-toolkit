"""Parse SPEC.md files — extracts YAML frontmatter and body text."""
from pathlib import Path

import yaml


def parse_spec_text(text: str) -> tuple[dict, str]:
    """Return (meta_dict, body_text) from spec file content.

    If the text begins with a --- frontmatter block, meta is parsed from it
    and body_text is everything after the closing ---. Otherwise meta is {}
    and body_text is the full text.
    """
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            meta = yaml.safe_load(text[4:end]) or {}
            return meta, text[end + 5:].strip()
    return {}, text


def parse_spec(spec_path: str) -> tuple[dict, str]:
    """Return (meta_dict, body_text) from a spec file."""
    return parse_spec_text(Path(spec_path).read_text())
