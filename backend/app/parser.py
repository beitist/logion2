from typing import List, Tuple, Dict
import uuid
import re
import docx
from docx.oxml.ns import qn
from docx.api import Document
from docx.text.run import Run
from lxml import etree

from .schemas import SegmentInternal, TagModel
from .logger import get_logger

logger = get_logger("Parser")

def parse_docx(file_path: str, segmentation_func=None, source_lang="en") -> List[SegmentInternal]:
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
        logger.warning(f"Could not load comments: {e}")

    # Helper context to pass comments_map, segmentation_func, source_lang
    context = {
        "comments_map": comments_map,
        "segmentation_func": segmentation_func,
        "segmentation_func": segmentation_func,
        "source_lang": source_lang,
        "extra_segments": []
    }

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
             
    # 3. Comments (Separate Segments)
    # Strategy: Expose comments as translatable segments.
    # We use valid IDs from the map.
    # Note: This list might include comments not referenced in the document body if they are zombies,
    # but that's acceptable.
    for cid, ctext in comments_map.items():
        if not ctext.strip():
            continue
            
        # Create a SegmentInternal for the comment
        # Metadata distinguishes it
        seg = SegmentInternal(
            id=str(uuid.uuid4()),
            segment_id=str(uuid.uuid4()),
            source_text=ctext,
            target_content=None,
            status="draft",
            tags={},
            metadata={
                "type": "comment",
                "comment_id": cid
            }
        )
        segments.append(seg)

    # 4. Footnotes
    segments.extend(_extract_footnotes(doc, context))
    
    # 5. Endnotes
    segments.extend(_extract_endnotes(doc, context))
    
    # 6. Extra Segments (Shapes/Textboxes)
    if "extra_segments" in context:
         segments.extend(context["extra_segments"])

    return segments

def _extract_footnotes(doc, context) -> List[SegmentInternal]:
    """
    Extracts footnotes as separate segments.
    """
    segments = []
    try:
        part = doc.part
        footnotes_part = None
        for rel in part.rels.values():
             if "footnotes" in rel.reltype:
                 footnotes_part = rel.target_part
                 break
                 
        if not footnotes_part:
            return []
            
        xml_data = footnotes_part.blob
        root = etree.fromstring(xml_data)
        namespaces = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        
        for footnote in root.findall('.//w:footnote', namespaces):
            fid = footnote.get(qn('w:id'))
            ftype = footnote.get(qn('w:type'))
            if ftype in ["separator", "continuationSeparator"]:
                continue

            for i, p_elem in enumerate(footnote.findall('.//w:p', namespaces)):
                # Manual XML processing -> _process_paragraph expects XML now?
                # or we convert p_elem to XML wrapper?
                # Let's update _process_paragraph to take XML element directly.
                
                # Check text content via xpath
                text_content = "".join([t.text for t in p_elem.findall('.//w:t', namespaces) if t.text])
                if not text_content.strip():
                     continue

                meta = {
                    "type": "footnote",
                    "footnote_id": fid,
                    "p_index": i
                }
                
                found_segments = _process_paragraph(p_elem, meta, context)
                segments.extend(found_segments)
            
    except Exception as e:
        logger.warning(f"Could not load footnotes: {e}")
        
    return segments

def _extract_endnotes(doc, context) -> List[SegmentInternal]:
    """
    Extracts endnotes as separate segments.
    """
    segments = []
    try:
        part = doc.part
        endnotes_part = None
        for rel in part.rels.values():
             if "endnotes" in rel.reltype:
                 endnotes_part = rel.target_part
                 break
                 
        if not endnotes_part:
            return []
            
        xml_data = endnotes_part.blob
        root = etree.fromstring(xml_data)
        namespaces = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        
        for endnote in root.findall('.//w:endnote', namespaces):
            eid = endnote.get(qn('w:id'))
            etype = endnote.get(qn('w:type'))
            if etype in ["separator", "continuationSeparator"]:
                continue

            for i, p_elem in enumerate(endnote.findall('.//w:p', namespaces)):
                
                text_content = "".join([t.text for t in p_elem.findall('.//w:t', namespaces) if t.text])
                if not text_content.strip():
                     continue

                meta = {
                    "type": "endnote",
                    "endnote_id": eid,
                    "p_index": i
                }
                
                segments.extend(_process_paragraph(p_elem, meta, context))
            
    except Exception as e:
        logger.warning(f"Could not load endnotes: {e}")
        
    return segments

