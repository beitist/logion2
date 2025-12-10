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
            
        segment = _process_paragraph(para, loc, context)
        if segment:
            container_segments.append(segment)

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
                    
                    segment = _process_paragraph(para, loc, context)
                    if segment:
                        container_segments.append(segment)

    return container_segments

def _process_paragraph(para, location: dict, context: dict) -> SegmentInternal:
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
            # Check for embedded CommentReference first
            com_refs = child.findall(qn('w:commentReference'))
            if com_refs:
                for cr in com_refs:
                     comment_id = cr.get(qn('w:id'))
                     if comment_id and context["comments_map"].get(comment_id):
                        comment_text = context["comments_map"][comment_id]
                        com_tag = TagModel(
                            type="comment", 
                            content=comment_text,
                            ref_id=comment_id
                        )
                        tid = add_tag(com_tag)
                        full_text += f"<{tid}>[COMMENT]</{tid}>"

            # Check for generic drawing/object if needed (ignored for now)
            
            run = Run(child, para)
            text = run.text
            if not text:
                continue
            
            extracted_tags = _extract_tags(run)
            if extracted_tags:
                active_ids = []
                # Open tags
                for t in extracted_tags:
                    tid = add_tag(t)
                    full_text += f"<{tid}>"
                    active_ids.append(tid)
                
                full_text += text
                
                # Close tags
                for tid in reversed(active_ids):
                    full_text += f"</{tid}>"

            else:
                full_text += text

        # 2. Hyperlink (w:hyperlink)
        elif tag_name == qn('w:hyperlink'):
            # Create a Link Tag wrapping the whole content
            # We don't extract URL for MVP yet, or we assume it's just 'link'
            link_tag = TagModel(type="link", xml_attributes={"is_hyperlink": True})
            tid = add_tag(link_tag)
            
            full_text += f"<{tid}>"
            
            # Iterate children of hyperlink (runs)
            for sub_child in child:
                if sub_child.tag == qn('w:r'):
                    run = Run(sub_child, para)
                    full_text += run.text
            
            full_text += f"</{tid}>"

        # 3. Comment Reference (w:commentReference)
        elif tag_name == qn('w:commentReference'):
            comment_id = child.get(qn('w:id'))
            if comment_id and context["comments_map"].get(comment_id):
                comment_text = context["comments_map"][comment_id]
                # Embed as a Tag with content
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
                    # Check for embedded CommentReference first (copy-paste logic from w:r above, ideally refactor)
                    # For MVP short-code, we just handle direct run text.
                    # TODO: If comments are inside insertions, we need recursion or helper.
                    
                    # Recursion helper?
                    # Let's simple-inline the Run handling for now.
                    run = Run(sub_child, para)
                    text = run.text
                    if text:
                        extracted_tags = _extract_tags(run)
                        if extracted_tags:
                            active_ids = []
                            for t in extracted_tags:
                                tid = add_tag(t)
                                full_text += f"<{tid}>"
                                active_ids.append(tid)
                            full_text += text
                            for tid in reversed(active_ids):
                                full_text += f"</{tid}>"
                        else:
                            full_text += text

        # 5. Deleted Text (w:del) - Tracked Changes REJECT (Skip)
        elif tag_name == qn('w:del'):
            continue

    if not full_text.strip():
        return None

    return SegmentInternal(
        id=str(uuid.uuid4()),
        segment_id=str(uuid.uuid4()),
        source_text=full_text,
        target_content=None,
        status="draft",
        tags=tags,
        metadata=location
    )

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
