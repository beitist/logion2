import re
import uuid
from datetime import datetime
from docx.oxml.ns import qn
from app.schemas import SegmentInternal, TagModel
from ..utils import split_sentences
from .extract import (
    process_run_element,
    is_pure_text_run,
    get_run_signature,
    get_run_text
)


class InlineProcessingState:
    """
    Shared mutable state for inline content processing within a single paragraph.
    Holds the tag registry and context, shared across recursive calls
    (e.g. hyperlinks containing runs, w:ins/w:del track changes).
    """
    def __init__(self, context: dict):
        self.tags = {}          # tid -> TagModel
        self.next_tag_id = 1
        self.context = context  # comments_map, extra_segments, etc.
        # Track Changes
        self.has_track_changes = False
        self._text_fragments = []   # [{text, type, author, date}, ...] for stage reconstruction
        self.revision_events = []   # [{type, text, author, date}, ...]

    def add_tag(self, tag_model: TagModel) -> str:
        tid = str(self.next_tag_id)
        self.next_tag_id += 1
        self.tags[tid] = tag_model
        return tid


def _strip_tags(text: str) -> str:
    """Remove custom XML tags like <1>, </2> from text, leaving only plain content."""
    return re.sub(r'</?(\d+)>', '', text)


def process_inline_children(elements, state: InlineProcessingState,
                            _inside_ins=False, _inside_del=False,
                            _revision_info=None) -> str:
    """
    Processes a sequence of inline XML elements (w:r, w:hyperlink, w:ins, w:del, ...).

    Called for:
      - Paragraph children (main case)
      - Hyperlink children (w:r inside w:hyperlink)
      - w:ins/w:del children (track changes)

    Run buffering is local to each invocation — runs are not merged across
    structural boundaries (hyperlinks, track changes, etc.).

    _inside_ins/_inside_del track nesting context for dual-text reconstruction:
      - Normal run: text → final content + original text
      - Inside w:ins: text → final content only (not in original)
      - Inside w:del: text → original text only (not in final)
      - Nested (e.g. del-inside-ins): text → neither

    _revision_info: dict with {type, author, date} of the enclosing w:ins/w:del,
      used for recording text fragments with their revision context.

    Returns the accumulated tagged-text string.
    """
    run_buffer = []
    buffer_signature = None
    content = ""

    def flush_run_buffer():
        nonlocal buffer_signature, content
        if not run_buffer:
            return

        # Record text fragments for revision stage reconstruction
        if not (_inside_ins and _inside_del):
            for r in run_buffer:
                plain = get_run_text(r)
                if plain:
                    if _revision_info:
                        state._text_fragments.append({
                            'text': plain,
                            'type': _revision_info['type'],
                            'author': _revision_info['author'],
                            'date': _revision_info['date'],
                        })
                    else:
                        state._text_fragments.append({
                            'text': plain, 'type': 'normal',
                            'author': '', 'date': '',
                        })

        # Optimization: Merge consecutive runs with identical formatting signature
        if len(run_buffer) > 1 and all(is_pure_text_run(r) for r in run_buffer):
            merged_text = ""
            for r in run_buffer:
                merged_text += get_run_text(r)
            content += process_run_element(
                run_buffer[0], add_tag_func=state.add_tag,
                context=state.context, process_para_func=process_paragraph,
                text_override=merged_text
            )
        else:
            for r in run_buffer:
                content += process_run_element(
                    r, add_tag_func=state.add_tag,
                    context=state.context, process_para_func=process_paragraph
                )

        run_buffer.clear()
        buffer_signature = None

    for child in elements:
        if child.tag == qn('w:r'):
            sig = get_run_signature(child)
            if sig != buffer_signature or not is_pure_text_run(child):
                flush_run_buffer()
                buffer_signature = sig
            run_buffer.append(child)

        elif child.tag == qn('w:ins'):
            flush_run_buffer()
            author = child.get(qn('w:author'), '')
            date_str = child.get(qn('w:date'), '')
            # Use outermost revision info (don't override if already nested)
            rev_info = _revision_info if _revision_info else {
                'type': 'ins', 'author': author, 'date': date_str
            }
            ins_text = process_inline_children(
                child, state, _inside_ins=True, _inside_del=_inside_del,
                _revision_info=rev_info
            )
            content += ins_text
            # Record revision event (only for non-empty text changes)
            plain_ins = _strip_tags(ins_text)
            if plain_ins.strip():
                state.has_track_changes = True
                state.revision_events.append({
                    'type': 'insertion',
                    'text': plain_ins.strip(),
                    'author': author,
                    'date': date_str,
                })

        elif child.tag == qn('w:del'):
            flush_run_buffer()
            author = child.get(qn('w:author'), '')
            date_str = child.get(qn('w:date'), '')
            rev_info = _revision_info if _revision_info else {
                'type': 'del', 'author': author, 'date': date_str
            }
            del_text = process_inline_children(
                child, state, _inside_ins=_inside_ins, _inside_del=True,
                _revision_info=rev_info
            )
            # del_text is NOT added to content (removed from final)
            plain_del = _strip_tags(del_text)
            if plain_del.strip():
                state.has_track_changes = True
                state.revision_events.append({
                    'type': 'deletion',
                    'text': plain_del.strip(),
                    'author': author,
                    'date': date_str,
                })

        elif child.tag == qn('w:hyperlink'):
            flush_run_buffer()
            rid = child.get(qn('r:id'))
            l_tag = TagModel(type="link", xml_attributes={"rid": rid})
            l_tid = state.add_tag(l_tag)
            content += f"<{l_tid}>"
            content += process_inline_children(
                child, state, _inside_ins=_inside_ins, _inside_del=_inside_del,
                _revision_info=_revision_info
            )
            content += f"</{l_tid}>"

        elif child.tag == qn('w:bookmarkStart') or child.tag == qn('w:bookmarkEnd'):
            pass

        else:
            # Other elements (math, smarttag, etc.)
            flush_run_buffer()

    flush_run_buffer()
    return content


