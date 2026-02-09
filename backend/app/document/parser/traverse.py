import re
import uuid
from docx.oxml.ns import qn
from app.schemas import SegmentInternal, TagModel
from ..utils import split_sentences
from .extract import (
    process_run_element, 
    is_pure_text_run, 
    get_run_signature, 
    get_run_text
)

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

def strip_wrapping_tags(source_text: str, tags: dict) -> tuple[str, dict]:
    """
    Cleans up tag patterns in segment text:
    1. Removes outer wrapping tags: '<1><2>text</2></1>' -> 'text'
    2. Removes empty tag pairs: '<N></N>' -> ''
    3. Removes whitespace-only tag pairs: '<N>\\n</N>' or '<N> </N>' -> '' (or keeps whitespace)
    
    Iterates until no more changes occur.
    """
    if not source_text:
        return source_text, tags or {}
    
    new_tags = dict(tags) if tags else {}
    text = source_text
    
    changed = True
    while changed:
        changed = False
        text_before = text
        
        # 1. Remove empty tag pairs: <N></N> (including groups like <1><2></2></1>)
        # Pattern matches <N></N> with nothing in between
        text = re.sub(r'<(\d+)></\1>', '', text)
        
        # 2. Remove whitespace-only tag pairs: <N>whitespace</N>
        # This removes tags that only contain spaces, newlines, nbsp, etc.
        text = re.sub(r'<(\d+)>[\s\xa0]*</\1>', '', text)
        
        # 3. Peel off outer wrapping tags if they encompass entire content
        # Use stripped version for matching, but preserve whitespace in result
        text_stripped = text.strip()
        match = re.match(r'^<(\d+)>(.*)</\1>$', text_stripped, re.DOTALL)
        if match:
            tag_id = match.group(1)
            inner = match.group(2)  # Don't strip inner - preserve whitespace
            text = inner
            if tag_id in new_tags:
                del new_tags[tag_id]
            changed = True
        
        # Check if anything changed in this iteration
        if text != text_before:
            changed = True
    
    # Final cleanup: filter tags dict to only keep tags that still appear
    # NOTE: Do NOT strip here - whitespace is handled in process_paragraph and restored in assembler
    tag_ids_in_text = set(re.findall(r'<(\d+)>', text))
    new_tags = {k: v for k, v in new_tags.items() if k in tag_ids_in_text}
    
    return text, new_tags

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

