import docx
from docx.api import Document
import docx.shared
from typing import List
import shutil
import re
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
    
    segment_map = {} # Key -> Segment
    
    # helper for keys
    def make_key(loc):
        # We need a robust key generation based on loc
        # body: type=body, index=...
        # table: type=table, table_index=..., ...
        # header: type=header, section_index=..., p_index=...
        # header table: type=header, sub_type=table, ...
        
        parts = [loc.get("type", "")]
        if loc.get("type") == "body":
            parts.append(str(loc.get("index", "")))
        elif loc.get("type") == "table":
            parts.append(f"{loc.get('table_index')}_{loc.get('row_index')}_{loc.get('cell_index')}_{loc.get('p_index')}")
        elif loc.get("type") in ["header", "footer"]:
            parts.append(str(loc.get("section_index")))
            if loc.get("sub_type") == "table":
                parts.append("table")
                parts.append(f"{loc.get('table_index')}_{loc.get('row_index')}_{loc.get('cell_index')}_{loc.get('p_index')}")
            else:
                parts.append(str(loc.get("p_index")))
        return "_".join(parts)

    for seg in segments:
        if seg.metadata:
            k = make_key(seg.metadata)
            segment_map[k] = seg

    # 1. Body
    _inject_into_container(doc, {"type": "body"}, segment_map)
    
    # 2. Sections
    for s_idx, section in enumerate(doc.sections):
        if section.header:
            _inject_into_container(section.header, {"type": "header", "section_index": s_idx}, segment_map)
        if section.footer:
             _inject_into_container(section.footer, {"type": "footer", "section_index": s_idx}, segment_map)

    doc.save(output_path)

def _inject_into_container(container, base_metadata, segment_map):
    # helper to generate key same as above (should be shared ideally)
    def get_seg(loc):
        parts = [loc.get("type", "")]
        if loc.get("type") == "body":
            parts.append(str(loc.get("index", "")))
        elif loc.get("type") == "table":
            parts.append(f"{loc.get('table_index')}_{loc.get('row_index')}_{loc.get('cell_index')}_{loc.get('p_index')}")
        elif loc.get("type") in ["header", "footer"]:
            parts.append(str(loc.get("section_index")))
            if loc.get("sub_type") == "table":
                parts.append("table")
                parts.append(f"{loc.get('table_index')}_{loc.get('row_index')}_{loc.get('cell_index')}_{loc.get('p_index')}")
            else:
                parts.append(str(loc.get("p_index")))
        k = "_".join(parts)
        return segment_map.get(k)

    # 1. Paragraphs
    for i, para in enumerate(container.paragraphs):
        loc = base_metadata.copy()
        if base_metadata["type"] == "body":
            loc["index"] = i
        else:
            loc["p_index"] = i
            
        seg = get_seg(loc)
        if seg:
            _inject_segment(para, seg)

    # 2. Tables
    for t_idx, table in enumerate(container.tables):
        for r_idx, row in enumerate(table.rows):
            for c_idx, cell in enumerate(row.cells):
                for p_idx, para in enumerate(cell.paragraphs):
                    loc = base_metadata.copy()
                    if base_metadata["type"] == "body":
                         loc["type"] = "table"
                    else:
                         loc["sub_type"] = "table"
                    
                    loc["table_index"] = t_idx
                    loc["row_index"] = r_idx
                    loc["cell_index"] = c_idx
                    loc["p_index"] = p_idx
                    
                    seg = get_seg(loc)
                    if seg:
                        _inject_segment(para, seg)

def _inject_segment(para, segment):
    target_text = segment.target_content
    # Clear existing runs
    para.clear()
    # RE-INJECT
    _inject_tagged_text(para, target_text, segment.tags)

def _inject_tagged_text(paragraph, text: str, tags_map: dict):
    """
    Parses "Text <1>Bold</1>" and creates runs.
    """
    # Tokenize by tags
    # Regex: (<(\d+)>.*?</\2>) matches <1>...</1>
    # Note: \2 because first capture is (\d+) inside the tag
    
    # Better regex: (<(\d+)>)(.*?)(</\2>)
    
    pattern = re.compile(r'(<(\d+)>.*?<\/\2>)')
    
    # Split keeps the delimiters if captured.
    parts = pattern.split(text)
    
    for part in parts:
        if not part:
            continue
            
        # Check if this part is a tag block
        tag_match = re.match(r'<(\d+)>(.*?)<\/\1>', part)
        
        if tag_match:
            tag_id = tag_match.group(1)
            content = tag_match.group(2)
            
            # Special Tag Types
            if tag_id in tags_map:
                tag_info = tags_map[tag_id]
                
                if tag_info.type == "tab":
                    # It's a TAB. Content is likely [TAB]. 
                    # We add a run with a tab.
                    run = paragraph.add_run()
                    run.add_tab()
                elif tag_info.type == "link":
                     # It's a Link. For MVP, we insert text + styling (Blue/Underline).
                     # Real hyperlinks require relationship manipulation which is complex.
                     # We emulate it visually.
                     run = paragraph.add_run(content)
                     run.font.color.rgb = docx.shared.RGBColor(0x05, 0x63, 0xC1) # Typical Blue
                     run.font.underline = True
                elif tag_info.type == "comment":
                    # Ignore comments in export for now? Or insert?
                    # User didn't ask for comments export yet.
                    # Just skip or insert text?
                    # Skip [COMMENT] marker.
                    pass 
                else:
                    # Formatting Tag (Bold, Italic, etc.)
                    run = paragraph.add_run(content)
                    _apply_formatting(run, tag_info)
            else:
                # Unknown tag, just insert content
                paragraph.add_run(content)
        
        elif re.match(r'\d+', part) or re.match(r'</\d+>', part) or re.match(r'<\d+>', part):
             continue
             
        else:
            # Regular text. Check for <br/> literal?
            if "<br/>" in part:
                # Split by <br/>
                sub_parts = part.split("<br/>")
                for i, sp in enumerate(sub_parts):
                    if i > 0:
                        # Add break
                        run = paragraph.add_run()
                        run.add_break()
                    if sp:
                        paragraph.add_run(sp)
            else:
                paragraph.add_run(part)

def _apply_formatting(run, tag_info: TagModel):
    if tag_info.type == "bold":
        run.bold = True
    if tag_info.type == "italic":
        run.italic = True
    if tag_info.type == "underline":
        run.underline = True
