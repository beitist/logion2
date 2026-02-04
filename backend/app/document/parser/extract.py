import re
import uuid
from docx.oxml.ns import qn
from app.schemas import TagModel
from ..utils import NAMESPACES

def extract_tags(run_element) -> list[TagModel]:
    """
    Inspects a run XML ELEMENT for formatting.
    Returns a list of detected TagModels.
    """
    found = []
    
    rPr = run_element.find(qn('w:rPr'))
    if rPr is None:
        return found
        
    # Bold
    if rPr.find(qn('w:b')) is not None:
         found.append(TagModel(type="bold"))
         
    # Italic
    if rPr.find(qn('w:i')) is not None:
        found.append(TagModel(type="italic"))
        
    # Underline
    if rPr.find(qn('w:u')) is not None:
        found.append(TagModel(type="underline"))
        
    # Superscript / Subscript
    vAlign = rPr.find(qn('w:vertAlign'))
    if vAlign is not None:
        val = vAlign.get(qn('w:val'))
        if val == 'superscript':
            found.append(TagModel(type="superscript"))
        elif val == 'subscript':
            found.append(TagModel(type="subscript"))
            
    # Color
    color = rPr.find(qn('w:color'))
    if color is not None:
        val = color.get(qn('w:val'))
        if val and val != 'auto' and val != '000000':
            found.append(TagModel(type="color", xml_attributes={"color": val}))

    # Highlighting
    highlight = rPr.find(qn('w:highlight'))
    if highlight is not None:
        val = highlight.get(qn('w:val'))
        found.append(TagModel(type="highlight", xml_attributes={"color": str(val)}))

    # Font Size
    sz = rPr.find(qn('w:sz'))
    if sz is not None:
        val = sz.get(qn('w:val'))
        if val:
            found.append(TagModel(type="size", xml_attributes={"val": str(val)}))
            
    # Font Family
    rFonts = rPr.find(qn('w:rFonts'))
    if rFonts is not None:
        font_name = rFonts.get(qn('w:ascii')) or rFonts.get(qn('w:hAnsi')) or rFonts.get(qn('w:eastAsia'))
        if font_name:
             found.append(TagModel(type="font", xml_attributes={"name": str(font_name)}))

    # Strikethrough
    strike = rPr.find(qn('w:strike'))
    if strike is not None:
        val = strike.get(qn('w:val'))
        if val not in ['0', 'false', 'off']:
            found.append(TagModel(type="strike"))
            
    # Small Caps
    smallCaps = rPr.find(qn('w:smallCaps'))
    if smallCaps is not None:
        val = smallCaps.get(qn('w:val'))
        if val not in ['0', 'false', 'off']:
            found.append(TagModel(type="smallCaps"))

    # All Caps
    caps = rPr.find(qn('w:caps'))
    if caps is not None:
        val = caps.get(qn('w:val'))
        if val not in ['0', 'false', 'off']:
            found.append(TagModel(type="caps"))

    return found

def get_run_text(run_element) -> str:
    """
    Extracts text from a run, handling <w:t>, <w:br>, <w:tab>.
    """
    text = ""
    for child in run_element:
        tag = child.tag
        if tag == qn('w:t'):
             text += child.text or ""
        elif tag == qn('w:br'):
             text += "\n"
        elif tag == qn('w:tab'):
             text += "\t"
        elif tag == qn('w:cr'):
             text += "\n"
    return text

def get_run_signature(run_element) -> tuple:
    """
    Returns a hashable signature of meaningful formatting properties.
    """
    rPr = run_element.find(qn('w:rPr'))
    if rPr is None:
        return None 
        
    sig = []
    
    # 1. Boolean Toggles
    for tag in ['b', 'i', 'u', 'strike', 'smallCaps', 'caps', 'vanish', 'webHidden']:
        el = rPr.find(qn(f'w:{tag}'))
        if el is not None:
            val = el.get(qn('w:val'))
            state = True
            if val in ['0', 'false', 'off']: state = False
            sig.append((tag, state))
    
    # 2. Valued Properties
    valued_props = [
        ('color', 'val'),
        ('highlight', 'val'),
        ('sz', 'val'),
        ('rFonts', 'ascii'),
        ('vertAlign', 'val'),
        ('shd', 'fill'), 
    ]
    
    for tag, attr in valued_props:
        el = rPr.find(qn(f'w:{tag}'))
        if el is not None:
            val = el.get(qn(f'w:{attr}'))
            if val:
                sig.append((tag, attr, val))
                
    return tuple(sorted(sig))

def is_pure_text_run(run_element) -> bool:
    """
    Returns True if the run contains only text-like elements.
    """
    allowed = [qn('w:t'), qn('w:br'), qn('w:tab'), qn('w:cr'), qn('w:rPr')]
    for child in run_element:
        if child.tag not in allowed:
            return False
    return True