def repair_tags(segments: list[str]) -> list[str]:
    """
    Ensures that if a segment ends with open tags, they are closed,
    and reopened in the next segment.
    """
    repaired = []
    stack = []
    pattern = re.compile(r'<(/?(\d+))>')

    for part in segments:
        prefix = "".join([f"<{tid}>" for tid in stack])
        current_seg = prefix + part

        for m in pattern.finditer(part):
            full_tag = m.group(1)
            tid = m.group(2)
            is_close = full_tag.startswith("/")

            if is_close:
                if stack and stack[-1] == tid:
                    stack.pop()
            else:
                stack.append(tid)

        suffix = "".join([f"</{tid}>" for tid in reversed(stack)])
        current_seg = current_seg + suffix

        repaired.append(current_seg)

    return repaired

def strip_wrapping_tags(source_text: str, tags: dict) -> tuple[str, dict, list]:
    """
    Cleans up tag patterns in segment text:
    1. Removes outer wrapping tags: '<1><2>text</2></1>' -> 'text'
    2. Removes empty tag pairs: '<N></N>' -> ''
    3. Removes whitespace-only tag pairs: '<N>\\n</N>' or '<N> </N>' -> '' (or keeps whitespace)

    Formatting tags (bold, italic, highlight, etc.) that wrap the entire content
    are stripped from the text but their IDs are collected in wrapper_tag_ids.
    Their TagModels are KEPT in the tags dict so the assembler can re-apply them
    during export via the wrapper_tags metadata field.

    Returns: (cleaned_text, cleaned_tags, wrapper_tag_ids)
    """
    # Tag types that must survive round-tripping when they wrap an entire segment.
    # Formatting tags preserve visual appearance, comment/shape preserve structure.
    # If one of these wraps an entire segment it is stripped from the display text
    # but preserved so it can be re-applied at export time.
    PRESERVE_TYPES = {
        # Visual formatting
        'bold', 'italic', 'underline', 'highlight', 'color',
        'size', 'font', 'strike', 'smallCaps', 'caps',
        'superscript', 'subscript',
        # Structural elements that carry content/annotation
        'comment', 'shape', 'link',
        # Reference elements (must round-trip to preserve footnote/endnote anchors)
        'footnote', 'endnote',
    }

    if not source_text:
        return source_text, tags or {}, []

    new_tags = dict(tags) if tags else {}
    text = source_text
    wrapper_tag_ids = []  # IDs of stripped formatting tags (outermost first)

    changed = True
    while changed:
        changed = False
        text_before = text

        # 1. Remove empty tag pairs: <N></N> (including groups like <1><2></2></1>)
        # BUT preserve footnote/endnote reference tags — they are structurally
        # important and must survive for export, even though they carry no text.
        def _remove_empty_pair(m):
            tid = m.group(1)
            tag_data = new_tags.get(tid)
            if tag_data:
                ttype = tag_data.type if hasattr(tag_data, 'type') else tag_data.get('type', '')
                if ttype in ('footnote', 'endnote'):
                    return m.group(0)  # keep
            return ''  # remove
        text = re.sub(r'<(\d+)></\1>', _remove_empty_pair, text)

        # 2. Remove whitespace-only tag pairs: <N>whitespace</N>
        # This removes tags that only contain spaces, newlines, nbsp, etc.
        # Also preserves footnote/endnote reference tags (same logic as above).
        text = re.sub(r'<(\d+)>[\s\xa0]*</\1>', _remove_empty_pair, text)

        # 3. Peel off outer wrapping tags if they encompass entire content
        # Use stripped version for matching, but preserve whitespace in result
        text_stripped = text.strip()
        match = re.match(r'^<(\d+)>(.*)</\1>$', text_stripped, re.DOTALL)
        if match:
            tag_id = match.group(1)
            inner = match.group(2)  # Don't strip inner - preserve whitespace
            tag_data = new_tags.get(tag_id)

            # Determine tag type to decide whether to preserve for export
            tag_type = ''
            if tag_data:
                tag_type = tag_data.type if hasattr(tag_data, 'type') else tag_data.get('type', '')

            if tag_type in PRESERVE_TYPES:
                # Formatting tag: strip from text but KEEP in tags dict
                # and record the ID so it can be re-wrapped during export
                text = inner
                wrapper_tag_ids.append(tag_id)
                # Do NOT delete from new_tags — the assembler needs the TagModel
            else:
                # Non-formatting tag (link, shape, comment, etc.): fully remove
                text = inner
                if tag_id in new_tags:
                    del new_tags[tag_id]
            changed = True

        # Check if anything changed in this iteration
        if text != text_before:
            changed = True

    # Final cleanup: filter tags dict to only keep tags that still appear in text
    # OR are referenced by wrapper_tag_ids (needed for export re-wrapping)
    tag_ids_in_text = set(re.findall(r'<(\d+)>', text))
    wrapper_set = set(wrapper_tag_ids)
    new_tags = {k: v for k, v in new_tags.items() if k in tag_ids_in_text or k in wrapper_set}

    return text, new_tags, wrapper_tag_ids

