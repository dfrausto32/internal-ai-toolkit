"""Apply SEARCH/REPLACE edit blocks to existing code.

Retries ask the model for the smallest fix instead of a full rewrite. The model replies with
blocks in this format, and `apply_edits` applies them only if every block matches exactly once:

    <<<<<<< SEARCH
    <existing lines, verbatim>
    =======
    <replacement lines>
    >>>>>>> REPLACE

Any block that doesn't apply cleanly makes the whole patch fail (returns None) so the caller can
fall back to a full rewrite — a half-applied patch is worse than none.
"""
import re

_BLOCK = re.compile(r"<<<<<<< SEARCH\n(.*?)\n=======\n(.*?)\n?>>>>>>> REPLACE", re.DOTALL)


def apply_edits(code: str, response: str) -> str | None:
    """Return `code` with every edit block applied, or None if any block fails to apply."""
    blocks = _BLOCK.findall(response)
    if not blocks:
        return None
    for search, replace in blocks:
        if not search.strip() or code.count(search) != 1:
            return None
        code = code.replace(search, replace, 1)
    return code
