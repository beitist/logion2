from docx.oxml.ns import qn
import re
import pysbd
from typing import List

# Cache for sentence segmenter
_segmenter_cache = {}

def get_segmenter(lang: str):
    if lang not in _segmenter_cache:
        # Pysbd supports ISO codes. Fallback to en.
        try:
             _segmenter_cache[lang] = pysbd.Segmenter(language=lang, clean=False)
        except:
             _segmenter_cache[lang] = pysbd.Segmenter(language="en", clean=False)
    return _segmenter_cache[lang]

def split_sentences(text: str, segmentation_func=None, lang="en") -> List[str]:
    # Use pysbd for robust splitting
    if segmentation_func:
        return segmentation_func(text)
    
    # Simple check for empty
    if not text or not text.strip():
        return [text]

    seg = get_segmenter(lang)
    return seg.segment(text)

# Namespaces commonly used
NAMESPACES = {
    'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
    'mc': 'http://schemas.openxmlformats.org/markup-compatibility/2006',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
}