def process_paragraph(para_element, location: dict, context: dict) -> list[SegmentInternal]:
    """
    Converts a docx Paragraph XML ELEMENT into a SegmentInternal list.
    """
    
    segments = []
    
    # Check for skipping (e.g. ToC)
    pStyle = para_element.find(qn('w:pStyle'))
    if pStyle is not None:
        style_val = pStyle.get(qn('w:val'))
        # Skip TOC
        if style_val and ('toc' in style_val.lower() or 'table of contents' in style_val.lower()):
            return []

    # Local State
    tags = {} # tid -> TagModel
    next_tag_id = 1
    
    def add_tag(tag_model: TagModel) -> str:
        nonlocal next_tag_id
        tid = str(next_tag_id)
        next_tag_id += 1
        tags[tid] = tag_model
        return tid

    # Buffer for text accumulation before processing
    run_buffer = [] # List of elements
    buffer_signature = None
    
    final_content = ""
    
    def flush_run_buffer():
        nonlocal buffer_signature, final_content
        if not run_buffer:
            return
            
        # Optimization: Merge runs with same signature
        if len(run_buffer) > 1 and all(is_pure_text_run(r) for r in run_buffer):
            # Merge text
            merged_text = ""
            for r in run_buffer:
                merged_text += get_run_text(r)
            
            # Process as one
            final_content += process_run_element(run_buffer[0], add_tag_func=add_tag, context=context, process_para_func=process_paragraph, text_override=merged_text)
        else:
            # Process individually
            for r in run_buffer:
                final_content += process_run_element(r, add_tag_func=add_tag, context=context, process_para_func=process_paragraph)
                
        run_buffer.clear()
        buffer_signature = None

    # Iterate Children
    for child in para_element:
        if child.tag == qn('w:r'):
             # Check Signature
             sig = get_run_signature(child)
             
             # If sig changes or not pure text, flush
             if sig != buffer_signature or not is_pure_text_run(child):
                 flush_run_buffer()
                 buffer_signature = sig
             
             run_buffer.append(child)
             
        elif child.tag == qn('w:hyperlink'):
             flush_run_buffer()
             
             # Hyperlinks contain runs
             rid = child.get(qn('r:id'))
             
             # Add Link Tag Wrapper
             l_tag = TagModel(type="link", xml_attributes={"rid": rid})
             l_tid = add_tag(l_tag)
             final_content += f"<{l_tid}>"
             
             for sub in child.findall(qn('w:r')):
                 final_content += process_run_element(sub, add_tag, context, process_paragraph)
                 
             final_content += f"</{l_tid}>"
             
        elif child.tag == qn('w:bookmarkStart') or child.tag == qn('w:bookmarkEnd'):
             # Ignore bookmarks for now
             pass
             
        else:
             # Other elements (math, smarttag etc)
             # Flush buffer first
             flush_run_buffer()
             # Try simple text extraction if it has text?
             pass
             
    flush_run_buffer()
    
    if not final_content.strip() and not ("[SHAPE]" in final_content):
        return []

    # Whitespace Handling (Preservation)
    # We strip main text but store whitespace info in metadata
    leading_ws = ""
    trailing_ws = ""
    
    raw_text_stripped = final_content
    match_leading = re.match(r'^(\s+)', final_content)
    if match_leading:
        leading_ws = match_leading.group(1)
        
    match_trailing = re.search(r'(\s+)$', final_content)
    if match_trailing:
        trailing_ws = match_trailing.group(1)
        
    # Careful stripping: Remove leading/trailing from the tagged string
    # But tags might be involved.
    # Simple approach: Strip, and if tags are cut, parser repair logic handles closing/opening?
    # No, stripping tags is dangerous.
    # We only strip if the whitespace is OUTSIDE tags or we treat tags as transparent.
    
    # BETTER: Don't strip content here. Let the segmentation handle it?
    # If we split sentences, pysbd might eat whitespace.
    # Let's clean up valid content
    clean_content = final_content # .strip() # Don't strip to preserve formatting precision?
    
    # We decided to use metadata for whitespace in reassembly loop.
    # Let's extract whitespace from the raw text content (ignoring tags for a moment is hard).
    # Regex to capture just the text nodes vs tags
    # Let's just strip the full string and save what we removed.
    clean_content = final_content.strip()
    if not clean_content:
         # It was all whitespace.
         # For now return one emptyish segment?
         # Or skip?
         if not "[SHAPE]" in final_content:
             return []
             
    ws_meta = {}
    if leading_ws: ws_meta['leading'] = leading_ws
    if trailing_ws: ws_meta['trailing'] = trailing_ws
    
    location['whitespaces'] = ws_meta
    
    # Check Wrapper Tags (e.g. entire paragraph holds one style)
    # If clean_content starts with <X> and ends with </X>, we can peel it off?
    # Simpler: Don't optimize this now. Reassembly handles it.
    
    # Segmentation
    text_to_split = clean_content
    # Note: Splitting tagged text is risky if we break tags.
    # We should use a tag-aware splitter or split only on safe punctuation.
    # Current `_split_sentences` uses Pysbd which assumes plain text.
    # If we pass tagged text to pysbd, it might split inside a tag.
    
    # STRATEGY: 
    # 1. Plain Split (Blind)
    # 2. Repair Tags (Close/Open)
    
    parts = split_sentences(text_to_split)
    repaired_parts = repair_tags(parts)
    
    final_segments = []
    
    for i, part in enumerate(repaired_parts):
        seg_loc = location.copy()
        seg_loc['sub_index'] = i
        
        # Strip wrapping tags that encompass entire segment
        clean_part, clean_tags = strip_wrapping_tags(part, tags)
        
        # Merge adjacent tags with identical formatting
        clean_part, clean_tags = merge_adjacent_tags(clean_part, clean_tags)
        
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
