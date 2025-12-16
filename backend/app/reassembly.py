import docx
from docx.api import Document
import docx.shared
from typing import List
import shutil
import re
from docx.enum.text import WD_COLOR_INDEX
from docx.oxml.ns import qn
import copy
from lxml import etree
from .schemas import SegmentInternal, TagModel

def _inject_comments(doc: Document, segments: List[SegmentInternal]):
    """
    Updates the comments.xml part of the document with translated text.
    """
    # 1. Map segments by comment_id
    comment_segs = {s.metadata["comment_id"]: s for s in segments if s.metadata.get("type") == "comment"}
    
    if not comment_segs:
        return

    try:
        part = doc.part
        comments_part = None
        for rel in part.rels.values():
             if "comments" in rel.reltype and not "commentsExtended" in rel.reltype and not "commentsIds" in rel.reltype:
                 comments_part = rel.target_part
                 break
                 
        if not comments_part:
            print("Warning: No comments part found to update.")
            return
            
        xml_data = comments_part.blob
        root = etree.fromstring(xml_data)
        namespaces = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        
        updated_count = 0
        
        for comment in root.findall('.//w:comment', namespaces):
             cid = comment.get(qn('w:id'))
             if cid in comment_segs:
                 seg = comment_segs[cid]
                 target_text = seg.target_content if seg.target_content is not None else seg.source_text
                 
                 # Replace content
                 # Clear existing paragraphs/runs in XML
                 # Usually comments have w:p -> w:r -> w:t
                 # We can just replace the text of the first run and delete others?
                 # Or better: clear all children, create new w:p/w:r/w:t?
                 # Since this is low-level XML, let's keep it simple:
                 # Find all w:t and replace valid text?
                 # But target might be shorter/longer or have formatting?
                 # For MVP: Flatten text.
                 
                 # Remove existing content children (p)
                 for child in list(comment):
                     if child.tag == qn('w:p'):
                        comment.remove(child)
                        
                 # Create new simple paragraph
                 # <w:p><w:r><w:t>TEXT</w:t></w:r></w:p>
                 wp = etree.SubElement(comment, qn('w:p'))
                 wr = etree.SubElement(wp, qn('w:r'))
                 wt = etree.SubElement(wr, qn('w:t'))
                 wt.text = target_text
                 
                 updated_count += 1
                 
        if updated_count > 0:
            # Save back
            new_xml = etree.tostring(root, encoding='utf-8', standalone=True)
            comments_part._blob = new_xml
            print(f"Updated {updated_count} comments in comments.xml")
            
    except Exception as e:
        print(f"Error updating comments: {e}")