def get_tag_signature(tag_data) -> tuple:
    """
    Creates a hashable signature for a tag to compare identity.
    Two tags with the same signature have identical formatting.
    Handles both dict and TagModel objects.
    """
    # Handle both dict and TagModel objects
    if hasattr(tag_data, 'type'):
        # TagModel object
        tag_type = tag_data.type or ''
        attrs = tag_data.xml_attributes or {}
    else:
        # Dictionary
        tag_type = tag_data.get('type', '')
        attrs = tag_data.get('xml_attributes', {})

    # Sort attributes for consistent comparison
    sorted_attrs = tuple(sorted(attrs.items())) if attrs else ()
    return (tag_type, sorted_attrs)

def merge_adjacent_tags(source_text: str, tags: dict) -> tuple[str, dict]:
    """
    Merges adjacent tags that have identical formatting.
    E.g. '<7>Please d</7><8>escribe</8>' -> '<7>Please describe</7>'
         (if tag 7 and 8 have same type/attrs)

    Returns cleaned text and updated tags dict.
    """
    if not source_text or not tags:
        return source_text, tags or {}

    # Build signature lookup for all tags
    tag_signatures = {tid: get_tag_signature(t) for tid, t in tags.items()}

    # Pattern to find tag pairs: </N><M> where N closes and M opens
    # We want to merge if they have the same signature
    pattern = re.compile(r'</(\d+)><(\d+)>')

    new_tags = dict(tags)
    text = source_text
    changed = True

    while changed:
        changed = False
        match = pattern.search(text)
        if match:
            closing_tid = match.group(1)
            opening_tid = match.group(2)

            # Check if both tags exist and have the same signature
            if closing_tid in tag_signatures and opening_tid in tag_signatures:
                sig1 = tag_signatures[closing_tid]
                sig2 = tag_signatures[opening_tid]

                if sig1 == sig2:
                    # Same formatting - remove the close/open pair
                    # </7><8> gets removed, content flows together
                    # Also need to replace </8> with </7> at the end
                    text = text[:match.start()] + text[match.end():]

                    # Replace closing tag of the merged one
                    text = text.replace(f'</{opening_tid}>', f'</{closing_tid}>', 1)

                    # Remove the now-unused tag from our dict
                    if opening_tid in new_tags:
                        del new_tags[opening_tid]
                    if opening_tid in tag_signatures:
                        del tag_signatures[opening_tid]

                    changed = True

    return text, new_tags

