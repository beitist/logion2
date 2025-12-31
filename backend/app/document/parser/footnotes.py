from docx.oxml.ns import qn
from lxml import etree
from .traverse import process_paragraph

def extract_footnotes(doc, context):
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
             # Skip separator/continuation
             ftype = footnote.get(qn('w:type'))
             if ftype in ['separator', 'continuationSeparator']:
                 continue
                 
             # A footnote can have multiple paragraphs
             for i, para in enumerate(footnote.findall('.//w:p', namespaces)):
                 # We treat footnote as a single block usually, or per-para?
                 # Existing logic seemed per-para?
                 # Let's map it.
                 
                 loc = {
                     "type": "footnote",
                     "footnote_id": fid,
                     "p_index": i
                 }
                 
                 # Recurse
                 segs = process_paragraph(para, loc, context)
                 segments.extend(segs)
                 
    except Exception as e:
        print(f"Error parsing footnotes: {e}")
        
    return segments

def extract_endnotes(doc, context):
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
             if etype in ['separator', 'continuationSeparator']:
                 continue
                 
             for i, para in enumerate(endnote.findall('.//w:p', namespaces)):
                 loc = {
                     "type": "endnote",
                     "endnote_id": eid,
                     "p_index": i
                 }
                 segs = process_paragraph(para, loc, context)
                 segments.extend(segs)
                 
    except Exception as e:
        print(f"Error parsing endnotes: {e}")
        
    return segments
