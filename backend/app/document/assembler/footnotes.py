from lxml import etree
import docx
from docx.api import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from .tags import inject_tagged_text

def inject_footnotes(doc: Document, segments: list):
    """
    Updates the footnotes.xml part of the document with translated text.
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
                 
                 for child in list(footnote):
                     footnote.remove(child)
                 
                 wp = docx.oxml.shared.OxmlElement('w:p')
                 footnote.append(wp)
                 
                 pPr = docx.oxml.shared.OxmlElement('w:pPr')
                 wp.append(pPr)
                 
                 pStyle = docx.oxml.shared.OxmlElement('w:pStyle')
                 pStyle.set(qn('w:val'), 'FootnoteText')
                 pPr.append(pStyle)

                 proxy_para = Paragraph(wp, footnotes_part)
                 inject_tagged_text(proxy_para, target_text, seg.tags)
                 
                 # Prepend reference
                 ref_run = etree.Element(qn('w:r'))
                 ref_rPr = etree.SubElement(ref_run, qn('w:rPr'))
                 ref_style = etree.SubElement(ref_rPr, qn('w:rStyle'))
                 ref_style.set(qn('w:val'), 'FootnoteReference')
                 etree.SubElement(ref_run, qn('w:footnoteRef'))
                 
                 if len(wp) > 0 and wp[0].tag == qn('w:pPr'):
                     wp.insert(1, ref_run)
                 else:
                     wp.insert(0, ref_run)

                 updated_count += 1
                 
        if updated_count > 0:
            new_xml = etree.tostring(root, encoding='utf-8', standalone=True)
            footnotes_part._blob = new_xml
            
    except Exception as e:
        print(f"Error updating footnotes: {e}")

def inject_endnotes(doc: Document, segments: list):
    """
    Updates the endnotes.xml part of the document with translated text.
    """
    endnote_segs = {s.metadata["endnote_id"]: s for s in segments if s.metadata.get("type") == "endnote"}
    
    if not endnote_segs:
        return
        
    try:
        part = doc.part
        endnotes_part = None
        for rel in part.rels.values():
             if "endnotes" in rel.reltype:
                 endnotes_part = rel.target_part
                 break
                 
        if not endnotes_part:
            return
            
        xml_data = endnotes_part.blob
        root = etree.fromstring(xml_data)
        namespaces = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        
        updated_count = 0
        
        for endnote in root.findall('.//w:endnote', namespaces):
            eid = endnote.get(qn('w:id'))
            if eid in endnote_segs:
                 seg = endnote_segs[eid]
                 target_text = seg.target_content if seg.target_content else seg.source_text
                 
                 for child in list(endnote):
                     endnote.remove(child)
                 
                 wp = docx.oxml.shared.OxmlElement('w:p')
                 endnote.append(wp)
                 
                 pPr = docx.oxml.shared.OxmlElement('w:pPr')
                 wp.append(pPr)
                 
                 pStyle = docx.oxml.shared.OxmlElement('w:pStyle')
                 pStyle.set(qn('w:val'), 'EndnoteText')
                 pPr.append(pStyle)
                 
                 proxy_para = Paragraph(wp, endnotes_part)
                 inject_tagged_text(proxy_para, target_text, seg.tags)
                 
                 ref_run = etree.Element(qn('w:r'))
                 ref_rPr = etree.SubElement(ref_run, qn('w:rPr'))
                 ref_style = etree.SubElement(ref_rPr, qn('w:rStyle'))
                 ref_style.set(qn('w:val'), 'EndnoteReference')
                 etree.SubElement(ref_run, qn('w:endnoteRef'))
                 
                 if len(wp) > 0 and wp[0].tag == qn('w:pPr'):
                     wp.insert(1, ref_run)
                 else:
                     wp.insert(0, ref_run)

                 updated_count += 1
                 
        if updated_count > 0:
            new_xml = etree.tostring(root, encoding='utf-8', standalone=True)
            endnotes_part._blob = new_xml
            
    except Exception as e:
        print(f"Error updating endnotes: {e}")
