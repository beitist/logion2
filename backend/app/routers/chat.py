import logging
import re
from pydantic import BaseModel
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Segment, Project, AiUsageLog
from ..rag.inference import InferenceOrchestrator
from ..config import get_default_model_id

logger = logging.getLogger("ChatRouter")
router = APIRouter(prefix="/project", tags=["chat"])


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]


class ChatResponse(BaseModel):
    reply: str
    usage: dict


def _strip_tags(text: str) -> str:
    """Remove XML-like formatting tags (e.g. <1>, </b>, <n>) from segment text."""
    if not text:
        return text
    return re.sub(r'</?[^>]+>', '', text).strip()


def _build_chat_system_prompt(segment: Segment, project: Project, custom_prompt: str, preceding_segment: Segment = None) -> str:
    source_lang = project.source_lang or "en"
    target_lang = project.target_lang or "de"

    source_clean = _strip_tags(segment.source_content)
    target_clean = _strip_tags(segment.target_content)

    prompt = f"""You are a professional translation assistant for {source_lang} to {target_lang} translation.
You are helping a translator with a specific segment. Answer questions, suggest alternatives, explain terminology, or adjust style as requested.
"""

    # Add preceding sentence from same paragraph for reading flow
    if preceding_segment:
        prev_src = _strip_tags(preceding_segment.source_content)
        prev_tgt = _strip_tags(preceding_segment.target_content)
        prompt += f"\n## Preceding Sentence (same paragraph)\n"
        prompt += f"Source: {prev_src}\n"
        if prev_tgt:
            prompt += f"Translation: {prev_tgt}\n"

    prompt += f"""
## Current Segment
Source ({source_lang}): {source_clean}
"""

    if target_clean:
        prompt += f"Current Translation ({target_lang}): {target_clean}\n"
    else:
        prompt += f"Current Translation ({target_lang}): (not yet translated)\n"

    # Include pre-computed context from metadata_json
    meta = segment.metadata_json or {}
    context_matches = meta.get("context_matches", [])

    # TM matches — exclude mt, glossary, and history (history = neighboring segments, not real TM)
    tm_hits = [m for m in context_matches if m.get("type") not in ("mt", "glossary", "history")]
    if tm_hits:
        prompt += "\n## Similar Segments from Translation Memory (for reference only, not authoritative)\n"
        for hit in tm_hits[:3]:
            src = _strip_tags(hit.get("source_text", ""))
            tgt = _strip_tags(hit.get("content", ""))
            score = hit.get("score", 0)
            prompt += f"- Source: {src}\n  Target: {tgt} (Similarity: {score}%)\n"

    # Glossary — informational, not prescriptive
    glossary_hits = [m for m in context_matches if m.get("type") == "glossary"]
    if glossary_hits:
        prompt += "\n## Project Glossary (for reference — use your judgement whether terms fit this context)\n"
        for g in glossary_hits:
            prompt += f"- {g.get('source_text', '')} -> {g.get('content', '')}"
            if g.get("note"):
                prompt += f" ({g['note']})"
            prompt += "\n"

    # Custom prompt / style guide
    if custom_prompt:
        prompt += f"\n## Style Guide\n{custom_prompt}\n"

    prompt += """
## Instructions
- Answer in the language the user writes in.
- Glossary terms are suggestions, not rules. If a glossary term doesn't fit the context, say so and suggest a better alternative.
- Keep responses concise and practical.
- If asked for alternatives, provide 2-3 options with brief explanations.
"""
    return prompt


@router.post("/{project_id}/segment/{segment_id}/chat", response_model=ChatResponse)
async def segment_chat(
    project_id: str,
    segment_id: str,
    payload: ChatRequest,
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    segment = db.query(Segment).filter(Segment.id == segment_id, Segment.project_id == project_id).first()
    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")

    if not payload.messages:
        raise HTTPException(status_code=400, detail="Messages list cannot be empty")

    # Model from editor settings
    ai_settings = (project.config or {}).get("ai_settings", {})
    model_name = ai_settings.get("model") or get_default_model_id()
    custom_prompt = ai_settings.get("custom_prompt", "")

    # Find preceding segment (always include for reading flow context)
    preceding_segment = None
    if segment.index is not None and segment.index > 0:
        preceding_segment = db.query(Segment).filter(
            Segment.project_id == project_id,
            Segment.index == segment.index - 1
        ).first()

    system_prompt = _build_chat_system_prompt(segment, project, custom_prompt, preceding_segment)
    messages = [{"role": m.role, "content": m.content} for m in payload.messages]

    orchestrator = InferenceOrchestrator()
    reply_text, usage = await orchestrator.call_chat(system_prompt, messages, model_name)

    # Log usage to DB + project config
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    if input_tokens > 0 or output_tokens > 0:
        db.add(AiUsageLog(
            project_id=project_id,
            segment_id=segment_id,
            model=model_name,
            trigger_type="segment_chat",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        ))

        # Update project.config.usage_stats (same pattern as segment_service)
        from sqlalchemy.orm.attributes import flag_modified
        current_config = dict(project.config or {})
        usage_stats = current_config.get("usage_stats", {})
        m_stats = usage_stats.get(model_name, {"input_tokens": 0, "output_tokens": 0})
        m_stats["input_tokens"] += input_tokens
        m_stats["output_tokens"] += output_tokens
        usage_stats[model_name] = m_stats
        current_config["usage_stats"] = usage_stats
        project.config = current_config
        flag_modified(project, "config")

        db.commit()

    return ChatResponse(reply=reply_text, usage=usage)
