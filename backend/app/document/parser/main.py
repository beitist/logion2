import docx
from docx.api import Document
from .traverse import process_container
from .footnotes import extract_footnotes, extract_endnotes
from app.logger import get_logger

logger = get_logger("Parser")

from .excel import parse_xlsx

def parse_document(file_path: str, segmentation_func=None, source_lang="en"):
    """
    Dispatches to the appropriate parser based on file extension.
    """
    logger.info(f"Dispatching parse for: {file_path}")
    ext = file_path.split(".")[-1].lower()
    if ext in ["docx", "doc"]:
        return _parse_docx(file_path, segmentation_func, source_lang)
    elif ext in ["xlsx", "xls"]:
        return parse_xlsx(file_path, segmentation_func, source_lang)
    else:
        # Fallback or error? For now, try docx as default or raise
        logger.warning(f"Unsupported extension {ext}, attempting DOCX parse.")
        return _parse_docx(file_path, segmentation_func, source_lang)

def _parse_docx(file_path: str, segmentation_func=None, source_lang="en"):
    """
    Parses a DOCX file and extracts segments with tags for formatting, hyperlinks, and comments.
    """
    logger.info(f"Parsing DOCX: {file_path}")
    
    doc = Document(file_path)
    final_segments = []
    
    # Context State
    context = {
        "comments_map": {}, 
        "_handled_ranges": set(),
        "_active_ranges": set(),
        "extra_segments": [] # Shapes, textboxes
    }
    
    # 0. Pre-Extract Comments
    try:
        part = doc.part
        comments_part = None
        for rel in part.rels.values():
             if "comments" in rel.reltype and not "commentsExtended" in rel.reltype and not "commentsIds" in rel.reltype:
                 comments_part = rel.target_part
                 break
        
        if comments_part:
            from lxml import etree
            xml_data = comments_part.blob
            root = etree.fromstring(xml_data)
            namespaces = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            
            for comment in root.findall('.//w:comment', namespaces):
                cid = comment.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}id')
                # Extract text
                texts = comment.findall('.//w:t', namespaces)
                full_text = "".join([t.text or "" for t in texts])
                context["comments_map"][cid] = full_text
    except Exception as e:
        logger.warning(f"Failed to extract comments: {e}")

    # 1. Body & Sections
    # Body
    body_meta = {"type": "body"}
    final_segments.extend(process_container(doc, body_meta, context))
    
    # Headers/Footers
    for s_idx, section in enumerate(doc.sections):
        if section.header:
            h_meta = {"type": "header", "section_index": s_idx}
            final_segments.extend(process_container(section.header, h_meta, context))
        if section.footer:
            f_meta = {"type": "footer", "section_index": s_idx}
            final_segments.extend(process_container(section.footer, f_meta, context))

    # 2. Footnotes & Endnotes
    final_segments.extend(extract_footnotes(doc, context))
    final_segments.extend(extract_endnotes(doc, context))
    
    # 3. Extra Segments (Shapes/Textboxes captured during traversal)
    if context["extra_segments"]:
        final_segments.extend(context["extra_segments"])

    logger.info(f"Extracted {len(final_segments)} segments.")
    return final_segments