def _parse_datetime(date_str: str):
    """Parse ISO 8601 datetime from Word XML (e.g. '2024-01-15T10:00:00Z')."""
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.rstrip('Z'))
    except (ValueError, TypeError):
        return None


def _cluster_revisions(fragments: list) -> list:
    """
    Groups revision fragments by author + time proximity (<5 min).
    Returns sorted list of cluster dicts:
      [{stage, author, date, rev_keys: set((author, date))}]
    """
    # Collect unique (author, date) revision pairs
    rev_pairs = {}
    for f in fragments:
        if f['type'] != 'normal':
            key = (f['author'], f['date'])
            if key not in rev_pairs:
                dt = _parse_datetime(f['date'])
                if dt:
                    rev_pairs[key] = dt

    if not rev_pairs:
        return []

    sorted_pairs = sorted(rev_pairs.items(), key=lambda x: x[1])

    # Cluster: same author + gap < 5 minutes
    GAP_SECONDS = 300
    clusters = []
    cur_keys = {sorted_pairs[0][0]}
    cur_author = sorted_pairs[0][0][0]
    cur_time = sorted_pairs[0][1]
    cur_first_date = sorted_pairs[0][0][1]

    for (author, date_str), dt in sorted_pairs[1:]:
        gap = abs((dt - cur_time).total_seconds())
        if author == cur_author and gap < GAP_SECONDS:
            cur_keys.add((author, date_str))
            cur_time = dt
        else:
            clusters.append({
                'author': cur_author, 'date': cur_first_date,
                'rev_keys': cur_keys,
            })
            cur_keys = {(author, date_str)}
            cur_author = author
            cur_time = dt
            cur_first_date = date_str

    clusters.append({
        'author': cur_author, 'date': cur_first_date,
        'rev_keys': cur_keys,
    })

    for i, c in enumerate(clusters):
        c['stage'] = i + 1

    return clusters


def _build_stage_texts(fragments: list, clusters: list) -> list:
    """
    Builds the plain text at each revision stage.

    Stage 0 = original (before any changes)
    Stage N = after applying all revisions in clusters 1..N

    Text at stage N includes:
      - All normal (non-revision) text
      - Insertions from stages <= N
      - Deletions from stages > N (not yet deleted)

    Returns list of {stage, author, date, text}.
    """
    if not clusters:
        return []

    rev_to_stage = {}
    for cluster in clusters:
        for key in cluster['rev_keys']:
            rev_to_stage[key] = cluster['stage']

    max_stage = clusters[-1]['stage']
    results = []

    for stage_n in range(0, max_stage + 1):
        text = ""
        for f in fragments:
            if f['type'] == 'normal':
                text += f['text']
            elif f['type'] == 'ins':
                frag_stage = rev_to_stage.get((f['author'], f['date']))
                if frag_stage is not None and frag_stage <= stage_n:
                    text += f['text']
            elif f['type'] == 'del':
                frag_stage = rev_to_stage.get((f['author'], f['date']))
                if frag_stage is not None and frag_stage > stage_n:
                    text += f['text']

        if stage_n == 0:
            results.append({
                'stage': 0, 'author': '', 'date': '',
                'text': text.strip(),
            })
        else:
            cluster = clusters[stage_n - 1]
            results.append({
                'stage': stage_n, 'author': cluster['author'],
                'date': cluster['date'], 'text': text.strip(),
            })

    return results


