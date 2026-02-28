import logging
import re
import os
import asyncio
import google.generativeai as genai
import anthropic
from typing import Dict, Optional, List

from .types import SegmentContext, GenerationResult
from ..config import get_default_model_id, get_ai_models_config

logger = logging.getLogger("RAG.Inference")

# Cache provider lookup to avoid re-reading JSON on every call
_provider_cache: Dict[str, str] = {}

def _get_provider(model_name: str) -> str:
    """Looks up the provider for a model ID from ai_models.json."""
    if model_name in _provider_cache:
        return _provider_cache[model_name]
    config = get_ai_models_config()
    for m in config.get("models", []):
        _provider_cache[m["id"]] = m.get("provider", "google")
    return _provider_cache.get(model_name, "google")


class InferenceOrchestrator:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            logger.warning("GOOGLE_API_KEY not set for InferenceOrchestrator")
        else:
            genai.configure(api_key=self.api_key)

        self.anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        self._anthropic_client = None
            
    async def generate_draft(
        self, 
        source_text: str, 
        source_lang: str, 
        target_lang: str, 
        context: SegmentContext,
        model_name: str = None,
        custom_prompt: str = "",
        segment_id: str = "single_draft"
    ) -> GenerationResult:
        """
        Orchestrates the generation process.
        Delegates to generate_structured_batch for Unified Logic.
        """
        if not model_name:
            model_name = get_default_model_id()
            
        # Transform Context to Batch Item format
        # We need to construct the batch item carefully from the Context object
        
        tm_matches = [{"source": m.source_text, "target": m.content, "score": m.score} 
                      for m in context.matches[:3] if m.type != 'glossary' and m.score < 100]
        
        glossary = [{"term": g.source_text, "translation": g.content} 
                    for g in context.glossary_hits]

        # Extract neighbors for windowed context logic if available
        # But generate_structured_batch expects "global" preceding/following.
        # For single segment, we can use context.prev_chunks / next_chunks if they are strictly neighbors.
        # In SegmentContext, prev_chunks/next_chunks are lists of strings.
        
        preceding = context.prev_chunks if context.prev_chunks else []
        following = context.next_chunks if context.next_chunks else []
        
        batch_item = {
            "id": segment_id,
            "source_text": source_text,
            "tm_matches": tm_matches,
            "glossary_matches": glossary
        }
        
        translations, usage = await self.generate_structured_batch(
            preceding_context=preceding,
            following_context=following,
            batch_items=[batch_item],
            source_lang=source_lang,
            target_lang=target_lang,
            model_name=model_name,
            custom_prompt=custom_prompt
        )
        
        target = translations.get(segment_id, "")
        if not target:
             # Fallback or Error?
             # If structured failed, maybe we return empty or try standard?
             # For now, return empty with error note?
             pass

        return GenerationResult(
            target_text=target,
            usage=usage,
            context_used=context
        )

    async def generate_structured_batch(
        self,
        preceding_context: List[str],
        following_context: List[str],
        batch_items: List[Dict], # [{id, source_text, tm_matches, glossary_matches}]
        source_lang: str,
        target_lang: str,
        model_name: str = None,
        custom_prompt: str = ""
    ) -> (Dict[str, str], Dict):
        """
        Translates a batch using a structured JSON prompt with Windowed Context.
        """
        if not model_name: model_name = get_default_model_id()
        
        import json
        
        system_instruction = f"""You are a professional translator. Translate the following content from {source_lang} to {target_lang}.
Rules:
1. Output valid JSON array: [{{ "id": "segment_id", "target": "translated_text" }}, ...]
2. Preserve XML-like tags (e.g. <1>, <b>) exactly as they appear in source.
3. TM match handling by score (HIGHEST PRIORITY — overrides Style Guide):
   - Score >= 95: MANDATORY reference. Copy the TM target translation verbatim. Do NOT rephrase, do NOT apply style guide rules, do NOT change terminology (e.g. keep "Stakeholder" even if the style guide prefers gendered language). The ONLY permitted change: if the current source text differs from the TM source, adjust the translation minimally to reflect that specific source difference — nothing else.
   - Score 70-94: Strong reference. Use as base and adapt for any source differences while keeping its style and terminology. Apply style guide only where the TM has no opinion.
   - Score < 70: Weak reference. Translate freely following the style guide, but consider the TM terminology.
4. ALWAYS use glossary terms over your own word choices. Glossary entries are mandatory.
5. Maintain style consistency across the batch.
"""

        if custom_prompt:
            system_instruction += f"\nStyle Guide (applies to free translations and weak TM matches only — do NOT override TM matches with score >= 95):\n{custom_prompt}\n"
            
        # Construct JSON Input
        # "context_window": { "preceding": [...], "following": [...] }
        # "batch": [ ... ]
        
        input_data = {
            "task": "Translate batch",
            "context_window": {
                "preceding_segments": preceding_context,
                "following_segments": following_context
            },
            "segments_to_translate": []
        }
        
        for item in batch_items:
            seg_obj = {
                "id": item['id'],
                "source": item['source_text'],
                "glossary": item['glossary_matches'],
                "tm_suggestions": item['tm_matches']
            }
            input_data['segments_to_translate'].append(seg_obj)
            
        prompt = f"{system_instruction}\n\nInput Data:\n{json.dumps(input_data, indent=2)}\n\nOutput JSON:"
        
        try:
            response_text, usage = await self._call_llm(prompt, model_name, temperature=0.2)
            
            # Robust JSON extraction
            import re
            json_str = response_text.strip()
            
            # 1. Try to find markdown block
            match = re.search(r"```(?:json)?(.*?)```", response_text, re.DOTALL | re.IGNORECASE)
            if match:
                json_str = match.group(1).strip()
            else:
                 # 2. Fallback: try to find outer brackets
                 s = response_text.find('[')
                 e = response_text.rfind(']')
                 if s != -1 and e != -1:
                     json_str = response_text[s:e+1]
            
            try:
                data = json.loads(json_str)
            except json.JSONDecodeError:
                # 3. Final Fallback: Aggressive cleanup
                # Sometimes models output "Here is the JSON: [ ... ]" without markdown
                json_str = re.sub(r'^[^{[]*', '', json_str) # strip leading non-json
                json_str = re.sub(r'[^}\]]*$', '', json_str) # strip trailing non-json
                data = json.loads(json_str)
            
            results = {}
            if isinstance(data, list):
                for item in data:
                    if 'id' in item and 'target' in item:
                        results[item['id']] = item['target']
            return results, usage
            
        except Exception as e:
            logger.error(f"Batch Inference Failed: {e}")
            return {}, {"input_tokens": 0, "output_tokens": 0}

    async def _generate_pass_1_plain(self, source: str, s_lang: str, t_lang: str, ctx: SegmentContext, model: str, prompt: str):
        """Pass 1: Translate Plain Text (Low Temperature)"""
        system_instruction = f"Translate from {s_lang} to {t_lang}. Output ONLY the raw translation text (Plain Text). No preamble. Do not wrap the output in any delimiters."
        
        if prompt:
            system_instruction += f"\n\nStyle Guide:\n{prompt}"
            
        # Inject Context (Matches + Neighbors)
        # We use a simplified context injection for Pass 1
        prompt_content = self._build_prompt_content(system_instruction, source, ctx)
        
        return await self._call_llm(prompt_content, model, temperature=0.2)

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

        return await self._call_llm(msg, model, temperature=0.1)

    async def _generate_standard(self, source: str, s_lang: str, t_lang: str, ctx: SegmentContext, model: str, prompt: str):
        """Standard 1-Pass Translation"""
        system_instruction = f"Translate from {s_lang} to {t_lang}. Output ONLY the raw translation text. Do not wrap the output in any delimiters."
        system_instruction += " The source text may contain XML-like formatting tags. Preserve them."
        
        if prompt:
            system_instruction += f"\n\nStyle Guide:\n{prompt}"
            
        prompt_content = self._build_prompt_content(system_instruction, source, ctx)
        
        return await self._call_llm(prompt_content, model, temperature=0.3)

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
        
        out += f"\n\n## Source Text\n{source}"
        
        if ctx.next_chunks:
             for n in ctx.next_chunks: out += f"\n... {n}"
             
        return out

    async def _call_llm(self, prompt: str, model_name: str, temperature: float, max_retries: int = 3) -> (str, Dict):
        """Dispatch to the correct provider based on model ID."""
        provider = _get_provider(model_name)
        if provider == "anthropic":
            return await self._call_claude(prompt, model_name, temperature, max_retries)
        else:
            return await self._call_gemini(prompt, model_name, temperature, max_retries)

    async def _call_gemini(self, prompt: str, model_name: str, temperature: float, max_retries: int = 3) -> (str, Dict):
        gm = genai.GenerativeModel(model_name)
        config = genai.GenerationConfig(temperature=temperature)

        for attempt in range(max_retries):
            try:
                if hasattr(gm, 'generate_content_async'):
                    res = await gm.generate_content_async(prompt, generation_config=config)
                else:
                    loop = asyncio.get_event_loop()
                    res = await loop.run_in_executor(None, lambda: gm.generate_content(prompt, generation_config=config))

                txt = res.text.strip()
                usage = {"input_tokens": 0, "output_tokens": 0}
                if res.usage_metadata:
                     usage["input_tokens"] = res.usage_metadata.prompt_token_count
                     usage["output_tokens"] = res.usage_metadata.candidates_token_count
                return txt, usage

            except Exception as e:
                is_transient = any(code in str(e) for code in ["500", "503", "504", "429", "DEADLINE", "overloaded"])
                if is_transient and attempt < max_retries - 1:
                    wait = (attempt + 1) * 3  # 3s, 6s, 9s
                    logger.warning(f"Gemini transient error (attempt {attempt+1}/{max_retries}): {e}. Retrying in {wait}s...")
                    await asyncio.sleep(wait)
                else:
                    raise e

    async def _call_claude(self, prompt: str, model_name: str, temperature: float, max_retries: int = 3) -> (str, Dict):
        if not self.anthropic_key:
            raise ValueError("ANTHROPIC_API_KEY not set")

        if not self._anthropic_client:
            self._anthropic_client = anthropic.AsyncAnthropic(api_key=self.anthropic_key)

        for attempt in range(max_retries):
            try:
                res = await self._anthropic_client.messages.create(
                    model=model_name,
                    max_tokens=8192,
                    temperature=temperature,
                    messages=[{"role": "user", "content": prompt}],
                )

                txt = res.content[0].text.strip()
                usage = {
                    "input_tokens": res.usage.input_tokens,
                    "output_tokens": res.usage.output_tokens,
                }
                return txt, usage

            except Exception as e:
                err_str = str(e)
                is_transient = any(code in err_str for code in ["500", "503", "529", "429", "overloaded"])
                if is_transient and attempt < max_retries - 1:
                    wait = (attempt + 1) * 3
                    logger.warning(f"Claude transient error (attempt {attempt+1}/{max_retries}): {e}. Retrying in {wait}s...")
                    await asyncio.sleep(wait)
                else:
                    raise e
