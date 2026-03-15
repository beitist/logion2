import re
from .tags import inject_tagged_text
from app.logger import get_logger

logger = get_logger("Assembler")

def _restore_whitespaces(text: str, metadata: dict) -> str:
    if not text or not metadata:
        return text
        
    ws = metadata.get("whitespaces")
    if not ws:
        return text
        
    leading = ws.get("leading", "")
    trailing = ws.get("trailing", "")
    
    if leading:
         text = leading + text.lstrip()
    if trailing:
         text = text.rstrip() + trailing
         
    return text

def _restore_missing_note_tags(target_text: str, source_text: str, tags: dict) -> str:
    """Append footnote/endnote reference tags from source if missing in target.

    After reinitialize, old translations may lack newly-parsed footnote tags.
    Without them the exported DOCX loses its footnote references.
    """
    if not tags or not source_text:
        return target_text
    for tid, tag in tags.items():
        if getattr(tag, 'type', None) not in ('footnote', 'endnote'):
            continue
        tag_pair = f"<{tid}></{tid}>"
        if tag_pair not in (target_text or ""):
            # Find position in source to decide placement
            src_pos = source_text.find(tag_pair)
            if src_pos == -1:
                continue
            # If tag is near end of source, append to target; otherwise prepend
            if src_pos > len(source_text) * 0.5:
                target_text = (target_text or "") + tag_pair
            else:
                target_text = tag_pair + (target_text or "")
    return target_text


def get_merged_content(segs_for_para):
    if not segs_for_para:
        return "", {}
    full_text = ""
    combined_tags = {}

    segs_for_para.sort(key=lambda x: x.metadata.get("sub_index", 0))
    for s in segs_for_para:
        text = s.target_content if s.target_content is not None else s.source_text

        # 1. Restore whitespaces FIRST (so they end up inside wrapper tags)
        text = _restore_whitespaces(text, s.metadata)

        # 2. Ensure footnote/endnote reference tags are present in target
        text = _restore_missing_note_tags(text, s.source_text, s.tags)

        # 3. Restore Wrapper Tags (wraps the content including whitespace)
        wrappers = s.metadata.get("wrapper_tags", [])
        if wrappers:
            for tid in reversed(wrappers):
                text = f"<{tid}>{text}</{tid}>"

        full_text += text
        if s.tags:
            combined_tags.update(s.tags)

    full_text = re.sub(r'</(\d+)><\1>', '', full_text)
    return full_text, combined_tags

def inject_into_container(container, base_metadata, source_segments, shape_map=None):
    # 1. Group by Paragraph
    grouped_segments = {}
    
    for s in source_segments:
        m = s.metadata
        if not m: continue
        
        stype = m.get("type", "body")
        section_idx = m.get("section_index", -1)
        
        t_coords = None
        if m.get("child_type") == "table_cell" or m.get("sub_type") == "table" or stype == "table":
             t_coords = (m.get("table_index"), m.get("row_index"), m.get("cell_index"))
             # Override stype to 'table' for consistent key matching with injection loop
             stype = "table"
             
        p_idx = m.get("p_index") if m.get("p_index") is not None else m.get("index")
            
        key = (stype, section_idx, t_coords, p_idx)
        
        if key not in grouped_segments:
            grouped_segments[key] = []
        grouped_segments[key].append(s)

    stype = base_metadata.get("type")
    s_idx = base_metadata.get("section_index", -1)

    # Paragraphs
    for i, para in enumerate(container.paragraphs):
        key = (stype, s_idx, None, i)
        if key in grouped_segments:
            try:
                text, tags = get_merged_content(grouped_segments[key])
                inject_tagged_text(para, text, tags, shape_map)
            except Exception as e:
                logger.error(f"Error injecting segment {key}: {e}")

    # Tables
    for t_i, table in enumerate(container.tables):
        for r_i, row in enumerate(table.rows):
            # Track seen cells to skip spanned cells (colspan/rowspan)
            # python-docx returns the same cell object for spanned cells
            seen_cells = set()
            for c_i, cell in enumerate(row.cells):
                cell_id = id(cell)  # Unique Python object ID
                if cell_id in seen_cells:
                    continue  # Skip: spanned cell already processed
                seen_cells.add(cell_id)
                
                for p_i, para in enumerate(cell.paragraphs):
                    target_type = stype
                    if stype == "body":
                        target_type = "table"
                    
                    key = (target_type, s_idx, (t_i, r_i, c_i), p_i)
                    if key in grouped_segments:
                        try:
                            text, tags = get_merged_content(grouped_segments[key])
                            inject_tagged_text(para, text, tags, shape_map)
                        except Exception as e:
                            logger.error(f"Error injecting table segment {key}: {e}")
