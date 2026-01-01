
import os
import openpyxl
from openpyxl.cell.text import InlineFont
from openpyxl.cell.rich_text import TextBlock, CellRichText
from app.logger import get_logger
from app.document.utils import split_sentences, qn

logger = get_logger("ExcelParser")

def parse_xlsx(file_path: str, segmentation_func=None, source_lang="en"):
    """
    Parses an XLSX file and extracts segments.
    Iterates through all cells in the active sheet.
    Splits content into sentences.
    """
    logger.info(f"Parsing XLSX: {file_path}")
    
    if segmentation_func is None:
        segmentation_func = lambda t: split_sentences(t, lang=source_lang)

    # Load without data_only=True to detect formulas
    wb = openpyxl.load_workbook(file_path, data_only=False)
    active_sheet = wb.active
    
    final_segments = []
    
    # Iterate through all rows and columns
    for row_idx, row in enumerate(active_sheet.iter_rows(), start=1):
        for col_idx, cell in enumerate(row, start=1):
            if cell.value is None:
                continue
            
            # Filter Logic
            # 'f' = Formula
            # 'n' = Numeric
            # 'd' = Date (sometimes shows as 'n' with style, checking is_date is safer)
            # 'b' = Bool
            # 's' = String, 'str' = String
            
            if cell.data_type == 'f':
                # Skip formulas
                continue
                
            if cell.is_date:
                # Is date check (property of cell)
                continue
                
            if cell.data_type == 'n':
                # Skip pure numbers
                continue
                
            if cell.data_type == 'b':
                continue
                
            cell_text = str(cell.value).strip()
            if not cell_text:
                continue
            
            # Check for explicit text marker (quote prefix)
            # If present, we treat it as text regardless of content (e.g. '123)
            # Note: openpyxl exposes this as `quote_prefix` boolean on the cell style
            # UPDATE: property name is likely quotePrefix (camelCase)
            is_quoted = getattr(cell, 'quote_prefix', False) or getattr(cell, 'quotePrefix', False)
            
            # Heuristic: If text looks like a number AND NOT QUOTED, skip it.
            if not is_quoted:
                # (e.g. '12345' stored as Text)
                # Remove common numeric markers
                import re
                cleaned = cell_text.replace('.', '').replace(',', '').replace(' ', '').replace('€', '').replace('$', '').replace('%', '')
                if cleaned.isdigit():
                     # Valid number stored as text -> Skip
                     continue
            
            # TODO: Handle Rich Text if possible.
            # openpyxl's data_only=True returns the evaluated value, loosing formulas.
            # Ideally we want the text. 
            
            # Split sentences
            sentences = segmentation_func(cell_text)
            
            for i, sent in enumerate(sentences):
                # Construct segment object
                # We use a similar structure to DOCX segments
                # Construct segment object
                # We return SegmentInternal objects to match DOCX parser
                import uuid
                from app.schemas import SegmentInternal
                
                segment = SegmentInternal(
                    segment_id=str(uuid.uuid4()),
                    source_text=sent.strip(),
                    tags={}, # No tags extraction yet
                    metadata={
                        "sheet": active_sheet.title,
                        "row": row_idx,
                        "col": col_idx,
                        "sentence_index": i, # Sub-index within cell
                        "is_tail": i == len(sentences) - 1
                    }
                )
                final_segments.append(segment)

    logger.info(f"Extracted {len(final_segments)} segments from XLSX.")
    return final_segments