def _inject_footnotes(doc: Document, segments: List[SegmentInternal]):
    """
    Updates the footnotes.xml part of the document with translated text.
    Similar to comments strategy.
    """
    footnote_segs = {s.metadata["footnote_id"]: s for s in segments if s.metadata.get("type") == "footnote"}
    
    if not footnote_segs:
        return

    try:
        part = doc.part
        footnotes_part = None
        for rel in part.rels.values():
             if "footnotes" in rel.reltype:
                 footnotes_part = rel.target_part
                 break
                 
        if not footnotes_part:
            print("Warning: No footnotes part found to update.")
            return
            
        xml_data = footnotes_part.blob
        root = etree.fromstring(xml_data)
        namespaces = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        
        updated_count = 0
        
        for footnote in root.findall('.//w:footnote', namespaces):
             fid = footnote.get(qn('w:id'))
             if fid in footnote_segs:
                 seg = footnote_segs[fid]
                 target_text = seg.target_content if seg.target_content is not None else seg.source_text
                 
                 # Replace content (Flattened)
                 for child in list(footnote):
                     if child.tag == qn('w:p'):
                        footnote.remove(child)
                 
                 # Create proper paragraph structure with style if needed
                 # Footnote Text style usually
                 wp = etree.SubElement(footnote, qn('w:p'))
                 
                 # Optional: Set style
                 # pStyle = etree.SubElement(wp, qn('w:pPr'))
                 # pStyleVal = etree.SubElement(pStyle, qn('w:pStyle'))
                 # pStyleVal.set(qn('w:val'), 'FootnoteText')
                 
                 wr = etree.SubElement(wp, qn('w:r'))
                 # Add Footnote Reference char if this is the first run? 
                 # Usually footnotes start with <w:r><w:footnoteRef/></w:r>
                 # We should preserve the reference marker! 
                 # Our simple "remove all paragraphs" logic destroys the footnote reference marker.
                 # The marker is usually in the first run of the first paragraph.
                 
                 # Improved strategy:
                 # Iterate existing paragraphs. Find the one with text?
                 # Footnotes structure:
                 # <w:p>
                 #   <w:pPr>...</w:pPr>
                 #   <w:r><w:footnoteRef/></w:r>
                 #   <w:r><w:t>Actual text</w:t></w:r>
                 # </w:p>
                 
                 # MVP Fix: Re-create the reference.
                 wr_ref = etree.SubElement(wp, qn('w:r'))
                 etree.SubElement(wr_ref, qn('w:rPr')).append(etree.Element(qn('w:rStyle'), {qn('w:val'): 'FootnoteReference'}))
                 etree.SubElement(wr_ref, qn('w:footnoteRef'))
                 # Actually w:footnoteRef usually is solitary?
                 # Let's clean up logic:
                 # We insert a run with the text AFTER the reference?
                 # OR simpler: Find existing w:t elements and replace their text, 
                 # if multiple w:t, join them or clear subsequent ones.
                 
                 # Let's go with "Modify w:t" strategy for footnotes to preserve structure better.
                 # This is safer than rebuilding the whole paragraph.
                 
                 # Remove rebuild logic above, use traversal.
                 footnote.remove(wp) # cleanup my previous lines
                 
                 text_elements = footnote.findall('.//w:t', namespaces)
                 if text_elements:
                     # Set first text element to target_text
                     text_elements[0].text = target_text
                     # Clear others
                     for t in text_elements[1:]:
                         t.text = ""
                 else:
                     # No text found? Create one.
                     # Fallback to appending a paragraph
                     wp = etree.SubElement(footnote, qn('w:p'))
                     wr = etree.SubElement(wp, qn('w:r'))
                     wt = etree.SubElement(wr, qn('w:t'))
                     wt.text = target_text

                 updated_count += 1
                 
        if updated_count > 0:
            # Save back
            new_xml = etree.tostring(root, encoding='utf-8', standalone=True)
            footnotes_part._blob = new_xml
            print(f"Updated {updated_count} footnotes in footnotes.xml")
            
    except Exception as e:
        print(f"Error updating footnotes: {e}")

def reassemble_docx(original_path: str, output_path: str, segments: List[SegmentInternal]):
    """
    Takes original DOCX and a list of TRANSLATED segments.
    Writes a new DOCX where text is replaced by target_content.
    """
    # 1. Copy file to output path
    shutil.copy(original_path, output_path)
    
    doc = Document(output_path)
    
    # We assume segments map 1:1 to paragraphs for this MVP.
    # In reality, we must match IDs or indices.
    # Our parser saved "original_index" in metadata!
    
    # segment_map caused collisions for split segments (make_key ignored sub_index).
    # We now pass the full list of segments to _inject_into_container and let it group them properly.
    
    # 1. Body
    _inject_into_container(doc, {"type": "body"}, segments)
    
    # 2. Sections
    for s_idx, section in enumerate(doc.sections):
        if section.header:
            _inject_into_container(section.header, {"type": "header", "section_index": s_idx}, segments)
        if section.footer:
             _inject_into_container(section.footer, {"type": "footer", "section_index": s_idx}, segments)

    # 3. Comments (Update comments.xml)
    _inject_comments(doc, segments)

    # 4. Footnotes
    _inject_footnotes(doc, segments)

    doc.save(output_path)

