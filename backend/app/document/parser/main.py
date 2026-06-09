import docx
import uuid
from docx.api import Document
from .traverse import process_container
from .footnotes import extract_footnotes, extract_endnotes
from app.logger import get_logger
from app.schemas import SegmentInternal

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
            W14_PARA_ID = '{http://schemas.microsoft.com/office/word/2010/wordml}paraId'

            # paraId -> comment id. commentsExtended references comments via the
            # w14:paraId of the comment's paragraphs (one per paragraph, usually
            # the last paragraph carries the commentEx entry).
            para_id_to_cid = {}

            for comment in root.findall('.//w:comment', namespaces):
                cid = comment.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}id')
                # Extract text
                texts = comment.findall('.//w:t', namespaces)
                full_text = "".join([t.text or "" for t in texts])
                # Store as dict with text and done status (default False)
                context["comments_map"][cid] = {"text": full_text, "is_done": False}
                # Record every paragraph's w14:paraId so we can resolve commentEx entries
                for para in comment.findall('.//w:p', namespaces):
                    pid = para.get(W14_PARA_ID)
                    if pid:
                        para_id_to_cid[pid] = cid

        # Check commentsExtended.xml for done status
        comments_ext_part = None
        for rel in part.rels.values():
            if "commentsExtended" in rel.reltype:
                comments_ext_part = rel.target_part
                break

        if comments_ext_part and context["comments_map"]:
            from lxml import etree
            ext_xml = comments_ext_part.blob
            ext_root = etree.fromstring(ext_xml)
            ns = {'w15': 'http://schemas.microsoft.com/office/word/2012/wordml'}
            W15 = 'http://schemas.microsoft.com/office/word/2012/wordml'
            for ce in ext_root.findall('.//w15:commentEx', ns):
                para_id = ce.get('{%s}paraId' % W15)
                is_done = ce.get('{%s}done' % W15) == '1'
                cid = para_id_to_cid.get(para_id)
                if cid and is_done and cid in context["comments_map"]:
                    context["comments_map"][cid]["is_done"] = True
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

    # 4. Comments as separate segments (for translation)
    for cid, cdata in context["comments_map"].items():
        ctext = cdata["text"] if isinstance(cdata, dict) else cdata
        is_done = cdata.get("is_done", False) if isinstance(cdata, dict) else False
        if ctext and ctext.strip():
            comment_seg = SegmentInternal(
                id=str(uuid.uuid4()),
                segment_id=str(uuid.uuid4()),
                source_text=ctext.strip(),
                target_content=None,
                status="draft",
                tags={},
                metadata={
                    "type": "comment",
                    "comment_id": cid,
                    "is_done": is_done
                }
            )
            final_segments.append(comment_seg)

    # 5. Filter empty segments (only whitespace, truly empty, or tag-only)
    import re
    def has_real_content(text):
        """Returns True if text contains actual content beyond just tags/whitespace"""
        if not text:
            return False
        # Remove all tags like <1>, </2>, etc. - single backslash for correct regex
        stripped = re.sub(r'</?\d+>', '', text)
        return bool(stripped.strip())
    
    final_segments = [s for s in final_segments if has_real_content(s.source_text)]

    logger.info(f"Extracted {len(final_segments)} segments.")
    return final_segments
