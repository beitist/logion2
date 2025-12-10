from typing import List, Tuple, Dict
import uuid
import re
from docx.oxml.ns import qn
from docx.api import Document
from docx.text.run import Run
from lxml import etree

from .schemas import SegmentInternal, TagModel

def parse_docx(file_path: str) -> List[SegmentInternal]:
    """
    Parses a DOCX file and extracts segments with tags for formatting, hyperlinks, and comments.
    """
    doc = Document(file_path)
    segments = []
    
    # 1. Load Comments Map (id -> text)
    comments_map = {}
    try:
        # Try explicit XML parsing for comments as python-docx support varies
        # We need to find the comments part
        part = doc.part
        # This is a bit hacky but robust for reading: iterate relations
        for rel in part.rels.values():
            if "comments" in rel.reltype and not "commentsExtended" in rel.reltype and not "commentsIds" in rel.reltype:
                 # Found comments.xml
                 xml_data = rel.target_part.blob
                 root = etree.fromstring(xml_data)
                 # Namespace usually w:
                 namespaces = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
                 for comment in root.findall('.//w:comment', namespaces):
                     cid = comment.get(qn('w:id'))
                     ctext = "".join([t.text for t in comment.findall('.//w:t', namespaces) if t.text])
                     comments_map[cid] = ctext
    except Exception as e:
        print(f"Warning: Could not load comments: {e}")

    # Helper context to pass comments_map
    context = {"comments_map": comments_map}

    # 1. Body
    segments.extend(_process_container(doc, {"type": "body"}, context))

    # 2. Key Sections (Headers/Footers)
    for s_idx, section in enumerate(doc.sections):
        # Header
        if section.header:
             segments.extend(_process_container(section.header, {
                 "type": "header", 
                 "section_index": s_idx
             }, context))
        # Footer
        if section.footer:
             segments.extend(_process_container(section.footer, {
                 "type": "footer", 
                 "section_index": s_idx
             }, context))
    
    return segments

def _process_container(container, base_metadata: dict, context: dict) -> List[SegmentInternal]:
    container_segments = []
    
    # 1. Paragraphs
    for i, para in enumerate(container.paragraphs):
        if not para.text.strip():
            continue
        
        # Merge base_metadata with specific location
        loc = base_metadata.copy()
        # "index" was used for body paragraphs in WP1. 
        if base_metadata.get("type") == "body":
            loc["index"] = i
        else:
            loc["p_index"] = i
            
        segment_list = _process_paragraph(para, loc, context)
        if segment_list:
            container_segments.extend(segment_list)

    # 2. Tables
    for t_idx, table in enumerate(container.tables):
        for r_idx, row in enumerate(table.rows):
            for c_idx, cell in enumerate(row.cells):
                # Recursion! A cell is also a container (has paragraphs and tables)
                # We need to construct the location correctly.
                
                cell_loc = base_metadata.copy()
                cell_loc["child_type"] = "table_cell" # differentiating direct paragraphs vs table cell paragraphs
                cell_loc["table_index"] = t_idx
                cell_loc["row_index"] = r_idx
                cell_loc["cell_index"] = c_idx
                
                # Cells only contain paragraphs/tables, so we can use _process_container?
                # But _process_container iterates tables too, which supports nested tables automatically!
                # However, our metadata scheme in WP1 Extension 1 was flat for tables: "type": "table".
                # To support recursion and headers properly, we need a flexible metadata structure.
                # For this step, let's keep it compatible but support the hierarchy.
                
                # Current table logic used:
                # location = { "type": "table", "table_index": ..., ... "p_index": ... }
                # The "type" was "table".
                
                # If we are in the body, base_metadata is {"type": "body"}.
                # If we are in header, base_metadata is {"type": "header", "section": ...}.
                
                # Let's adjust the location logic for specific paragraphs inside the cell.
                # We will NOT call _process_container recursively yet to avoid breaking previous schema too much,
                # but we will iterate the cell's paragraphs.
                
                for p_idx, para in enumerate(cell.paragraphs):
                    if not para.text.strip():
                        continue
                        
                    loc = base_metadata.copy()
                    # We override "type" to indicate it's in a table, OR we keep parent type?
                    # The previous verification expected "type": "table".
                    # Let's keep "type": "table" but add "parent_context" if needed?
                    # Actually, for Headers, we need to know it is in a header.
                    
                    if base_metadata["type"] == "body":
                         loc["type"] = "table" # Backwards compatibility with previous step
                    else:
                         # It's a table inside a header/footer
                         loc["sub_type"] = "table"
                         
                    loc["table_index"] = t_idx
                    loc["row_index"] = r_idx
                    loc["cell_index"] = c_idx
                    loc["p_index"] = p_idx
                    
                    segment_list = _process_paragraph(para, loc, context)
                    if segment_list:
                        container_segments.extend(segment_list)

    return container_segments

