
import os
import re
import shutil
from typing import List
from bs4 import BeautifulSoup
from fastapi import HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from ..models import Project, Segment, ProjectFile, ProjectFileCategory
from ..schemas import SegmentInternal, TagModel
from ..storage import download_file
from ..reassembly import reassemble_docx
from ..logger import get_logger

logger = get_logger("ExportService")
UPLOAD_DIR = "uploads"

class ExportService:
    def __init__(self, db: Session):
        self.db = db

    def export_project(self, project_id: str) -> FileResponse:
        project = self.db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        # 1. Get all segments
        segments = self.db.query(Segment).filter(Segment.project_id == project_id).order_by(Segment.index).all()
        
        # 2. Reconstruct SegmentInternal objects
        reassembly_segments = self._prepare_segments_for_reassembly(segments)
        
        # 3. Path to original file
        source_file_record = self.db.query(ProjectFile).filter(
            ProjectFile.project_id == project_id, 
            ProjectFile.category == ProjectFileCategory.source.value
        ).first()

        if not source_file_record:
            raise HTTPException(status_code=404, detail="Original source file not found for project")
        
        input_object_name = source_file_record.file_path
        temp_input_path = os.path.join(UPLOAD_DIR, f"temp_export_in_{project_id}.docx")
        
        try:
            try:
                download_file(input_object_name, temp_input_path)
            except Exception as e:
                # Legacy fallback
                if os.path.exists(input_object_name):
                     shutil.copy(input_object_name, temp_input_path)
                else:
                     raise HTTPException(status_code=404, detail=f"Source file download failed: {e}")

            output_filename = f"translated_{project.filename}"
            output_path = os.path.join(UPLOAD_DIR, output_filename)
            
            # 4. Reassemble
            try:
                reassemble_docx(temp_input_path, output_path, reassembly_segments)
            except Exception as e:
                import traceback
                with open("export_error.log", "w") as f:
                    f.write(traceback.format_exc())
                raise HTTPException(status_code=500, detail=f"Reassembly failed: {str(e)}")
                
            return FileResponse(output_path, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", filename=output_filename)
            
        finally:
            if os.path.exists(temp_input_path):
                os.remove(temp_input_path)

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


    def export_project_tmx(self, project_id: str) -> FileResponse:
        project = self.db.query(Project).filter(Project.id == project_id).first()
        if not project:
             raise HTTPException(status_code=404, detail="Project not found")
        
        segments = self.db.query(Segment).filter(Segment.project_id == project_id).order_by(Segment.index).all()
        
        tmx_content = self.generate_tmx_content(project.source_lang, project.target_lang, segments)
        
        output_filename = f"{project.filename}.tmx"
        output_path = os.path.join(UPLOAD_DIR, output_filename)
        
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(tmx_content)
            
        return FileResponse(output_path, media_type="application/xml", filename=output_filename)

    def generate_tmx_content(self, source_lang, target_lang, segments):
        """
        Generates a TMX 1.4b compliant string from segments.
        """
        import datetime
        from xml.sax.saxutils import escape

        tmx_header = f"""<?xml version="1.0" encoding="UTF-8"?>
<tmx version="1.4b">
  <header creationtool="Logion2" creationtoolversion="1.0"
          datatype="PlainText" segtype="sentence"
          adminlang="en-US" srclang="{source_lang}"
          o-tmf="Logion2TM"
          creationdate="{datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}">
  </header>
  <body>"""

        tmx_body = ""
        for seg in segments:
            if not seg.target_content or not seg.source_content:
                continue
            
            # Strip internal tags (anything looking like <1>, </1>, <b ...>)
            # We want clean text for TMX to avoid polluting other TMs.
            src_clean_text = re.sub(r'<[^>]+>', '', seg.source_content)
            tgt_clean_text = re.sub(r'<[^>]+>', '', seg.target_content)
            
            src_clean = escape(src_clean_text)
            tgt_clean = escape(tgt_clean_text)

            tmx_body += f"""
    <tu>
      <tuv xml:lang="{source_lang}">
        <seg>{src_clean}</seg>
      </tuv>
      <tuv xml:lang="{target_lang}">
        <seg>{tgt_clean}</seg>
      </tuv>
    </tu>"""

        tmx_footer = """
  </body>
</tmx>"""
    
        return tmx_header + tmx_body + tmx_footer

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