def process_paragraph(para_element, location: dict, context: dict) -> list[SegmentInternal]:
    """
    Converts a docx Paragraph XML ELEMENT into a SegmentInternal list.
    """

    # Check for skipping (e.g. ToC)
    pStyle = para_element.find(qn('w:pStyle'))
    if pStyle is not None:
        style_val = pStyle.get(qn('w:val'))
        # Skip TOC
        if style_val and ('toc' in style_val.lower() or 'table of contents' in style_val.lower()):
            return []

    # Process inline children via shared state
    state = InlineProcessingState(context)
    final_content = process_inline_children(para_element, state)
    tags = state.tags

    if not final_content.strip() and not ("[SHAPE]" in final_content):
        return []

    # Track Changes: build revision stages from text fragments
    if state.has_track_changes and state._text_fragments:
        # Derive original/final from fragments
        original_plain = ''.join(
            f['text'] for f in state._text_fragments if f['type'] in ('normal', 'del')
        ).strip()
        final_plain = ''.join(
            f['text'] for f in state._text_fragments if f['type'] in ('normal', 'ins')
        ).strip()

        if original_plain != final_plain:
            location['has_track_changes'] = True
            location['original_text'] = original_plain
            location['final_text'] = final_plain
            location['revisions'] = state.revision_events

            # Build revision stages for Git-Slider UI
            clusters = _cluster_revisions(state._text_fragments)
            if clusters:
                stages = _build_stage_texts(state._text_fragments, clusters)
                if len(stages) >= 2:
                    location['revision_stages'] = stages

    # Pre-strip: extract outer whitespace for empty-check, but per-segment
    # whitespace is extracted AFTER tag-stripping (see below) so that spaces
    # hidden inside wrapper tags are correctly captured.
    clean_content = final_content.strip()
    if not clean_content:
         if not "[SHAPE]" in final_content:
             return []

    # Segmentation — skip sentence splitting for TC paragraphs to avoid
    # duplicating full-paragraph revision_stages across sub-segments.
    if location.get('has_track_changes'):
        parts = [clean_content]
    else:
        parts = split_sentences(clean_content)

    # Merge orphan tag-only parts (e.g. "<1></1>") back into the previous segment.
    # pysbd sometimes splits footnote/endnote reference tags into their own segment.
    _tag_only_re = re.compile(r'^[\s]*(?:<\d+></\d+>[\s]*)+$')
    merged_parts = []
    for p in parts:
        if _tag_only_re.match(p) and merged_parts:
            merged_parts[-1] += p
        else:
            merged_parts.append(p)
    parts = merged_parts
    repaired_parts = repair_tags(parts)

    final_segments = []
    num_parts = len(repaired_parts)

    for i, part in enumerate(repaired_parts):
        seg_loc = location.copy()
        seg_loc['sub_index'] = i

        # Strip wrapping tags that encompass entire segment.
        clean_part, clean_tags, wrapper_tag_ids = strip_wrapping_tags(part, tags)

        # Merge adjacent tags with identical formatting
        clean_part, clean_tags = merge_adjacent_tags(clean_part, clean_tags)

        # Store wrapper tag IDs in metadata for the export assembler
        if wrapper_tag_ids:
            seg_loc['wrapper_tags'] = wrapper_tag_ids

        # Whitespace Handling (Preservation)
        # Extract AFTER tag-stripping so that spaces originally inside wrapper
        # tags (e.g. '<1>Text </1>' → 'Text ') are correctly detected.
        # For multi-sentence paragraphs: leading ws on first segment,
        # trailing ws on last segment, inner segments get per-part ws only.
        leading_ws = ""
        trailing_ws = ""

        # Per-part whitespace (spaces exposed after tag stripping)
        match_leading = re.match(r'^(\s+)', clean_part)
        if match_leading:
            leading_ws = match_leading.group(1)

        match_trailing = re.search(r'(\s+)$', clean_part)
        if match_trailing:
            trailing_ws = match_trailing.group(1)

        # Paragraph-level outer whitespace: only first/last segment
        if i == 0:
            outer_leading = re.match(r'^(\s+)', final_content)
            if outer_leading:
                # Use outer leading if it's longer (covers both inner + outer)
                if len(outer_leading.group(1)) > len(leading_ws):
                    leading_ws = outer_leading.group(1)

        if i == num_parts - 1:
            outer_trailing = re.search(r'(\s+)$', final_content)
            if outer_trailing:
                if len(outer_trailing.group(1)) > len(trailing_ws):
                    trailing_ws = outer_trailing.group(1)

        ws_meta = {}
        if leading_ws: ws_meta['leading'] = leading_ws
        if trailing_ws: ws_meta['trailing'] = trailing_ws
        seg_loc['whitespaces'] = ws_meta

        # Strip the whitespace from the stored text (editor works without it)
        clean_part = clean_part.strip()

        final_segments.append(SegmentInternal(
            id=str(uuid.uuid4()),
            segment_id=str(uuid.uuid4()),
            source_text=clean_part,
            target_content=None,
            status="draft",
            tags=clean_tags,
            metadata=seg_loc
        ))

    return final_segments