def _process_container(container, base_metadata: dict, context: dict) -> List[SegmentInternal]:
    container_segments = []
    
    # 1. Paragraphs
    for i, para in enumerate(container.paragraphs):
        # REMOVED: if not para.text.strip(): continue (Skips shapes/images!)
        
        # Merge base_metadata with specific location
        loc = base_metadata.copy()
        # "index" was used for body paragraphs in WP1. 
        if base_metadata.get("type") == "body":
            loc["index"] = i
        else:
            loc["p_index"] = i
            
        segment_list = _process_paragraph(para._element, loc, context)
        if segment_list:
            container_segments.extend(segment_list)

    # 2. Tables
    for t_idx, table in enumerate(container.tables):
        # Track processed cells to handle Merged Cells (vMerge)
        # python-docx repeats the cell object for each covered row.
        processed_tcs = set() 
        
        for r_idx, row in enumerate(table.rows):
            for c_idx, cell in enumerate(row.cells):
                # Check for duplication via XML element (tc)
                if cell._tc in processed_tcs:
                    continue
                processed_tcs.add(cell._tc)

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
                    # REMOVED: if not para.text.strip(): continue
                        
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
                    
                    segment_list = _process_paragraph(para._element, loc, context)
                    if segment_list:
                        container_segments.extend(segment_list)

    return container_segments

