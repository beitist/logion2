"""
Track Changes Diff Utility

Generates <insert> and <delete> HTML markup from word-level diffs
between two translation strings. Compatible with the tiptap
track-change-extension (InsertionMark / DeletionMark).
"""

import difflib
import re
from datetime import datetime


def generate_tc_markup(
    old_text: str,
    new_text: str,
    author_id: str = "mt",
    author_name: str = "MT",
    date: str = ""
) -> str:
    """
    Diffs old_text vs new_text at word level and wraps changes
    in <insert>/<delete> elements with track-change-extension attributes.

    Returns HTML string that TipTap can parse into InsertionMark/DeletionMark.
    """
    if not date:
        date = datetime.utcnow().strftime("%Y-%m-%d %H:%M")

    # Escape author values for HTML attributes
    author_id_safe = _escape_attr(author_id)
    author_name_safe = _escape_attr(author_name)
    date_safe = _escape_attr(date)

    attrs = (
        f'data-op-user-id="{author_id_safe}" '
        f'data-op-user-nickname="{author_name_safe}" '
        f'data-op-date="{date_safe}"'
    )

    # Tokenize preserving whitespace structure
    old_tokens = _tokenize(old_text)
    new_tokens = _tokenize(new_text)

    sm = difflib.SequenceMatcher(None, old_tokens, new_tokens)
    parts = []

    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            parts.append("".join(old_tokens[i1:i2]))
        elif op == "replace":
            old_chunk = "".join(old_tokens[i1:i2])
            new_chunk = "".join(new_tokens[j1:j2])
            parts.append(f"<delete {attrs}>{old_chunk}</delete>")
            parts.append(f"<insert {attrs}>{new_chunk}</insert>")
        elif op == "insert":
            new_chunk = "".join(new_tokens[j1:j2])
            parts.append(f"<insert {attrs}>{new_chunk}</insert>")
        elif op == "delete":
            old_chunk = "".join(old_tokens[i1:i2])
            parts.append(f"<delete {attrs}>{old_chunk}</delete>")

    return "".join(parts)


def _tokenize(text: str) -> list:
    """
    Split text into tokens where each token is either a word or whitespace.
    This preserves whitespace structure through the diff.
    """
    return re.findall(r'\S+|\s+', text)


def _escape_attr(value: str) -> str:
    """Escape a string for use in an HTML attribute value."""
    return (
        value
        .replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