# Circular dependency: _process_paragraph needs traverse?
# No, shape processing calls _process_paragraph recursively.
# We will need to inject the traversal function or import specific module functions inside logic.
# For now, let's keep handle_shape_element generic or passing context that has the function.

def handle_shape_element(shape_element, add_tag_func, context, process_para_func) -> str:
    """
    Handles drawing/shape elements. For textboxes, extracts text as segments.
    For pure images (no textbox), returns empty string to preserve original element.
    """
    ns = NAMESPACES
    txbx_contents = shape_element.findall('.//w:txbxContent', ns)
    
    # If no textbox content, this is a pure image - don't create placeholder
    # This preserves the original image in the document during reassembly
    if not txbx_contents:
        return ""  # Empty string = no placeholder, image preserved
    
    # Has textbox - extract text content
    shape_id = str(uuid.uuid4())
    
    for txbx in txbx_contents:
        for i, para in enumerate(txbx.findall('.//w:p', ns)):
            loc = {
                "type": "shape",
                "shape_id": shape_id,
                "p_index": i
            }
            
            sub_segments = process_para_func(para, loc, context)
            if sub_segments:
                context["extra_segments"].extend(sub_segments)

    # Create tag for textbox (not pure image)
    shape_tag = TagModel(type="shape", content="[TEXTBOX]", xml_attributes={"id": shape_id})
    tid = add_tag_func(shape_tag)
    return f"<{tid}></{tid}>"

def process_run_element(run_element, add_tag_func, context, process_para_func, text_override=None) -> str:
    """
    Helper to process a w:r element.
    """
    
    def process_text_for_urls(txt):
        if not txt: return ""
        url_pattern = re.compile(r'(https?://[^\s<>"]+|www\.[^\s<>"]+)')
        parts = url_pattern.split(txt)
        res = ""
        if len(parts) > 1:
            for part in parts:
                if url_pattern.match(part):
                        l_tag = TagModel(type="link", xml_attributes={"is_hyperlink": True})
                        l_tid = add_tag_func(l_tag)
                        res += f"<{l_tid}>{part}</{l_tid}>"
                elif part:
                        res += part
            return res
        else:
            return txt

    final_text = text_override if text_override is not None else get_run_text(run_element)
    
    if not final_text:
        return ""
        
    extracted_tags = extract_tags(run_element)
    
    active_ids = []
    full_run_text = ""
    
    if extracted_tags:
        for t in extracted_tags:
            tid = add_tag_func(t)
            full_run_text += f"<{tid}>"
            active_ids.append(tid)
            
    run_content = ""
    
    if text_override is not None:
        run_content = process_text_for_urls(text_override)
    else:
        for child in run_element:
            tag_name = child.tag
            
            if tag_name == qn('w:t'):
                run_content += process_text_for_urls(child.text or "")
                
            elif tag_name == qn('w:tab'):
                 run_content += "\t"
                 
            elif tag_name == qn('w:br') or tag_name == qn('w:cr'):
                 run_content += "\n"
                 
            elif tag_name == qn('w:commentReference'):
                cid = child.get(qn('w:id'))
                was_handled = "_handled_ranges" in context and cid in context["_handled_ranges"]
                is_active = "_active_ranges" in context and cid in context["_active_ranges"]
                
                if not was_handled and not is_active and cid and context["comments_map"].get(cid):
                    ctext = context["comments_map"][cid]
                    com_tag = TagModel(type="comment", content=ctext, ref_id=cid)
                    tid = add_tag_func(com_tag)
                    run_content += f"<{tid}></{tid}>"

            elif tag_name == qn('w:drawing') or tag_name == qn('w:pict'):
                 run_content += handle_shape_element(child, add_tag_func, context, process_para_func)

            elif tag_name == "{http://schemas.openxmlformats.org/markup-compatibility/2006}AlternateContent":
                 mc_ns = NAMESPACES
                 choice = child.find('mc:Choice', mc_ns)
                 fallback = child.find('mc:Fallback', mc_ns)
                 target_el = None
                 if choice is not None:
                     target_el = choice.find('.//w:drawing', mc_ns)
                 if target_el is None and fallback is not None:
                     target_el = fallback.find('.//w:pict', mc_ns)
                 
                 if target_el is not None:
                     run_content += handle_shape_element(target_el, add_tag_func, context, process_para_func)

            elif tag_name == qn('w:footnoteReference'):
                fid = child.get(qn('w:id'))
                ftag = TagModel(type="footnote", xml_attributes={"id": fid})
                tid = add_tag_func(ftag)
                run_content += f"<{tid}></{tid}>"

            elif tag_name == qn('w:endnoteReference'):
                eid = child.get(qn('w:id'))
                etag = TagModel(type="endnote", xml_attributes={"id": eid})
                tid = add_tag_func(etag)
                run_content += f"<{tid}></{tid}>"

    full_run_text += run_content
    
    for tid in reversed(active_ids):
        full_run_text += f"</{tid}>"
        
    return full_run_text