def _inject_into_container(container, base_metadata, source_segments):
    # source_segments: List[SegmentInternal]
    
    # Helper to merge segments targeting the same paragraph
    def get_merged_content(segs_for_para):
        if not segs_for_para:
            return "", {}
        full_text = ""
        combined_tags = {}
        # Sort by sub_index
        segs_for_para.sort(key=lambda x: x.metadata.get("sub_index", 0))
        for s in segs_for_para:
            text = s.target_content if s.target_content is not None else s.source_text
            full_text += text
            if s.tags:
                combined_tags.update(s.tags)
                
        # Smart Merging Optimization
        # Remove </N><N> patterns (redundant boundary from split)
        # Regex: </(\d+)><\1>
        full_text = re.sub(r'</(\d+)><\1>', '', full_text)
        
        return full_text, combined_tags

    # 1. Build Grouped Segments from the flat list
    grouped_segments = {}
    
    for s in source_segments:
        m = s.metadata
        if not m: continue
        
        stype = m.get("type", "body")
        section_idx = m.get("section_index", -1)
        
        # Table Coords
        t_coords = None
        if m.get("child_type") == "table_cell" or m.get("sub_type") == "table" or stype == "table":
             t_coords = (m.get("table_index"), m.get("row_index"), m.get("cell_index"))
             
        p_idx = m.get("p_index") if m.get("p_index") is not None else m.get("index")
            
        key = (stype, section_idx, t_coords, p_idx)
        
        if key not in grouped_segments:
            grouped_segments[key] = []
        grouped_segments[key].append(s)

    # 2. Iterate the Container and Inject
    # We iterate the Physical Container (doc, header, etc.)
    
    stype = base_metadata.get("type")
    s_idx = base_metadata.get("section_index", -1)

    # DEBUG DUMP
    with open("debug_reassembly_keys.log", "a") as f:
         f.write(f"--- Injecting into {stype} s_idx={s_idx} ---\n")
         f.write(f"Grouped Keys: {[k for k in grouped_segments.keys() if k[0] == stype]}\n")

    # A. Paragraphs
    for i, para in enumerate(container.paragraphs):
        # Key = (stype, s_idx, None, i)
        key = (stype, s_idx, None, i)
        
        if key in grouped_segments:
            try:
                text, tags = get_merged_content(grouped_segments[key])
                _inject_tagged_text(para, text, tags)
                with open("debug_reassembly_keys.log", "a") as f: f.write(f"Inject Para {key}: OK\n")
            except Exception as e:
                print(f"Error injecting segment {key}: {e}")
        else:
            with open("debug_reassembly_keys.log", "a") as f: f.write(f"Inject Para {key}: MISSED\n")

    # B. Tables
    for t_i, table in enumerate(container.tables):
        for r_i, row in enumerate(table.rows):
            for c_i, cell in enumerate(row.cells):
                for p_i, para in enumerate(cell.paragraphs):
                    # Key Construction
                    target_type = stype
                    if stype == "body":
                        target_type = "table"
                    
                    key = (target_type, s_idx, (t_i, r_i, c_i), p_i)
                    
                    if key in grouped_segments:
                        try:
                            text, tags = get_merged_content(grouped_segments[key])
                            _inject_tagged_text(para, text, tags)
                            with open("debug_reassembly_keys.log", "a") as f: f.write(f"Inject Table {key}: OK\n")
                        except Exception as e:
                            print(f"Error injecting table segment {key}: {e}")
                    else:
                        with open("debug_reassembly_keys.log", "a") as f: f.write(f"Inject Table {key}: MISSED\n")


    
# This requires major refactoring of the loops above.
# Let's do it in the next tool call properly.
def _inject_segment(para, segment):
    target_text = segment.target_content
    # Clear existing runs
    para.clear()
    # RE-INJECT
    _inject_tagged_text(para, target_text, segment.tags)