def _process_paragraph(para, location: dict, context: dict) -> List[SegmentInternal]:
    """
    Converts a docx Paragraph object into a SegmentInternal with tags.
    Handles Runs, Hyperlinks, and Comments via XML iteration.
    """
    full_text = ""
    tags = {}
    
    # Counter for tags
    tag_counter = 1
    
    def add_tag(tag_model: TagModel):
        nonlocal tag_counter
        tid = str(tag_counter)
        tags[tid] = tag_model
        tag_counter += 1
        return tid

    # IMPORTANT: We iterate DIRECT children of the paragraph element.
    # Hyperlinks and Runs are children of the paragraph.
    # We must treat them sequentially.
    
    for child in para._element:
        tag_name = child.tag
        
        # 1. Regular Run (w:r)
        if tag_name == qn('w:r'):
             # Handle run content via helper
             run_text = _process_run_element(child, para, add_tag, context)
             if run_text:
                 full_text += run_text

        # 2. Hyperlink (w:hyperlink)
        elif tag_name == qn('w:hyperlink'):
            # Create a Link Tag wrapping the whole content
            link_tag = TagModel(type="link", xml_attributes={"is_hyperlink": True})
            tid = add_tag(link_tag)
            
            full_text += f"<{tid}>"
            
            # Iterate children of hyperlink (runs)
            for sub_child in child:
                if sub_child.tag == qn('w:r'):
                    # Treat as run
                    run_text = _process_run_element(sub_child, para, add_tag, context)
                    if run_text:
                        full_text += run_text
            
            full_text += f"</{tid}>"

        # 2b. Comment Range Start
        elif tag_name == qn('w:commentRangeStart'):
            comment_id = child.get(qn('w:id'))
            if comment_id and context["comments_map"].get(comment_id):
                # Start a wrapping tag
                comment_text = context["comments_map"][comment_id]
                com_tag = TagModel(
                    type="comment",
                    content=comment_text,
                    ref_id=comment_id
                )
                tid = add_tag(com_tag)
                # Store mapping so we know this ID is active/handled as a range
                # We need to map XML-ID to our TAG-ID to close it later
                # Use context or local dict? Local is fine for para-scope? 
                # WARNING: Comments can span paragraphs! 
                # If a comment spans paragraphs, we have a problem with our SegmentInternal Design (per Paragraph).
                # MVP Limitation: We CLOSE all tags at end of paragraph. 
                # If we encounter EndTag in next para without StartTag, we ignore? 
                # OR we just treat intra-paragraph ranges for now. 
                # Let's support Intra-Paragraph Ranges fully.
                # For Inter-Paragraph, we might leave open? No, SegmentInternal must be self-contained XML-ish.
                # Decision: Auto-Close at end of para. Auto-Reopen at start of next? Too complex.
                # MVP: Intra-paragraph ranges work. Spanning ranges will look like separate comments per segment.
                
                # We need to store 'xml_id' -> 'tag_id' for this paragraph.
                if "_active_ranges" not in context:
                    context["_active_ranges"] = {} # XML_ID -> TAG_ID
                
                context["_active_ranges"][comment_id] = tid
                full_text += f"<{tid}>"

        # 2c. Comment Range End
        elif tag_name == qn('w:commentRangeEnd'):
            comment_id = child.get(qn('w:id'))
            # Check if we have an open tag for this
            if "_active_ranges" in context and comment_id in context["_active_ranges"]:
                tid = context["_active_ranges"][comment_id]
                full_text += f"</{tid}>"
                # Mark as handled so Ref doesn't duplicate? 
                
                if "_handled_ranges" not in context:
                    context["_handled_ranges"] = set()
                context["_handled_ranges"].add(comment_id)
                
                del context["_active_ranges"][comment_id]

        # 3. Comment Reference (w:commentReference)
        elif tag_name == qn('w:commentReference'):
            comment_id = child.get(qn('w:id'))
            
            # Check if this was already handled as a range
            was_handled = "_handled_ranges" in context and comment_id in context["_handled_ranges"]
            is_active = "_active_ranges" in context and comment_id in context["_active_ranges"]
            
            if was_handled or is_active:
                # It's a range comment, we ignore the anchor reference to avoid duplication
                pass
            elif comment_id and context["comments_map"].get(comment_id):
                # Point Comment (no range seen in this para)
                comment_text = context["comments_map"][comment_id]
                com_tag = TagModel(
                    type="comment", 
                    content=comment_text, 
                    ref_id=comment_id
                )
                tid = add_tag(com_tag)
                full_text += f"<{tid}>[COMMENT]</{tid}>"

        # 4. Inserted Text (w:ins) - Tracked Changes ACCEPT
        elif tag_name == qn('w:ins'):
            # Treat as normal content. Iterate children (runs)
            for sub_child in child:
                if sub_child.tag == qn('w:r'):
                     run_text = _process_run_element(sub_child, para, add_tag, context)
                     if run_text:
                         full_text += run_text

        # 5. Deleted Text (w:del) - Tracked Changes REJECT (Skip)
        elif tag_name == qn('w:del'):
             # Future: Maybe extract deleted text if user wants "Show Revisions"
            continue

    if not full_text:
        return []

    # Decision: Split or Keep Whole?
    # MVP Strategy: Only split if NO TAGS are present to avoid breaking tag structure.
    # Future: Parse <n>...</n> and split safely.
    segments_to_create = []
    
    if not tags:
        # Pure text, safe to split
        sentences = _split_sentences(full_text)
        for idx, sentence in enumerate(sentences):
             segments_to_create.append((sentence, idx))
    else:
        # Has tags, keep whole
        segments_to_create.append((full_text, 0))

    final_segments = []
    for content, sub_index in segments_to_create:
        # Create unique location
        seg_loc = location.copy()
        seg_loc["sub_index"] = sub_index
        
        final_segments.append(SegmentInternal(
            id=str(uuid.uuid4()),
            segment_id=str(uuid.uuid4()),
            source_text=content,
            target_content=None, # Translation starts empty/null
            status="draft",
            tags=tags if sub_index == 0 else {}, # Tags technically belong to the whole, but we only have them here if we didn't split.
            metadata=seg_loc
        ))

    return final_segments

