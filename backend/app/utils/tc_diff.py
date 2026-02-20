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


def convert_ai_tc_to_tiptap(
    ai_output: str,
    author_id: str = "mt",
    author_name: str = "MT",
    date: str = ""
) -> str:
    """
    Convert AI-generated <ins>/<del> markup to TipTap-compatible
    <insert>/<delete> elements with track-change-extension attributes.

    The AI produces simpler <ins>/<del> tags; this adds the required
    data-op-user-id, data-op-user-nickname, data-op-date attributes.
    """
    if not date:
        date = datetime.utcnow().strftime("%Y-%m-%d %H:%M")

    author_id_safe = _escape_attr(author_id)
    author_name_safe = _escape_attr(author_name)
    date_safe = _escape_attr(date)

    attrs = (
        f'data-op-user-id="{author_id_safe}" '
        f'data-op-user-nickname="{author_name_safe}" '
        f'data-op-date="{date_safe}"'
    )

    result = ai_output
    # <ins>...</ins> → <insert ...>...</insert>
    result = re.sub(r'<ins>(.*?)</ins>', rf'<insert {attrs}>\1</insert>', result)
    # <del>...</del> → <delete ...>...</delete>
    result = re.sub(r'<del>(.*?)</del>', rf'<delete {attrs}>\1</delete>', result)
    return result


def extract_clean_from_tc(ai_output: str) -> str:
    """
    Extract clean text from AI TC markup.
    Removes <del>...</del> entirely, strips <ins> tags (keeps content).

    Example: "The <del>big</del> <ins>large</ins> dog" → "The large dog"

    The result is used as TM-chain base for the next stage.
    """
    # Remove <del>...</del> blocks entirely
    result = re.sub(r'<del>.*?</del>', '', ai_output)
    # Strip <ins> tags but keep content
    result = re.sub(r'<ins>(.*?)</ins>', r'\1', result)
    # Normalize whitespace (collapsed doubles from removed dels)
    result = re.sub(r'  +', ' ', result).strip()
    return result


def validate_ai_tc_markup(ai_output: str) -> bool:
    """
    Check if AI-generated TC markup has balanced <ins>/<del> tags.
    Returns True if valid, False if malformed (triggers fallback to word-level diff).

    Also returns True if there are no tags at all (unchanged text).
    """
    ins_opens = len(re.findall(r'<ins>', ai_output))
    ins_closes = len(re.findall(r'</ins>', ai_output))
    del_opens = len(re.findall(r'<del>', ai_output))
    del_closes = len(re.findall(r'</del>', ai_output))

    if ins_opens != ins_closes or del_opens != del_closes:
        return False

    # Check for nesting (not supported): <ins> inside <del> or vice versa
    # Simple check: no tag should appear between an open and close of the other
    for pattern in [r'<ins>[^<]*<del>', r'<del>[^<]*<ins>']:
        if re.search(pattern, ai_output):
            return False

    return True


# ── Accumulation: build multi-author TC document from clean texts ─────

