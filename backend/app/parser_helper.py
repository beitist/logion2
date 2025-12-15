
import re
from typing import List

def _repair_tags(segments: List[str]) -> List[str]:
    """
    Ensures that if a segment ends with open tags, they are closed,
    and reopened in the next segment.
    """
    repaired = []
    stack = []
    # Regex to find tags: <1>, </1>
    pattern = re.compile(r'<(/?(\d+))>')
    
    for part in segments:
        # 1. Prepend Open Tags from Stack (Re-Open)
        prefix = "".join([f"<{tid}>" for tid in stack])
        current_seg = prefix + part
        
        # 2. Update Stack based on tags in THIS part (Original content)
        # We must scan 'part' to avoiding seeing the tags we just prepended
        for m in pattern.finditer(part):
            full_tag = m.group(1) # "1" or "/1"
            tid = m.group(2)
            is_close = full_tag.startswith("/")
            
            if is_close:
                # Attempt to pop from stack
                if stack and stack[-1] == tid:
                    stack.pop()
            else:
                stack.append(tid)
        
        # 3. Append Close Tags for remaining Stack (Close)
        suffix = "".join([f"</{tid}>" for tid in reversed(stack)])
        current_seg = current_seg + suffix
        
        repaired.append(current_seg)
        
    return repaired
