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
        
        final_segments.append(SegmentInternal(
            id=str(uuid.uuid4()),
            segment_id=str(uuid.uuid4()),
            source_text=part,
            target_content=None, 
            status="draft",
            tags=tags, 
            metadata=seg_loc
        ))
        
    return final_segments

def process_container(container, base_metadata: dict, context: dict):
    """
    Iterates over a container's paragraphs and tables.
    """
    all_segments = []
    
    # Paragraphs
    for i, para in enumerate(container.paragraphs):
        meta = base_metadata.copy()
        meta['p_index'] = i
        # Use _element to get lxml
        segs = process_paragraph(para._element, meta, context)
        all_segments.extend(segs)
        
    # Tables
    for t_i, table in enumerate(container.tables):
        for r_i, row in enumerate(table.rows):
            for c_i, cell in enumerate(row.cells):
                # Recursive call for Cell Container
                cell_meta = base_metadata.copy()
                cell_meta['child_type'] = 'table_cell'
                cell_meta['table_index'] = t_i
                cell_meta['row_index'] = r_i
                cell_meta['cell_index'] = c_i
                
                cell_segs = process_container(cell, cell_meta, context)
                all_segments.extend(cell_segs)
                
    return all_segments
