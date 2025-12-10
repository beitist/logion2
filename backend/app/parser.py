import docx
from docx.api import Document
from typing import List, Tuple, Dict
import uuid
import re

from .schemas import SegmentInternal, TagModel

def parse_docx(file_path: str) -> List[SegmentInternal]:
    """
    Parses a DOCX file and returns a list of SegmentInternal objects.
    Each paragraph is treated as a segment (simplification for MVP).
    """
    doc = Document(file_path)
    segments = []

    # 1. Body
    segments.extend(_process_container(doc, {"type": "body"}))

    # 2. Key Sections (Headers/Footers)
    for s_idx, section in enumerate(doc.sections):
        # Header
        if section.header:
             segments.extend(_process_container(section.header, {
                 "type": "header", 
                 "section_index": s_idx
             }))
        # Footer
        if section.footer:
             segments.extend(_process_container(section.footer, {
                 "type": "footer", 
                 "section_index": s_idx
             }))
    
    return segments

def _process_container(container, base_metadata: dict) -> List[SegmentInternal]:
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
            
        segment = _process_paragraph(para, loc)
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
                    
                    segment = _process_paragraph(para, loc)
                    if segment:
                        container_segments.append(segment)

    return container_segments

def _process_paragraph(para, location: dict) -> SegmentInternal:
    """
    Converts a docx Paragraph object into a SegmentInternal with tags.
    """
    source_text_parts = []
    tags = {}
    tag_counter = 1

    for run in para.runs:
        current_tags = _extract_tags(run)
        
        text = run.text
        if not text:
            continue

        if current_tags:
            # If run has relevant formatting, wrap it in a tag
            # For MVP: we treat the whole run as one tag block if it has ANY format.
            # Real world: might have multiple formats. We flatten to single ID for now.
            
            # Use the first extracted tag type as dominant, or combine?
            # Let's map tag_id -> TagModel
            
            # Optimization: Group identical consecutive runs? (Not for step 1)

            tag_id = str(tag_counter)
            tag_counter += 1
            
            # Store the simplified tag info. 
            # If multiple styles (Bold + Italic), we might need a composite type or list.
            # Spec says: "1": { "type": "bold" }
            # Let's check what we have.
            
            # Simple approach: If bold, type='bold'. If italic, type='italic'. 
            # If both, we might need nested tags? Or a 'style' tag?
            # Specs says: <1>...<1>.
            # Let's stick to: Create a tag entry for this run.
            
            # Merging attributes
            combined_type = "+".join([t.type for t in current_tags])
            
            tags[tag_id] = TagModel(
                type=combined_type,
                xml_attributes={} # Placeholder for real XML extraction later
            )
            
            source_text_parts.append(f"<{tag_id}>{text}</{tag_id}>")
        else:
            source_text_parts.append(text)

    # If no text after processing (e.g. only images), return None
    full_text = "".join(source_text_parts)
    if not full_text.strip():
        return None

    return SegmentInternal(
        segment_id=str(uuid.uuid4()),
        source_text=full_text,
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