def process_container(container, base_metadata: dict, context: dict):
    """
    Iterates over a container's paragraphs and tables IN DOCUMENT ORDER.
    Uses XML-level iteration for Document body, falls back to python-docx API for cells.
    """
    all_segments = []

    # Namespaces for Word XML
    w_ns = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'

    # Get the XML element
    body_element = container._element if hasattr(container, '_element') else getattr(container, 'element', None)

    # Check if this is a document body (has w:body wrapper) or a cell/other container
    # Document body needs special handling for correct order
    is_document_body = hasattr(container, 'sections')  # Only Document has sections

    if is_document_body and body_element is not None:
        # Find the actual w:body element
        body_el = body_element.find(f'{w_ns}body')
        if body_el is None:
            body_el = body_element  # Fallback to element itself

        p_index = 0
        t_index = 0

        for child in body_el:
            tag = child.tag

            if tag == f'{w_ns}p':
                meta = base_metadata.copy()
                meta['p_index'] = p_index
                segs = process_paragraph(child, meta, context)
                all_segments.extend(segs)
                p_index += 1

            elif tag == f'{w_ns}tbl':
                from docx.table import Table
                table = Table(child, container)

                for r_i, row in enumerate(table.rows):
                    seen_cells = set()
                    for c_i, cell in enumerate(row.cells):
                        cell_id = id(cell)
                        if cell_id in seen_cells:
                            continue
                        seen_cells.add(cell_id)

                        cell_meta = base_metadata.copy()
                        cell_meta['child_type'] = 'table_cell'
                        cell_meta['table_index'] = t_index
                        cell_meta['row_index'] = r_i
                        cell_meta['cell_index'] = c_i

                        cell_segs = process_container(cell, cell_meta, context)
                        all_segments.extend(cell_segs)

                t_index += 1
    else:
        # For cells and other containers, use python-docx API (simpler, works reliably)
        # Paragraphs first
        for i, para in enumerate(container.paragraphs):
            meta = base_metadata.copy()
            meta['p_index'] = i
            segs = process_paragraph(para._element, meta, context)
            all_segments.extend(segs)

        # Then tables (cells can have nested tables)
        for t_i, table in enumerate(container.tables):
            for r_i, row in enumerate(table.rows):
                seen_cells = set()
                for c_i, cell in enumerate(row.cells):
                    cell_id = id(cell)
                    if cell_id in seen_cells:
                        continue
                    seen_cells.add(cell_id)

                    cell_meta = base_metadata.copy()
                    cell_meta['child_type'] = 'table_cell'
                    cell_meta['table_index'] = t_i
                    cell_meta['row_index'] = r_i
                    cell_meta['cell_index'] = c_i

                    cell_segs = process_container(cell, cell_meta, context)
                    all_segments.extend(cell_segs)

    return all_segments