import pysbd

_segmenter = pysbd.Segmenter(language="en", clean=False)

def _split_sentences(text: str) -> List[str]:
    # Use pysbd for robust splitting
    return _segmenter.segment(text)

def _extract_tags(run) -> List[TagModel]:
    """
    Inspects a run for Bold, Italic, Underline.
    Returns a list of detected TagModels.
    """
    found = []
    
    if run.bold:
        found.append(TagModel(type="bold"))
    if run.italic:
        found.append(TagModel(type="italic"))
    if run.underline:
        found.append(TagModel(type="underline"))
        
    # TODO: Comments, Superscript, Subscript
        
    return found

def _process_run_element(run_element, para, add_tag_func, context) -> str:
    """
    Helper to process a w:r element.
    Handles formatting (Bold/Italic), Embedded Comments, Tabs, Breaks, and Text.
    Also handles URL regex detection.
    """
    # 1. Embedded Comments (w:commentReference in Run)
    # Check for embedded CommentReference logic copied/adapted?
    # Usually they are siblings to text in w:r, so we iterate items.
    
    # 2. Extract formatting from Run object
    run_obj = Run(run_element, para)
    extracted_tags = _extract_tags(run_obj)
    
    active_ids = []
    full_run_text = ""
    
    # Open formatting tags
    if extracted_tags:
        for t in extracted_tags:
            tid = add_tag_func(t)
            full_run_text += f"<{tid}>"
            active_ids.append(tid)
            
    # 3. Iterate Children of w:r (Text, Tab, Br, CommentRef)
    content_accum = ""
    
    for child in run_element:
        tag_name = child.tag
        
        if tag_name == qn('w:t'):
            text_val = child.text or ""
            content_accum += text_val
            
        elif tag_name == qn('w:tab'):
             # Handle TAB
             # Strategy: Convert to Tag or literal. Plan said <4>TAB</4> tag type="tab".
             # Let's create a TagModel for it.
             tab_tag = TagModel(type="tab", content="[TAB]")
             tid = add_tag_func(tab_tag)
             # Visual spacer? Or just the tag?
             # Let's render it as a visual block in frontend, so [TAB] is good.
             content_accum += f"<{tid}>[TAB]</{tid}>"
             
        elif tag_name == qn('w:br'):
             # Handle LINE BREAK
             # Insert HTML break and maybe a Tag?
             # Plan says: <br/> literal.
             content_accum += "<br/>"

        elif tag_name == qn('w:commentReference'):
            cid = child.get(qn('w:id'))
            if cid and context["comments_map"].get(cid):
                ctext = context["comments_map"][cid]
                com_tag = TagModel(type="comment", content=ctext, ref_id=cid)
                tid = add_tag_func(com_tag)
                content_accum += f"<{tid}>[COMMENT]</{tid}>"

    # 4. Process Text for URLs (Regex)
    # URL detection works on text parts.
    # But mixed content (text <br> text) makes regex hard.
    # Simple strategy: Run regex on the whole accumulated string? 
    # Risk: Regex matching tags inside.
    # Better: Only run regex on the w:t parts before appending?
    # But we already accumulated them.
    # Refactoring:
    # URL regex should run on text chunks only.
    # Let's just do it post-hoc on the accumulated text if it hasn't tags inside?
    # Or, simpler: Just return content_accum.
    # If we want High-Fidelity URL detection in mixed content (Tabs/Breaks), it requires distinct processing.
    # For MVP: Re-apply the URL pattern to text parts?
    # Let's modify the loop above:
    
    # New Loop logic to handle URL splitting on the fly
    content_accum_final = ""
    
    # helper for checking URL in text
    def process_text_for_urls(txt):
        if not txt: return ""
        url_pattern = re.compile(r'(https?://[^\s]+)')
        parts = url_pattern.split(txt)
        res = ""
        if len(parts) > 1:
            for part in parts:
                if url_pattern.match(part):
                        l_tag = TagModel(type="link", xml_attributes={"is_hyperlink": True})
                        l_tid = add_tag_func(l_tag)
                        res += f"<{l_tid}>{part}</{l_tid}>"
                elif part:
                        res += part
            return res
        else:
            return txt

    # Re-iterate or just rebuild logic
    final_content = ""
    for child in run_element:
        tag_name = child.tag
        if tag_name == qn('w:t'):
            final_content += process_text_for_urls(child.text or "")
        elif tag_name == qn('w:tab'):
             tab_tag = TagModel(type="tab", content="[TAB]")
             tid = add_tag_func(tab_tag)
             final_content += f"<{tid}>[TAB]</{tid}>"
        elif tag_name == qn('w:br'):
             final_content += "<br/>"
        elif tag_name == qn('w:commentReference'):
            cid = child.get(qn('w:id'))
            
            # Check if this was already handled as a range
            # Note: _process_run_element shares the same context dict as _process_paragraph
            was_handled = "_handled_ranges" in context and cid in context["_handled_ranges"]
            is_active = "_active_ranges" in context and cid in context["_active_ranges"]
            
            if was_handled or is_active:
                # Suppress point comment
                pass
            elif cid and context["comments_map"].get(cid):
                ctext = context["comments_map"][cid]
                com_tag = TagModel(type="comment", content=ctext, ref_id=cid)
                tid = add_tag_func(com_tag)
                final_content += f"<{tid}>[COMMENT]</{tid}>"

    full_run_text += final_content

    # Close formatting tags
    if extracted_tags:
        for tid in reversed(active_ids):
            full_run_text += f"</{tid}>"
            
    return full_run_text
