import shutil
import docx
from docx.api import Document
from lxml import etree
from docx.oxml.ns import qn
from app.logger import get_logger
from .insert import inject_into_container
from .footnotes import inject_footnotes, inject_endnotes

logger = get_logger("Assembler")

def reassemble_docx(original_path: str, output_path: str, segments: list):
    """
    Takes original DOCX and a list of TRANSLATED segments.
    Writes a new DOCX where text is replaced by target_content.
    """
    logger.info(f"Reassembling DOCX: {output_path}")
    
    # 1. Copy file to output path
    shutil.copy(original_path, output_path)
    
    doc = Document(output_path)
    
    # Filter for Shape Segments
    shape_segments = [s for s in segments if s.metadata and s.metadata.get("type") == "shape"]
    shape_map = {} # shape_id -> List[Segments]
    
    for s in shape_segments:
        sid = s.metadata.get("shape_id")
        if not sid: continue
        if sid not in shape_map:
             shape_map[sid] = []
        shape_map[sid].append(s)
        
    # 1. Body
    inject_into_container(doc, {"type": "body"}, segments, shape_map)
    
    # 2. Sections
    for s_idx, section in enumerate(doc.sections):
        if section.header:
            inject_into_container(section.header, {"type": "header", "section_index": s_idx}, segments, shape_map)
        if section.footer:
             inject_into_container(section.footer, {"type": "footer", "section_index": s_idx}, segments, shape_map)

    # 3. Comments (Update comments.xml)
    _inject_comments_stub(doc, segments) # Keeping the stub inline or moving it?

    # 4. Footnotes
    inject_footnotes(doc, segments)

    # 5. Endnotes
    inject_endnotes(doc, segments)

    doc.save(output_path)
    logger.info("Reassembly complete.")

def _inject_comments_stub(doc, segments):
    # Minimal version of comment injection
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
                 
                 for child in list(comment):
                     if child.tag == qn('w:p'):
                        comment.remove(child)
                        
                 wp = etree.SubElement(comment, qn('w:p'))
                 wr = etree.SubElement(wp, qn('w:r'))
                 wt = etree.SubElement(wr, qn('w:t'))
                 wt.text = target_text
                 
                 updated_count += 1
                 
        if updated_count > 0:
            new_xml = etree.tostring(root, encoding='utf-8', standalone=True)
            comments_part._blob = new_xml
            
    except Exception as e:
        logger.error(f"Error updating comments: {e}")
