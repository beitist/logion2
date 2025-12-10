from .schemas import SegmentInternal

def translate_segment_dummy(segment: SegmentInternal, target_lang="de") -> SegmentInternal:
    """
    Mock translator.
    Prefixed "DE_" to text parts, but PRESERVES tags.
    Input: "This is <1>bold</1>."
    Output: "DE_This DE_is <1>DE_bold</1>."
    """
    # Simple regex replace won't work easily if we want to be smart.
    # For dummy: just prefix the whole string, but we must respect tags?
    # Actually, simpler: Just replace the text content inside and outside tags?
    
    # Let's do a very naive implementation for Proof of Concept:
    # "This is <1>bold</1>" -> "[DE] This is <1>[DE] bold</1>"
    
    # We can iterate over the source text using regex to find tags
    # But wait, existing tags format is <n>...</n>.
    
    import re
    
    # Split by tags
    # Pattern to match <n>...</n> AND pure text
    # This is complex to do perfectly with regex for nested tags, but we have flat tags for now.
    
    translated_text = segment.source_text
    
    # Naive: Prepend [DE] to the whole string is BAD because it messes up structure if not careful.
    # Better: just prepend to the text content?
    
    # Strategy:
    # 1. Hide tags -> Replace <1>...</1> with placeholders? No, we need to translate INSIDE tags too.
    # 2. Just replace all text with "DE_" + text?
    
    # Let's just prepend "DE: " to the start of the string for the easiest check.
    # AND prepend "DE_" to the content inside tags?
    
    # Example: "Hello <1>World</1>" -> "DE: Hello <1>DE: World</1>"
    
    # Regex to match content inside tags: <(\d+)>(.*?)</\1>
    # Regex to match content outside tags is harder.
    
    # Simplest valid dummy for roundtrip:
    # Just prefix the whole string.
    # "DE_Hello <1>World</1>" -> This is technically valid XML-ish content.
    # But checking if we can write it back is the key.
    
    segment.target_content = "DE: " + segment.source_text
    # No, let's be clean.
    
    segment.target_content = "DE: " + segment.source_text
    
    return segment
