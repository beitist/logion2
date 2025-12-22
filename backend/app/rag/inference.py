import logging
import re
import os
import asyncio
import google.generativeai as genai
from typing import Dict, Optional, List

from .types import SegmentContext, GenerationResult
from ..config import get_default_model_id

logger = logging.getLogger("RAG.Inference")

class InferenceOrchestrator:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            logger.warning("GOOGLE_API_KEY not set for InferenceOrchestrator")
        else:
            genai.configure(api_key=self.api_key)
            
    async def generate_draft(
        self, 
        source_text: str, 
        source_lang: str, 
        target_lang: str, 
        context: SegmentContext,
        model_name: str = None,
        custom_prompt: str = ""
    ) -> GenerationResult:
        """
        Orchestrates the generation process.
        Decides between 1-Pass and 2-Pass based on tag complexity.
        """
        if not model_name:
            model_name = get_default_model_id()
            
        # Heuristic: Complex Tags?
        # Count tags like <1>, <b>, etc.
        tag_count = len(re.findall(r'<[^>]+>', source_text))
        is_complex = tag_count > 3
        
        usage = {"input_tokens": 0, "output_tokens": 0}
        
        try:
            if is_complex and "flash" not in model_name: 
                # Use Two-Pass for complex segments (if not already using a fast model)
                # Pass 1: Linguistic (Plain)
                logger.info(f"Triggering Two-Pass (Tags: {tag_count})")
                
                # Strip tags for Pass 1
                plain_source = re.sub(r'<[^>]+>', '', source_text).replace("  ", " ").strip()
                
                plain_target, u1 = await self._generate_pass_1_plain(
                    plain_source, source_lang, target_lang, context, model_name, custom_prompt
                )
                usage["input_tokens"] += u1["input_tokens"]
                usage["output_tokens"] += u1["output_tokens"]
                
                # Pass 2: Tag Injection (Use a cheaper model ideally, or same)
                # For now using same model or Flash if available?
                # Let's use the same model to be safe, or user config?
                # User suggestion: "Nutze für Pass 2 ein günstigeres Modell (z.B. Gemini Flash)"
                # We try to use 'gemini-1.5-flash' for pass 2 if main is pro?
                pass2_model = "gemini-1.5-flash" if "pro" in model_name else model_name
                
                final_text, u2 = await self._generate_pass_2_tags(
                    source_text, plain_target, pass2_model, custom_prompt
                )
                usage["input_tokens"] += u2["input_tokens"]
                usage["output_tokens"] += u2["output_tokens"]
                
                return GenerationResult(
                    target_text=final_text,
                    usage=usage,
                    context_used=context
                )
            
            else:
                # Standard 1-Pass
                text, u = await self._generate_standard(
                    source_text, source_lang, target_lang, context, model_name, custom_prompt
                )
                return GenerationResult(
                    target_text=text,
                    usage=u,
                    context_used=context
                )
                
        except Exception as e:
            logger.error(f"Inference Error: {e}", exc_info=True)
            return GenerationResult(
                target_text="",
                usage=usage,
                context_used=context,
                error=str(e)
            )

    async def _generate_pass_1_plain(self, source: str, s_lang: str, t_lang: str, ctx: SegmentContext, model: str, prompt: str):
        """Pass 1: Translate Plain Text (Low Temperature)"""
        system_instruction = f"Translate from {s_lang} to {t_lang}. Output ONLY the raw translation text (Plain Text). No preamble."
        
        if prompt:
            system_instruction += f"\n\nStyle Guide:\n{prompt}"
            
        # Inject Context (Matches + Neighbors)
        # We use a simplified context injection for Pass 1
        prompt_content = self._build_prompt_content(system_instruction, source, ctx)
        
        return await self._call_gemini(prompt_content, model, temperature=0.2)

    async def _generate_pass_2_tags(self, original_source: str, plain_translation: str, model: str, custom_prompt: str):
        """Pass 2: Inject Tags into Translation"""
        msg = f"""Here is a source sentence with formatting tags: {original_source}
Here is its translation (Plain Text): {plain_translation}

Task: Insert the tags from the source into the translation at the semantically corresponding positions.
Rules:
- You MUST preserve all tags from the source.
- Do NOT translate the content again, just place tags.
- Output ONLY the final tagged translation."""

        if custom_prompt:
             msg += f"\n\nConstraint: {custom_prompt}"

        return await self._call_gemini(msg, model, temperature=0.1)

    async def _generate_standard(self, source: str, s_lang: str, t_lang: str, ctx: SegmentContext, model: str, prompt: str):
        """Standard 1-Pass Translation"""
        system_instruction = f"Translate from {s_lang} to {t_lang}. Output ONLY the raw translation text."
        system_instruction += " The source text may contain XML-like formatting tags. Preserve them."
        
        if prompt:
            system_instruction += f"\n\nStyle Guide:\n{prompt}"
            
        prompt_content = self._build_prompt_content(system_instruction, source, ctx)
        
        return await self._call_gemini(prompt_content, model, temperature=0.3)

    def _build_prompt_content(self, system_instr, source, ctx: SegmentContext) -> str:
        out = system_instruction = system_instr
        
        # Inject Glossary
        if ctx.glossary_hits:
            out += "\n\nGlossary Terms:"
            for g in ctx.glossary_hits:
                out += f"\n- {g.source_text} -> {g.content} : {g.note or ''}"
                
        # Inject TM/Neighbors
        if ctx.matches:
            out += "\n\nReference Translations (TM):"
            for m in ctx.matches[:3]:
                if m.type == 'history': continue
                out += f"\n- {m.source_text} -> {m.content} (Score: {m.score})"

        # Inject History (Short Term Memory)
        history = [m for m in ctx.matches if m.type == 'history']
        out += "\n\nContext (Preceding Segments):"
        if ctx.prev_chunks:
            # Source neighbors
             for p in ctx.prev_chunks: out += f"\n... {p}"
        
        # If we have history (Target), it's even better, but usually mixed with source neighbors in display.
        # Let's just put source neighbors as 'Background'.
        
        out += f"\n\n>>> {source} <<<"
        
        if ctx.next_chunks:
             for n in ctx.next_chunks: out += f"\n... {n}"
             
        return out

    async def _call_gemini(self, prompt: str, model_name: str, temperature: float) -> (str, Dict):
        # Async wrapper for Google GenAI
        # Note: genai.GenerativeModel is sync instantiation, generate_content is the call.
        # Check if generate_content_async exists
        
        gm = genai.GenerativeModel(model_name)
        config = genai.GenerationConfig(temperature=temperature)
        
        try:
            if hasattr(gm, 'generate_content_async'):
                res = await gm.generate_content_async(prompt, generation_config=config)
            else:
                # Fallback to sync in thread
                loop = asyncio.get_event_loop()
                res = await loop.run_in_executor(None, lambda: gm.generate_content(prompt, generation_config=config))
                
            txt = res.text.strip()
            usage = {"input_tokens": 0, "output_tokens": 0}
            if res.usage_metadata:
                 usage["input_tokens"] = res.usage_metadata.prompt_token_count
                 usage["output_tokens"] = res.usage_metadata.candidates_token_count
            return txt, usage
            
        except Exception as e:
            raise e
