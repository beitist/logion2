import os
import re
import shutil
import datetime
from typing import List
from bs4 import BeautifulSoup
from fastapi import HTTPException
from ..models import Segment, ProjectFile, ProjectFileCategory
from ..schemas import SegmentInternal, TagModel
from ..storage import download_file
from ..document.assembler import reassemble_docx
from ..tmx import export_tmx
from .base import BaseWorkflow

UPLOAD_DIR = "uploads"

class ExportWorkflow(BaseWorkflow):
    def run(self, format: str = "docx") -> str:
        """
        Runs the export process.
        Returns the absolute path to the generated file.
        """
        if not self.project:
            raise HTTPException(status_code=404, detail="Project not found")

        if format == "docx":
            return self._export_docx()
        elif format == "tmx":
            return self._export_tmx()
        else:
            raise ValueError(f"Unknown format: {format}")

    def _export_docx(self) -> str:
        """
        Exports all source files as translated DOCX.
        If multiple source files exist, creates a ZIP archive.
        """
        import zipfile
        
        # 1. Get ALL source files (multi-file support)
        source_file_records = self.db.query(ProjectFile).filter(
            ProjectFile.project_id == self.project_id, 
            ProjectFile.category == ProjectFileCategory.source.value
        ).order_by(ProjectFile.uploaded_at).all()

        if not source_file_records:
            raise HTTPException(status_code=404, detail="No source files found for project")
        
        # 2. Get all segments and group by file_id
        all_segments = self.db.query(Segment).filter(
            Segment.project_id == self.project_id
        ).order_by(Segment.index).all()
        
        # Group segments by file_id for multi-file processing
        segments_by_file = {}
        for seg in all_segments:
            # Use file_id if available, otherwise fallback to first file
            file_key = seg.file_id or source_file_records[0].id
            if file_key not in segments_by_file:
                segments_by_file[file_key] = []
            segments_by_file[file_key].append(seg)
        
        # 3. Process each source file
        output_files = []  # List of (filename, path) tuples
        temp_files_to_cleanup = []
        
        try:
            for source_record in source_file_records:
                # Get segments for this file
                file_segments = segments_by_file.get(source_record.id, [])
                
                if not file_segments:
                    continue  # Skip files with no segments
                
                # Prepare segments for reassembly
                reassembly_segments = self._prepare_segments_for_reassembly(file_segments)
                
                # Download source file
                input_object_name = source_record.file_path
                temp_input_path = os.path.join(UPLOAD_DIR, f"temp_export_in_{source_record.id}.docx")
                temp_files_to_cleanup.append(temp_input_path)
                
                try:
                    download_file(input_object_name, temp_input_path)
                except Exception as e:
                    # Legacy fallback
                    if os.path.exists(input_object_name):
                        shutil.copy(input_object_name, temp_input_path)
                    else:
                        raise HTTPException(status_code=404, detail=f"Source file download failed: {e}")
                
                # Output filename for this file
                output_filename = f"translated_{source_record.filename}"
                output_path = os.path.join(UPLOAD_DIR, output_filename)
                
                # Reassemble this file
                try:
                    reassemble_docx(temp_input_path, output_path, reassembly_segments)
                    output_files.append((output_filename, output_path))
                except Exception as e:
                    import traceback
                    with open("export_error.log", "w") as f:
                        f.write(f"File: {source_record.filename}\n")
                        f.write(traceback.format_exc())
                    raise HTTPException(status_code=500, detail=f"Reassembly failed for {source_record.filename}: {str(e)}")
            
            # 4. Return single file or create ZIP for multiple files
            if len(output_files) == 1:
                return output_files[0][1]  # Return single file path
            
            # Create ZIP archive for multiple files
            zip_filename = f"translated_{self.project.name or self.project.filename}_all.zip"
            zip_path = os.path.join(UPLOAD_DIR, zip_filename)
            
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for filename, filepath in output_files:
                    zipf.write(filepath, filename)
            
            # Clean up individual output files (they're now in the ZIP)
            for _, filepath in output_files:
                if os.path.exists(filepath):
                    os.remove(filepath)
            
            return zip_path
            
        finally:
            # Clean up temp input files
            for temp_path in temp_files_to_cleanup:
                if os.path.exists(temp_path):
                    os.remove(temp_path)

    def _export_tmx(self) -> str:
        segments = self.db.query(Segment).filter(Segment.project_id == self.project_id).order_by(Segment.index).all()
        
        tmx_content = self._generate_tmx_content(self.project.source_lang, self.project.target_lang, segments)
        
        output_filename = f"{self.project.filename}.tmx"
        output_path = os.path.join(UPLOAD_DIR, output_filename)
        
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(tmx_content)
            
        return output_path

    def _prepare_segments_for_reassembly(self, segments: List[Segment]) -> List[SegmentInternal]:
        reassembly_segments = []
        for db_seg in segments:
            stored_data = db_seg.metadata_json or {}
            
            reconstructed_tags_dict = {}
            for tag_name, tag_data in stored_data.get("tags", {}).items():
                reconstructed_tags_dict[tag_name] = TagModel(**tag_data)
            
            meta_loc = stored_data.get("metadata", {})
            target_text = db_seg.target_content
            if not target_text:
                target_text = db_seg.source_content 
            else:
                target_text = self._cleanup_tiptap_html(target_text)

            seg_internal = SegmentInternal(
                id=db_seg.id,
                segment_id=str(db_seg.id),
                source_text=db_seg.source_content,
                target_content=target_text,
                status=db_seg.status,
                tags=reconstructed_tags_dict,
                metadata=meta_loc
            )
            reassembly_segments.append(seg_internal)
        return reassembly_segments

    def _cleanup_tiptap_html(self, html_content: str) -> str:
        """
        Cleans up Tiptap HTML, handles span tags, and converts them back to placeholders.
        """
        if not html_content:
            return ""

        # Protect existing <1> tags
        text = re.sub(r'<(\d+)>', r'__TAG_START_\1__', html_content)
        text = re.sub(r'</(\d+)>', r'__TAG_END_\1__', text)

        soup = BeautifulSoup(text, "html.parser")
        
        # Convert Tiptap Spans
        for span in soup.find_all("span", attrs={"data-type": "tag-node"}):
            tid = span.get("data-id")
            if tid:
                if tid == 'TAB':
                    span.replace_with("[TAB]") 
                else:
                    text_content = span.get_text().strip()
                    is_end_tag = text_content.startswith("/")
                    if is_end_tag:
                        placeholder = f"__TAG_END_{tid}__"
                    else:
                        placeholder = f"__TAG_START_{tid}__"
                    span.replace_with(placeholder)

        # Handle Paragraphs
        ps = soup.find_all("p")
        if len(ps) > 0:
             cleaned_html = ""
             for i, p in enumerate(ps):
                 if i > 0: cleaned_html += "<br/>"
                 cleaned_html += p.decode_contents()
        else:
            cleaned_html = soup.decode_contents()

        # Restore placeholders
        cleaned_html = re.sub(r'__TAG_START_(\d+)__', r'<\1>', cleaned_html)
        cleaned_html = re.sub(r'__TAG_END_(\d+)__', r'</\1>', cleaned_html)
         
        return cleaned_html

    def _generate_tmx_content(self, source_lang, target_lang, segments):
        from xml.sax.saxutils import escape

        tmx_header = f'''<?xml version="1.0" encoding="UTF-8"?>
<tmx version="1.4b">
  <header creationtool="Logion2" creationtoolversion="1.0"
          datatype="PlainText" segtype="sentence"
          adminlang="en-US" srclang="{source_lang}"
          o-tmf="Logion2TM"
          creationdate="{datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}">
  </header>
  <body>'''

        tmx_body = ""
        for seg in segments:
            if not seg.target_content or not seg.source_content:
                continue
            
            src_clean_text = re.sub(r'<[^>]+>', '', seg.source_content)
            tgt_clean_text = re.sub(r'<[^>]+>', '', seg.target_content)
            
            src_clean = escape(src_clean_text)
            tgt_clean = escape(tgt_clean_text)

            tmx_body += f'''
    <tu>
      <tuv xml:lang="{source_lang}">
        <seg>{src_clean}</seg>
      </tuv>
      <tuv xml:lang="{target_lang}">
        <seg>{tgt_clean}</seg>
      </tuv>
    </tu>'''

        tmx_footer = """
  </body>
</tmx>"""
    
        return tmx_header + tmx_body + tmx_footer
