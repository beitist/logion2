import docx
from docx.api import Document
import docx.shared
from typing import List
import shutil
import re
from docx.enum.text import WD_COLOR_INDEX
from docx.oxml.ns import qn
import copy
from .schemas import SegmentInternal, TagModel

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
    
    active_style = {'bold': 0, 'italic': 0, 'underline': 0, 'highlight': False}
    
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


