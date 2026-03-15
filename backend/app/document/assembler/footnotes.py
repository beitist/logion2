import re
from lxml import etree
import docx
from docx.api import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from .tags import inject_tagged_text

_URL_RE = re.compile(r'https?://[^\s<>"]+|www\.[^\s<>"]+')
_HYPERLINK_RELTYPE = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink'
_W_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'


def _collect_original_hyperlinks(note_el, notes_part):
    """Collect original hyperlink URLs (ordered list) before clearing the note."""
    ns = {'w': _W_NS}
    hyperlinks = []
    for hl in note_el.findall('.//w:hyperlink', ns):
        rid = hl.get(qn('r:id'))
        if not rid:
            continue
        try:
            url = notes_part.rels[rid].target_ref
        except (KeyError, AttributeError):
            continue
        text = ''.join(t.text or '' for t in hl.findall('.//w:t', ns))
        if url:
            hyperlinks.append({'url': url, 'text': (text or '').strip()})
    return hyperlinks


def _restore_hyperlinks(wp, notes_part, original_hyperlinks):
    """Post-process: restore hyperlinks in the rebuilt paragraph.

    Strategy:
    1. If inject_tagged_text already created w:hyperlink elements (from preserved
       link tags), do nothing — they already have correct r:id references.
    2. Otherwise, match runs by text: first try exact text match against original
       hyperlink text, then try URL-pattern detection.
    3. Final fallback: if the original had exactly one hyperlink covering (almost)
       all text and no hyperlinks were created yet, wrap ALL content runs in it.
    """
    if not original_hyperlinks:
        return

    # Check if inject_tagged_text already created hyperlinks
    existing = wp.findall(qn('w:hyperlink'))
    if existing:
        return  # Already handled via link tags

    # Build text→url map from originals
    text_to_url = {h['text']: h['url'] for h in original_hyperlinks if h['text']}

    # Collect content runs (skip pPr, footnoteRef runs)
    content_runs = []
    for run in wp.findall(qn('w:r')):
        # Skip footnote/endnote reference runs
        rPr = run.find(qn('w:rPr'))
        if rPr is not None:
            rStyle = rPr.find(qn('w:rStyle'))
            if rStyle is not None:
                val = rStyle.get(qn('w:val'), '')
                if val in ('FootnoteReference', 'EndnoteReference'):
                    continue
        t_el = run.find(qn('w:t'))
        if t_el is not None and t_el.text:
            content_runs.append(run)

    matched_any = False

    # Pass 1: exact text match or URL pattern match (per-run)
    for run in list(content_runs):
        t_el = run.find(qn('w:t'))
        text = t_el.text.strip()

        url = text_to_url.get(text)
        if not url and _URL_RE.fullmatch(text):
            url = text if text.startswith('http') else f'https://{text}'

        if url:
            _wrap_run_in_hyperlink(run, url, notes_part)
            matched_any = True

    if matched_any:
        return

    # Pass 2 (fallback): original had exactly one hyperlink → wrap all content runs
    if len(original_hyperlinks) == 1 and content_runs:
        url = original_hyperlinks[0]['url']
        rid = notes_part.relate_to(url, _HYPERLINK_RELTYPE, is_external=True)
        hyperlink = docx.oxml.shared.OxmlElement('w:hyperlink')
        hyperlink.set(qn('r:id'), rid)

        # Insert hyperlink at the position of the first content run
        first_run = content_runs[0]
        parent = first_run.getparent()
        idx = list(parent).index(first_run)

        # Move all content runs inside the hyperlink
        for run in content_runs:
            parent.remove(run)
            _apply_hyperlink_style(run)
            hyperlink.append(run)

        parent.insert(idx, hyperlink)


def _wrap_run_in_hyperlink(run, url, notes_part):
    """Wrap a single run in a w:hyperlink element."""
    parent = run.getparent()
    if parent is not None and parent.tag == qn('w:hyperlink'):
        return

    rid = notes_part.relate_to(url, _HYPERLINK_RELTYPE, is_external=True)
    hyperlink = docx.oxml.shared.OxmlElement('w:hyperlink')
    hyperlink.set(qn('r:id'), rid)

    idx = list(parent).index(run)
    parent.remove(run)
    _apply_hyperlink_style(run)
    hyperlink.append(run)
    parent.insert(idx, hyperlink)


def _apply_hyperlink_style(run):
    """Add Hyperlink rStyle to a run."""
    rPr = run.find(qn('w:rPr'))
    if rPr is None:
        rPr = docx.oxml.shared.OxmlElement('w:rPr')
        run.insert(0, rPr)
    rStyle = docx.oxml.shared.OxmlElement('w:rStyle')
    rStyle.set(qn('w:val'), 'Hyperlink')
    rPr.insert(0, rStyle)


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
        namespaces = {'w': _W_NS}

        updated_count = 0

        for footnote in root.findall('.//w:footnote', namespaces):
             fid = footnote.get(qn('w:id'))
             if fid in footnote_segs:
                 seg = footnote_segs[fid]
                 target_text = seg.target_content if seg.target_content is not None else seg.source_text

                 # Collect original hyperlinks before clearing
                 orig_hyperlinks = _collect_original_hyperlinks(footnote, footnotes_part)

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

                 # Restore hyperlinks (fallback for segments without link tags)
                 _restore_hyperlinks(wp, footnotes_part, orig_hyperlinks)

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
        namespaces = {'w': _W_NS}

        updated_count = 0

        for endnote in root.findall('.//w:endnote', namespaces):
            eid = endnote.get(qn('w:id'))
            if eid in endnote_segs:
                 seg = endnote_segs[eid]
                 target_text = seg.target_content if seg.target_content else seg.source_text

                 # Collect original hyperlinks before clearing
                 orig_hyperlinks = _collect_original_hyperlinks(endnote, endnotes_part)

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

                 # Restore hyperlinks (fallback for segments without link tags)
                 _restore_hyperlinks(wp, endnotes_part, orig_hyperlinks)

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
