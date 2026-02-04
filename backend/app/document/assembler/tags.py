import re
import copy
import docx
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from app.logger import get_logger

logger = get_logger("Assembler")

def inject_tagged_text(paragraph: Paragraph, text: str, tags_map: dict, shape_map=None):
    """
    Parses 'text' containing custom tags and reconstructs the paragraph with formatting.
    Preserves w:drawing and w:pict elements found in the paragraph before clearing.
    """
    p_element = paragraph._element
    
    # 1. Preserve Shapes (Drawings/Picts) before clearing
    preserved_shapes = []
    
    for child in p_element.iter():
        if child.tag == "{http://schemas.openxmlformats.org/markup-compatibility/2006}AlternateContent":
             try:
                 preserved_shapes.append(copy.deepcopy(child))
             except Exception as e:
                 logger.warning(f"Failed to preserve AlternateContent: {e}")
                 
        elif child.tag == qn('w:drawing') or child.tag == qn('w:pict'):
            # Check if inside AlternateContent/Choice/Fallback
            parent = child.getparent()
            
            mc_ns = 'http://schemas.openxmlformats.org/markup-compatibility/2006'
            is_wrapped = False
            if parent is not None:
                if parent.tag == f"{{{mc_ns}}}Choice" or parent.tag == f"{{{mc_ns}}}Fallback":
                    is_wrapped = True
            
            if not is_wrapped:
                try:
                    preserved_shapes.append(copy.deepcopy(child))
                except Exception as e:
                    logger.warning(f"Failed to preserve shape: {e}")

    # 2. Clear existing content (Safe Mode)
    for child in list(p_element):
        if child.tag == qn('w:pPr'):
            continue
        p_element.remove(child)

    # Tokenize
    tokens = re.split(r'(<[^>]+>)', text)
    
    active_style = {'bold': 0, 'italic': 0, 'underline': 0, 'highlight': False, 'superscript': False, 'subscript': False, 'strike': False, 'smallCaps': False, 'caps': False}
    
    # Helper to process shape elements recursively
    def process_shape_element(element, sid):
        ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        txbx_contents = element.findall('.//w:txbxContent', ns)
        
        global_p_idx = 0
        for txbx in txbx_contents:
             paras = txbx.findall('.//w:p', ns)
             for para in paras:
                 # Fetch segments for this shape/p_index
                 if sid in shape_map:
                     t_segs = shape_map[sid]
                     matching_segs = [s for s in t_segs if s.metadata.get("p_index") == global_p_idx]
                     
                     if matching_segs:
                         matching_segs.sort(key=lambda x: x.metadata.get("sub_index", 0))
                         
                         full_text = ""
                         combined_tags = {}
                         for s in matching_segs:
                             content = s.target_content if s.target_content is not None else s.source_text
                             full_text += content
                             if s.tags:
                                 combined_tags.update(s.tags)
                         
                         full_text = re.sub(r'</(\d+)><\1>', '', full_text)

                         proxy_p = Paragraph(para, None)
                         inject_tagged_text(proxy_p, full_text, combined_tags, None)
                         
                 global_p_idx += 1
                 
        # Recursive check for wrapper shapes inside
        # (Though usually textboxes contain paragraphs, not more shapes directly, unless nested)
        
        # If AlternatContent wrapper, we need to drill down?
        # The element passed here IS the child of AlternateContent usually, or the Drawing/Pict itself.
        if element.tag == "{http://schemas.openxmlformats.org/markup-compatibility/2006}AlternateContent":
             mc_ns = {'mc': 'http://schemas.openxmlformats.org/markup-compatibility/2006'}
             choice = element.find('mc:Choice', mc_ns)
             if choice is not None:
                 for child in choice:
                     process_shape_element(child, sid)
             fallback = element.find('mc:Fallback', mc_ns)
             if fallback is not None:
                 for child in fallback:
                     process_shape_element(child, sid)
    
    # Helper to add run
    def add_styled_run(content):
        # context: where to add run?
        # If inside hyperlink, add to hyperlink_el
        if 'hyperlink_el' in active_style:
            parent = active_style['hyperlink_el']
            
            run = docx.oxml.shared.OxmlElement('w:r')
            t = docx.oxml.shared.OxmlElement('w:t')
            if content:
                 t.set(qn('xml:space'), 'preserve')
            t.text = content
            
            rPr = docx.oxml.shared.OxmlElement('w:rPr')
            
            # Hyperlink Style
            rStyle = docx.oxml.shared.OxmlElement('w:rStyle')
            rStyle.set(qn('w:val'), 'Hyperlink')
            rPr.append(rStyle)
            
            color = docx.oxml.shared.OxmlElement('w:color')
            color.set(qn('w:val'), '0563C1') 
            rPr.append(color)
            
            u = docx.oxml.shared.OxmlElement('w:u')
            u.set(qn('w:val'), 'single')
            rPr.append(u)
            
            # Apply other styles
            if active_style['bold'] > 0: 
                rPr.append(docx.oxml.shared.OxmlElement('w:b'))
            if active_style['italic'] > 0: 
                rPr.append(docx.oxml.shared.OxmlElement('w:i'))
                
            run.append(rPr)
            run.append(t)
            parent.append(run)
            
        else:
            # Standard Paragraph Run
            run = paragraph.add_run(content)
            
            if active_style['bold'] > 0: run.bold = True
            if active_style['italic'] > 0: run.italic = True
            if active_style['underline'] > 0: run.underline = True
            
            if active_style['superscript']:
                run.font.superscript = True
            if active_style['subscript']:
                run.font.subscript = True
                
            if active_style['strike']:
                run.font.strike = True
            if active_style['smallCaps']:
                run.font.small_caps = True
            if active_style['caps']:
                run.font.all_caps = True
                
            if 'color' in active_style:
                try:
                    run.font.color.rgb = docx.shared.RGBColor.from_string(active_style['color'])
                except: pass
                
            if 'size' in active_style:
                try:
                    # w:sz is half-points. python-docx takes Pt.
                    # so val 24 = 12pt.
                    # run.font.size expects Length (Pt).
                    # Pt(12) = 152400 EMU.
                    # We can set element directly or use Pt
                    pt_val = int(active_style['size']) / 2
                    run.font.size = docx.shared.Pt(pt_val)
                except: pass

            if 'font' in active_style:
                run.font.name = active_style['font']
                
            if active_style['highlight'] is not False:
                # Highlight logic
                # docx.enum.text.WD_COLOR_INDEX
                # If specific color?
                if active_style['highlight'] is True:
                     run.font.highlight_color = docx.enum.text.WD_COLOR_INDEX.YELLOW
                elif isinstance(active_style['highlight'], str):
                     # Try to map common colors
                     # For now default to yellow
                     run.font.highlight_color = docx.enum.text.WD_COLOR_INDEX.YELLOW
    
    for token in tokens:
        if not token:
            continue
            
        if token.startswith("<") and token.endswith(">"):
            tag_content = token[1:-1]
            is_closing = tag_content.startswith("/")
            if is_closing:
                tag_content = tag_content[1:]
                
            if tag_content.isdigit():
                tid = tag_content
                tag = tags_map.get(tid)
                if tag:
                    if tag.type == 'bold': active_style['bold'] += -1 if is_closing else 1
                    elif tag.type == 'italic': active_style['italic'] += -1 if is_closing else 1
                    elif tag.type == 'underline': active_style['underline'] += -1 if is_closing else 1
                    elif tag.type == 'superscript': active_style['superscript'] = not is_closing
                    elif tag.type == 'subscript': active_style['subscript'] = not is_closing
                    elif tag.type == 'strike': active_style['strike'] = not is_closing
                    elif tag.type == 'smallCaps': active_style['smallCaps'] = not is_closing
                    elif tag.type == 'caps': active_style['caps'] = not is_closing
                    
                    elif tag.type == 'color':
                        if is_closing: active_style.pop('color', None)
                        else: 
                             if tag.xml_attributes and 'color' in tag.xml_attributes:
                                 active_style['color'] = tag.xml_attributes['color']
                                 
                    elif tag.type == 'size':
                         if is_closing: active_style.pop('size', None)
                         else:
                             if tag.xml_attributes and 'val' in tag.xml_attributes:
                                 active_style['size'] = tag.xml_attributes['val']
                                 
                    elif tag.type == 'font':
                         if is_closing: active_style.pop('font', None)
                         else:
                             if tag.xml_attributes and 'name' in tag.xml_attributes:
                                 active_style['font'] = tag.xml_attributes['name']

                    elif tag.type == 'comment': active_style['highlight'] = not is_closing
                    elif tag.type == 'highlight':
                        if is_closing: active_style['highlight'] = False
                        else: active_style['highlight'] = True # Simplify color mapping

                    elif tag.type == 'shape' and not is_closing:
                        if preserved_shapes:
                            shape_el = preserved_shapes.pop(0)
                            
                            # Injection into Textbox?
                            if shape_map and tag.xml_attributes and 'id' in tag.xml_attributes:
                                sid = tag.xml_attributes['id']
                                process_shape_element(shape_el, sid)

                            run = paragraph.add_run()
                            run._element.append(shape_el)
                        else:
                            run = paragraph.add_run("[MISSING SHAPE]")
                            run.font.color.rgb = docx.shared.RGBColor(255, 0, 0)
                            
                    elif tag.type == 'footnote' and not is_closing:
                        run = paragraph.add_run()
                        rPr = docx.oxml.shared.OxmlElement('w:rPr')
                        rStyle = docx.oxml.shared.OxmlElement('w:rStyle')
                        rStyle.set(qn('w:val'), 'FootnoteReference')
                        rPr.append(rStyle)
                        run._element.append(rPr)
                        
                        ref = docx.oxml.shared.OxmlElement('w:footnoteReference')
                        ref.set(qn('w:id'), tag.xml_attributes['id'])
                        run._element.append(ref)

                    elif tag.type == 'endnote' and not is_closing:
                        run = paragraph.add_run()
                        rPr = docx.oxml.shared.OxmlElement('w:rPr')
                        rStyle = docx.oxml.shared.OxmlElement('w:rStyle')
                        rStyle.set(qn('w:val'), 'EndnoteReference')
                        rPr.append(rStyle)
                        run._element.append(rPr)
                        
                        ref = docx.oxml.shared.OxmlElement('w:endnoteReference')
                        ref.set(qn('w:id'), tag.xml_attributes['id'])
                        run._element.append(ref)
                        
                    elif tag.type == 'link':
                         if is_closing:
                             if 'hyperlink_el' in active_style: active_style.pop('hyperlink_el')
                         else:
                             hyplink = docx.oxml.shared.OxmlElement('w:hyperlink')
                             if tag.xml_attributes and 'rid' in tag.xml_attributes:
                                 hyplink.set(qn('r:id'), tag.xml_attributes['rid'])
                             paragraph._element.append(hyplink)
                             active_style['hyperlink_el'] = hyplink

            else:
                # HTML Tags
                lower_tag = tag_content.lower()
                if lower_tag == 'br/':
                    paragraph.add_run().add_break()
                    continue
                elif lower_tag in ['b', 'strong']: active_style['bold'] += -1 if is_closing else 1
                elif lower_tag in ['i', 'em']: active_style['italic'] += -1 if is_closing else 1
                elif lower_tag == 'u': active_style['underline'] += -1 if is_closing else 1
        else:
            add_styled_run(token)

    # 3. Append any remaining preserved shapes (images without explicit <shape> tag)
    # This ensures images are not lost when parser returns empty string for pure images
    for remaining_shape in preserved_shapes:
        run = paragraph.add_run()
        run._element.append(remaining_shape)