def _inject_tagged_text(paragraph, text, tags_map):
    """
    Parses 'text' which may contain:
    1. Custom Tags: <1>...</1> (mapped to properties via tags_map)
    2. HTML Tags: <b>, <strong>, <i>, <em>, <u>, <br/>
    3. Custom Markers: [TAB], [COMMENT], [SHAPE]
    
    Reconstructs the paragraph with appropriate runs and formatting.
    Preserves w:drawing and w:pict elements.
    """
    p_element = paragraph._element
    
    # 1. Preserve Shapes (Drawings/Picts) before clearing
    # We iterate descendants to find them in order.
    preserved_shapes = []
    # Note: element.iter() might return self? No, usually descendants.
    # We check specific tags.
    # Safest way to get in-order:
    for child in p_element.iter():
        if child.tag == qn('w:drawing') or child.tag == qn('w:pict'):
            try:
                # Deepcopy to detach and save
                preserved_shapes.append(copy.deepcopy(child))
            except Exception as e:
                print(f"Warning: Failed to preserve shape: {e}")

    # 2. Clear existing content
    p_element.clear_content()

    # DEBUG LOGGING
    with open("debug_reassembly.txt", "a") as f:
        f.write(f"\n--- Injecting Text ---\nText: {text[:50]}...\nTags Map Keys: {list(tags_map.keys())}\n")
        f.write(f"Preserved Shapes: {len(preserved_shapes)}\n")

    # Tokenize
    tokens = re.split(r'(<[^>]+>)', text)
    
    active_style = {'bold': 0, 'italic': 0, 'underline': 0, 'highlight': False, 'superscript': False, 'subscript': False}
    
    for token in tokens:
        if not token:
            continue
            
        # Is it a Tag?
        if token.startswith("<") and token.endswith(">"):
            tag_content = token[1:-1] # strip < >
            is_closing = tag_content.startswith("/")
            if is_closing:
                tag_content = tag_content[1:]
                
            # Check ID (Digits) -> Custom Tag
            if tag_content.isdigit():
                tid = tag_content
                tag = tags_map.get(tid)
                if tag:
                    # Apply tag formatting
                    if tag.type == 'bold':
                        active_style['bold'] += -1 if is_closing else 1
                    elif tag.type == 'italic':
                        active_style['italic'] += -1 if is_closing else 1
                    elif tag.type == 'underline':
                        active_style['underline'] += -1 if is_closing else 1
                    elif tag.type == 'superscript':
                        active_style['superscript'] = not is_closing
                    elif tag.type == 'subscript':
                        active_style['subscript'] = not is_closing
                    elif tag.type == 'color':
                        # Handle color application
                        if is_closing:
                             active_style.pop('color', None)
                        else:
                             if tag.xml_attributes and 'color' in tag.xml_attributes:
                                 active_style['color'] = tag.xml_attributes['color']
                                 
                    elif tag.type == 'comment':
                        active_style['highlight'] = not is_closing
                    elif tag.type == 'shape' and not is_closing:
                        # Insert Shape
                        if preserved_shapes:
                            shape_el = preserved_shapes.pop(0)
                            # Shape must be in a run
                            run = paragraph.add_run()
                            run._element.append(shape_el)
                        else:
                            # Shape missing/deleted?
                            # Create a placeholder or ignore
                            run = paragraph.add_run("[MISSING SHAPE]")
                            run.font.color.rgb = docx.shared.RGBColor(255, 0, 0)
                        
            # Check HTML Tags
            else:
                lower_tag = tag_content.lower()
                if lower_tag == 'br/':
                    paragraph.add_run().add_break()
                    continue
                elif lower_tag in ['b', 'strong']:
                   active_style['bold'] += -1 if is_closing else 1
                elif lower_tag in ['i', 'em']:
                   active_style['italic'] += -1 if is_closing else 1
                elif lower_tag == 'u':
                   active_style['underline'] += -1 if is_closing else 1
                
        else:
            # Generic Text
            
            # Helper to add run
            def add_styled_run(content):
                run = paragraph.add_run(content)
                if active_style['bold'] > 0: run.bold = True
                if active_style['italic'] > 0: run.italic = True
                if active_style['underline'] > 0: run.underline = True
                if active_style['superscript']: run.font.superscript = True
                if active_style['subscript']: run.font.subscript = True
                
                if 'color' in active_style:
                     try:
                         run.font.color.rgb = docx.shared.RGBColor.from_string(active_style['color'])
                     except:
                         pass # Warning: invalid color ignored
                         
                if active_style['highlight']: 
                    run.font.highlight_color = WD_COLOR_INDEX.YELLOW
            
            # Handle [TAB]
            if "[TAB]" in token:
                parts = token.split("[TAB]")
                for i, part in enumerate(parts):
                    if i > 0:
                        paragraph.add_run().add_tab()
                    if part:
                         add_styled_run(part)
            else:
                add_styled_run(token)

    # Append remaining shapes if any (user deleted tag?)
    if preserved_shapes:
        for shape_el in preserved_shapes:
             run = paragraph.add_run()
             run._element.append(shape_el)