def _process_paragraph(para_element, location: dict, context: dict) -> List[SegmentInternal]:
    """
    Converts a docx Paragraph XML ELEMENT into a SegmentInternal with tags.
    Handles Runs, Hyperlinks, and Comments via XML iteration.
    Argument 'para_element' is an lxml/OxmlElement (not Paragraph object).
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
    
    for child in para_element:
        tag_name = child.tag
        
        # 1. Regular Run (w:r)
        
        # 1. Regular Run (w:r)
        # logger.debug(f"CHILD: {tag_name}")
        
        # 1. Regular Run (w:r)
        if tag_name == qn('w:r'):
             # Handle run content via helper
             run_text = _process_run_element(child, add_tag, context)
             if run_text:
                 full_text += run_text

        # 2. Hyperlink (w:hyperlink)
        elif tag_name == qn('w:hyperlink'):
            # Create a Link Tag wrapping the whole content
            # We need to capture the relationship ID (r:id) to know the URL!
            rid = child.get(qn('r:id'))
            
            link_tag = TagModel(type="link", xml_attributes={"is_hyperlink": True, "rid": rid})
            tid = add_tag(link_tag)
            
            full_text += f"<{tid}>"
            
            # Iterate children of hyperlink (runs)
            for sub_child in child:
                if sub_child.tag == qn('w:r'):
                    # Treat as run
                    run_text = _process_run_element(sub_child, add_tag, context)
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
                full_text += f"<{tid}></{tid}>"

        # 4. Inserted Text (w:ins) - Tracked Changes ACCEPT
        elif tag_name == qn('w:ins'):
            # Treat as normal content. Iterate children (runs)
            for sub_child in child:
                if sub_child.tag == qn('w:r'):
                     run_text = _process_run_element(sub_child, add_tag, context)
                     if run_text:
                         full_text += run_text

        # 5. Footnote Reference
        elif tag_name == qn('w:footnoteReference'):
            fid = child.get(qn('w:id'))
            ftag = TagModel(type="footnote", xml_attributes={"id": fid})
            tid = add_tag(ftag)
            tid = add_tag(ftag)
            full_text += f"<{tid}></{tid}>"

        # 6. Endnote Reference
        elif tag_name == qn('w:endnoteReference'):
            eid = child.get(qn('w:id'))
            etag = TagModel(type="endnote", xml_attributes={"id": eid})
            tid = add_tag(etag)
            tid = add_tag(etag)
            full_text += f"<{tid}></{tid}>"

        # 7. Deleted Text (w:del) - Tracked Changes REJECT (Skip)
        elif tag_name == qn('w:del'):
             # Future: Maybe extract deleted text if user wants "Show Revisions"
            continue

    if not full_text:
        return []

    # Decision: Smart Splitting
    # Always split sentences, then repair tags across boundaries.
    
    segments_to_create = []
    final_segments = []

    # 1. Split (using SemanticAligner which protects tags from breaking splitting logic)
    sentences = _split_sentences(full_text, context.get("segmentation_func"), lang=context.get("source_lang", "en"))
    
    # 2. Repair Tags (Clone open tags across split boundaries)
    repaired_sentences = _repair_tags(sentences)
    
    for idx, sentence in enumerate(repaired_sentences):
         segments_to_create.append((sentence, idx))

    for content, sub_index in segments_to_create:
        # Create unique location
        seg_loc = location.copy()
        seg_loc["sub_index"] = sub_index

        # Detect Leading/Trailing Spaces
        src_leading = ""
        src_trailing = ""
        
        # Leading
        m_lead = re.match(r'^(\s+)', content)
        if m_lead:
            src_leading = m_lead.group(1)
            
        # Trailing
        m_trail = re.search(r'(\s+)$', content)
        if m_trail:
            src_trailing = m_trail.group(1)
            
        if src_leading or src_trailing:
            seg_loc["whitespaces"] = {
                "leading": src_leading,
                "trailing": src_trailing
            }
        
        final_segments.append(SegmentInternal(
            id=str(uuid.uuid4()),
            segment_id=str(uuid.uuid4()),
            source_text=content,
            target_content=None, # Translation starts empty/null
            status="draft",
            tags=tags, # Pass tags to all segments so split parts can reference them
            metadata=seg_loc
        ))

    return final_segments

import pysbd

_segmenter_cache = {}

def _get_segmenter(lang: str):
    if lang not in _segmenter_cache:
        # Pysbd supports ISO codes. Fallback to en.
        try:
             _segmenter_cache[lang] = pysbd.Segmenter(language=lang, clean=False)
        except:
             _segmenter_cache[lang] = pysbd.Segmenter(language="en", clean=False)
    return _segmenter_cache[lang]

def _split_sentences(text: str, segmentation_func=None, lang="en") -> List[str]:
    # Use pysbd for robust splitting
    if segmentation_func:
        return segmentation_func(text)
    
    seg = _get_segmenter(lang)
    return seg.segment(text)

def _extract_tags(run_element) -> List[TagModel]:
    """
    Inspects a run XML ELEMENT for formatting.
    Returns a list of detected TagModels.
    """
    found = []
    
    # Needs valid namespaces
    namespaces = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    
    rPr = run_element.find(qn('w:rPr'))
    if rPr is None:
        return found
        
    # Bold
    # w:b can be present (True) or have w:val="0"/"false" (False)
    # Simple check: availability
    if rPr.find(qn('w:b')) is not None:
         # To be pedantic: check w:val
         # val = rPr.find(qn('w:b')).get(qn('w:val'))
         # if val not in ['0', 'false', 'off']:
         found.append(TagModel(type="bold"))
         
    if rPr.find(qn('w:i')) is not None:
        found.append(TagModel(type="italic"))
        
    if rPr.find(qn('w:u')) is not None:
        found.append(TagModel(type="underline"))
        
    # Superscript / Subscript (w:vertAlign w:val='superscript')
    vAlign = rPr.find(qn('w:vertAlign'))
    if vAlign is not None:
        val = vAlign.get(qn('w:val'))
        if val == 'superscript':
            found.append(TagModel(type="superscript"))
        elif val == 'subscript':
            found.append(TagModel(type="subscript"))
            
    # Color
    color = rPr.find(qn('w:color'))
    if color is not None:
        val = color.get(qn('w:val'))
        # Ignore auto or black (common defaults that cause noise)
        if val and val != 'auto' and val != '000000':
            found.append(TagModel(type="color", xml_attributes={"color": val}))

    # Highlighting
    highlight = rPr.find(qn('w:highlight'))
    if highlight is not None:
        val = highlight.get(qn('w:val'))
        found.append(TagModel(type="highlight", xml_attributes={"color": str(val)}))
            
    return found

def _handle_shape_element(shape_element, add_tag_func, context) -> str:
    # NEW: Drill down for Textboxes (w:txbxContent)
    found_textbox = False
    shape_id = None
    
    # Check for textbox content
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    txbx_contents = shape_element.findall('.//w:txbxContent', ns)
    
    if txbx_contents:
        logger.debug(f"Shape {shape_element}: Found {len(txbx_contents)} textboxes")
        shape_id = str(uuid.uuid4())
        found_textbox = True
        
        for txbx in txbx_contents:
            # Iterate paragraphs
            for i, para in enumerate(txbx.findall('.//w:p', ns)):
                loc = {
                    "type": "shape",
                    "shape_id": shape_id,
                    "p_index": i
                }
                
                sub_segments = _process_paragraph(para, loc, context)
                if sub_segments:
                    context["extra_segments"].extend(sub_segments)

    # Create shape tag
    if found_textbox:
        shape_tag = TagModel(type="shape", content="[SHAPE]", xml_attributes={"id": shape_id})
    else:
        shape_tag = TagModel(type="shape", content="[SHAPE]")
        
    tid = add_tag_func(shape_tag)
    return f"<{tid}></{tid}>"


def _process_run_element(run_element, add_tag_func, context) -> str:
    """
    Helper to process a w:r element.
    Handles formatting (Bold/Italic), Embedded Comments, Tabs, Breaks, and Text.
    Also handles URL regex detection.
    """
    # 2. Extract formatting from Run XML directly
    extracted_tags = _extract_tags(run_element)
    
    active_ids = []
    full_run_text = ""
    
    # Open formatting tags
    if extracted_tags:
        for t in extracted_tags:
            tid = add_tag_func(t)
            full_run_text += f"<{tid}>"
            active_ids.append(tid)
            
    # 3. Iterate Children of w:r (Text, Tab, Br, CommentRef, Shapes)
    # Re-iterate or just rebuild logic
    final_content = ""
    
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

    for child in run_element:
        tag_name = child.tag
        
        if tag_name == qn('w:t'):
            final_content += process_text_for_urls(child.text or "")
            
        elif tag_name == qn('w:tab'):
             tab_tag = TagModel(type="tab", content="[TAB]")
             tid = add_tag_func(tab_tag)
             final_content += f"<{tid}></{tid}>" # Remove [TAB] text
             
        elif tag_name == qn('w:br'):
             final_content += "<br/>"
             
        elif tag_name == qn('w:commentReference'):
            cid = child.get(qn('w:id'))
            
            # Check if this was already handled as a range
            was_handled = "_handled_ranges" in context and cid in context["_handled_ranges"]
            is_active = "_active_ranges" in context and cid in context["_active_ranges"]
            
            if was_handled or is_active:
                pass
            elif cid and context["comments_map"].get(cid):
                ctext = context["comments_map"][cid]
                com_tag = TagModel(type="comment", content=ctext, ref_id=cid)
                tid = add_tag_func(com_tag)
                final_content += f"<{tid}></{tid}>"

        elif tag_name == qn('w:drawing') or tag_name == qn('w:pict'):
             # Handle Shapes/Images
             final_content += _handle_shape_element(child, add_tag_func, context)

        elif tag_name == "{http://schemas.openxmlformats.org/markup-compatibility/2006}AlternateContent":
             # Handle AlternateContent (e.g. Choice vs Fallback)
             # usually w:drawing in Choice, w:pict in Fallback
             # We prefer Choice.
             mc_ns = {'mc': 'http://schemas.openxmlformats.org/markup-compatibility/2006', 'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
             
             choice = child.find('mc:Choice', mc_ns)
             fallback = child.find('mc:Fallback', mc_ns)
             
             if choice is not None:
                 # Iterate all children, as choice might contain multiple drawings or other elements
                 logger.debug(f"Processing mc:Choice. Found {len(list(choice))} children.")
                 for child_el in choice:
                     if child_el.tag == qn('w:drawing') or child_el.tag == qn('w:pict'):
                         final_content += _handle_shape_element(child_el, add_tag_func, context)
             
             if not final_content and fallback is not None:
                 for child_el in fallback:
                     if child_el.tag == qn('w:drawing') or child_el.tag == qn('w:pict'):
                          final_content += _handle_shape_element(child_el, add_tag_func, context)

             # if target_el is not None:
             #    # Recursive call to our own logic helper?
             #    # Or just call _handle_shape(target_el)?
             #    # We need to reuse the logic below.
             #    # Let's refactor the logic below into a local helper or function.
             #    final_content += _handle_shape_element(target_el, add_tag_func, context)

        elif tag_name == qn('w:footnoteReference'):
            fid = child.get(qn('w:id'))
            ftag = TagModel(type="footnote", xml_attributes={"id": fid})
            tid = add_tag_func(ftag)
            final_content += f"<{tid}></{tid}>"

        elif tag_name == qn('w:endnoteReference'):
            eid = child.get(qn('w:id'))
            etag = TagModel(type="endnote", xml_attributes={"id": eid})
            tid = add_tag_func(etag)
            final_content += f"<{tid}></{tid}>"

    full_run_text += final_content

    # Close formatting tags
    if extracted_tags:
        for tid in reversed(active_ids):
            full_run_text += f"</{tid}>"
            
    return full_run_text

import re
from typing import List

def _repair_tags(segments: List[str]) -> List[str]:
    """
    Ensures that if a segment ends with open tags, they are closed,
    and reopened in the next segment.
    """
    repaired = []
    stack = []
    # Regex to find tags: <1>, </1>
    pattern = re.compile(r'<(/?(\d+))>')
    
    for part in segments:
        # 1. Prepend Open Tags from Stack (Re-Open)
        prefix = "".join([f"<{tid}>" for tid in stack])
        current_seg = prefix + part
        
        # 2. Update Stack based on tags in THIS part (Original content)
        # We must scan 'part' to avoiding seeing the tags we just prepended
        for m in pattern.finditer(part):
            full_tag = m.group(1) # "1" or "/1"
            tid = m.group(2)
            is_close = full_tag.startswith("/")
            
            if is_close:
                # Attempt to pop from stack
                if stack and stack[-1] == tid:
                    stack.pop()
            else:
                stack.append(tid)
        
        # 3. Append Close Tags for remaining Stack (Close)
        suffix = "".join([f"</{tid}>" for tid in reversed(stack)])
        current_seg = current_seg + suffix
        
        repaired.append(current_seg)
        
    return repaired