def accumulate_tc_stages(
    base_text: str,
    stage_clean_texts: list,
    stage_authors: list,
) -> str:
    """
    Build an accumulated TC document from a clean base text and per-stage
    clean translations.  Uses word-level diffs (same tokenizer as
    generate_tc_markup) to determine changes between consecutive stages.

    base_text:         clean base translation (no markup)
    stage_clean_texts: ordered list of clean texts, one per stage after base
    stage_authors:     [(author_id, author_name, date), ...] matching stages

    Returns TipTap HTML with multi-author <insert>/<delete> marks.
    Overlapping changes produce nested marks:
        <delete B><insert A>text</insert></delete>
    """
    if not stage_clean_texts:
        return base_text

    # Internal: list of (text, marks) tuples
    # marks = [("insert"|"delete", attrs_string), ...]
    fragments = [(base_text, [])]
    prev_clean = base_text

    for clean_text, (a_id, a_name, a_date) in zip(stage_clean_texts, stage_authors):
        if not clean_text or clean_text == prev_clean:
            continue

        attrs = _make_attrs(a_id, a_name, a_date)

        # Word-level diff → consume ops
        old_tokens = _tokenize(prev_clean)
        new_tokens = _tokenize(clean_text)
        sm = difflib.SequenceMatcher(None, old_tokens, new_tokens)

        ops = []
        for opcode, i1, i2, j1, j2 in sm.get_opcodes():
            old_chunk = "".join(old_tokens[i1:i2])
            new_chunk = "".join(new_tokens[j1:j2])
            if opcode == "equal":
                ops.append(("keep", old_chunk, ""))
            elif opcode == "replace":
                ops.append(("delete", old_chunk, attrs))
                ops.append(("insert", new_chunk, attrs))
            elif opcode == "delete":
                ops.append(("delete", old_chunk, attrs))
            elif opcode == "insert":
                ops.append(("insert", new_chunk, attrs))

        fragments = _apply_consume_ops(fragments, ops)
        prev_clean = clean_text

    return _serialize_fragments(fragments)


def _make_attrs(author_id: str, author_name: str, date: str) -> str:
    """Build data-op attribute string for TipTap TC elements."""
    if not date:
        date = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    return (
        f'data-op-user-id="{_escape_attr(author_id)}" '
        f'data-op-user-nickname="{_escape_attr(author_name)}" '
        f'data-op-date="{_escape_attr(date)}"'
    )


def _apply_consume_ops(fragments: list, ops: list) -> list:
    """
    Apply keep/delete/insert ops to the fragment list by consuming
    visible text in order.  Invisible (already-deleted) fragments are
    passed through unchanged, preserving physical document order.
    """
    new_frags = []
    frag_idx = 0
    frag_offset = 0

    def _is_visible(marks):
        return not any(m[0] == "delete" for m in marks)

    def consume(length, add_mark=None):
        nonlocal frag_idx, frag_offset
        remaining = length
        pieces = []

        while remaining > 0 and frag_idx < len(fragments):
            text, marks = fragments[frag_idx]

            # Pass through invisible (deleted) fragments
            if not _is_visible(marks):
                pieces.append((text, list(marks)))
                frag_idx += 1
                frag_offset = 0
                continue

            available = len(text) - frag_offset
            take = min(remaining, available)

            piece_text = text[frag_offset:frag_offset + take]
            piece_marks = list(marks)
            if add_mark:
                piece_marks.append(add_mark)

            pieces.append((piece_text, piece_marks))
            remaining -= take
            frag_offset += take

            if frag_offset >= len(text):
                frag_idx += 1
                frag_offset = 0

        return pieces

    for op_type, text, attrs in ops:
        if op_type == "keep":
            new_frags.extend(consume(len(text)))
        elif op_type == "delete":
            new_frags.extend(
                consume(len(text), add_mark=("delete", attrs))
            )
        elif op_type == "insert":
            new_frags.append((text, [("insert", attrs)]))

    # Emit remaining fragments (trailing invisible)
    while frag_idx < len(fragments):
        text, marks = fragments[frag_idx]
        if frag_offset > 0:
            text = text[frag_offset:]
            frag_offset = 0
        if text:
            new_frags.append((text, list(marks)))
        frag_idx += 1

    return new_frags


def _serialize_fragments(fragments: list) -> str:
    """
    Convert fragment list to TipTap HTML.
    Nesting order: insert (inner) then delete (outer).
    """
    parts = []
    for text, marks in fragments:
        if not text:
            continue
        html = text
        for mtype, attrs in marks:
            if mtype == "insert":
                html = f"<insert {attrs}>{html}</insert>"
        for mtype, attrs in marks:
            if mtype == "delete":
                html = f"<delete {attrs}>{html}</delete>"
        parts.append(html)
    return "".join(parts)


def _escape_attr(value: str) -> str:
    """Escape a string for use in an HTML attribute value."""
    return (
        value
        .replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
