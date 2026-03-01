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


class QuotaExceededError(Exception):
    """Raised when API daily quota is exhausted. Workflows should stop, not retry."""
    pass


def _is_quota_exceeded(error_str: str) -> bool:
    """Detects quota-exceeded 429s (vs transient rate limits)."""
    lower = error_str.lower()
    return "429" in error_str and any(kw in lower for kw in [
        "quota", "daily", "exceeded", "exhausted", "resource has been",
        "billing", "limit for the day",
    ])


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
1. Output valid JSON array: [{{ "id": "segment_id", "target": "translated_text" }}, ...]. Escape double quotes inside translations with backslash (\"). Do not include literal newlines inside JSON strings.
2. Preserve XML-like tags (e.g. <1>, <b>) exactly as they appear in source.
3. TM match handling by score (HIGHEST PRIORITY — overrides Style Guide):
   - Score >= 95: MANDATORY. Copy the TM target verbatim. The ONLY permitted change: if the current source differs from the TM source, adjust minimally to reflect that specific difference — nothing else.
   - Score 87-94: STRONG. Start by copying the TM target AS-IS. Then compare the current source with the TM source word by word. ONLY replace words/phrases in the TM target that directly correspond to differences in the source. Keep ALL other words, terminology, and phrasing from the TM target unchanged. Do NOT rephrase, do NOT substitute synonyms, do NOT apply style guide rules to TM-derived parts.
   - Score < 87: Weak reference. Translate freely following the style guide, but consider the TM terminology for consistency.
4. ALWAYS use glossary terms over your own word choices. Glossary entries are mandatory.
5. Maintain style consistency across the batch.
"""

        if custom_prompt:
            system_instruction += f"\nStyle Guide (applies to free translations and weak TM matches below 87 only — do NOT override TM matches with score >= 87):\n{custom_prompt}\n"
            
        # Construct JSON Input
        # "context_window": { "preceding": [...], "following": [...] }
        # "batch": [ ... ]
        
        input_data = {
            "task": "Translate batch",
            "context_window": {
                "preceding_segments": [self._sanitize_for_prompt(s) for s in preceding_context],
                "following_segments": [self._sanitize_for_prompt(s) for s in following_context],
            },
            "segments_to_translate": []
        }
        
        for item in batch_items:
            seg_obj = {
                "id": item['id'],
                "source": self._sanitize_for_prompt(item['source_text']),
                "glossary": item['glossary_matches'],
                "tm_suggestions": [{
                    **tm,
                    "source": self._sanitize_for_prompt(tm.get("source", "")),
                    "target": self._sanitize_for_prompt(tm.get("target", ""))
                } for tm in item['tm_matches']]
            }
            input_data['segments_to_translate'].append(seg_obj)
            
        prompt = f"{system_instruction}\n\nInput Data:\n{json.dumps(input_data, indent=2)}\n\nOutput JSON:"
        
        try:
            response_text, usage = await self._call_llm(prompt, model_name, temperature=0.2, json_mode=True)
            
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
                # 3. Repair: fix unescaped characters and retry
                repaired = self._repair_llm_json(json_str)
                try:
                    data = json.loads(repaired)
                    logger.info("JSON parsed after repair")
                except json.JSONDecodeError:
                    # 4. Final fallback: extract "target" values via regex
                    logger.warning(f"JSON parse failed after repair, attempting regex extraction. Raw (first 500): {response_text[:500]}")
                    target_matches = re.findall(r'"target"\s*:\s*"((?:[^"\\]|\\.)*)"', json_str)
                    id_matches = re.findall(r'"id"\s*:\s*"((?:[^"\\]|\\.)*)"', json_str)

                    if target_matches and id_matches and len(target_matches) == len(id_matches):
                        data = [{"id": id_matches[i], "target": target_matches[i]} for i in range(len(id_matches))]
                    elif target_matches and len(batch_items) == 1:
                        data = [{"id": batch_items[0]["id"], "target": target_matches[0]}]
                    else:
                        if len(batch_items) == 1:
                            plain = re.sub(r'[\[\]{}":]', '', response_text).strip()
                            if plain:
                                logger.warning("Using plain text fallback for single segment")
                                data = [{"id": batch_items[0]["id"], "target": plain}]
                            else:
                                data = []
                        else:
                            data = []

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

    @staticmethod
    def _sanitize_for_prompt(text: str) -> str:
        """
        Light cleanup of source text before embedding in prompt.
        Only normalizes whitespace and strips control characters.
        Does NOT touch quotes or punctuation — that's the LLM's job.
        """
        if not text:
            return text
        result = text.replace('\t', ' ')
        result = re.sub(r' {2,}', ' ', result)
        result = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', result)
        return result.strip()

    @staticmethod
    def _repair_llm_json(text: str) -> str:
        """
        Repair common JSON issues from LLM responses before parsing.
        Uses a state machine to track whether we're inside a JSON string value,
        then fixes:
        - Unescaped double quotes inside string values
        - Literal newlines / carriage returns / tabs inside strings
        - Invalid escape sequences (lone backslash before non-escape char)
        - Control characters (ASCII < 32)
        """
        result = []
        i = 0
        in_string = False

        while i < len(text):
            c = text[i]

            # Inside a string: handle escape sequences
            if in_string and c == '\\':
                if i + 1 < len(text):
                    next_c = text[i + 1]
                    if next_c in '"\\\/bfnrtu':
                        # Valid JSON escape — pass through
                        result.append(c)
                        result.append(next_c)
                        i += 2
                        continue
                    else:
                        # Invalid escape (e.g. \S, \e) — escape the backslash
                        result.append('\\\\')
                        i += 1
                        continue
                else:
                    result.append('\\\\')
                    i += 1
                    continue

            if c == '"':
                if not in_string:
                    in_string = True
                    result.append(c)
                    i += 1
                    continue

                # Inside string, hit a quote — is it structural or content?
                # Look ahead past whitespace to see what follows
                j = i + 1
                while j < len(text) and text[j] in ' \t\r\n':
                    j += 1

                if j >= len(text) or text[j] in ',}]:':
                    # Structural delimiter follows → this closes the string
                    in_string = False
                    result.append(c)
                else:
                    # Something else follows (letter, number, etc.)
                    # → likely an unescaped quote inside the value
                    result.append('\\"')
                i += 1
                continue

            # Inside string: fix literal whitespace characters
            if in_string:
                if c == '\n':
                    result.append('\\n')
                    i += 1
                    continue
                elif c == '\r':
                    result.append('\\r')
                    i += 1
                    continue
                elif c == '\t':
                    result.append('\\t')
                    i += 1
                    continue
                elif ord(c) < 32:
                    # Strip other control characters
                    i += 1
                    continue

            result.append(c)
            i += 1

        return ''.join(result)

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

    async def _call_llm(self, prompt: str, model_name: str, temperature: float, max_retries: int = 3, json_mode: bool = False) -> (str, Dict):
        """Dispatch to the correct provider based on model ID."""
        if not model_name:
            model_name = get_default_model_id()
        provider = _get_provider(model_name)
        logger.info(f"LLM dispatch: model={model_name}, provider={provider}, json_mode={json_mode}")
        if provider == "anthropic":
            return await self._call_claude(prompt, model_name, temperature, max_retries, json_mode=json_mode)
        else:
            return await self._call_gemini(prompt, model_name, temperature, max_retries, json_mode=json_mode)

    async def _call_gemini(self, prompt: str, model_name: str, temperature: float, max_retries: int = 3, json_mode: bool = False) -> (str, Dict):
        gm = genai.GenerativeModel(model_name)
        config_kwargs = {"temperature": temperature}
        if json_mode:
            config_kwargs["response_mime_type"] = "application/json"
        config = genai.GenerationConfig(**config_kwargs)

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
                err_str = str(e)
                # Quota exceeded → stop immediately, don't retry
                if _is_quota_exceeded(err_str):
                    logger.error(f"Gemini quota exceeded: {e}")
                    raise QuotaExceededError(f"API quota exceeded: {e}")
                is_transient = any(code in err_str for code in ["500", "503", "504", "429", "DEADLINE", "overloaded"])
                if is_transient and attempt < max_retries - 1:
                    wait = (attempt + 1) * 3  # 3s, 6s, 9s
                    logger.warning(f"Gemini transient error (attempt {attempt+1}/{max_retries}): {e}. Retrying in {wait}s...")
                    await asyncio.sleep(wait)
                else:
                    raise e

    async def _call_claude(self, prompt: str, model_name: str, temperature: float, max_retries: int = 3, json_mode: bool = False) -> (str, Dict):
        if not self.anthropic_key:
            raise ValueError("ANTHROPIC_API_KEY not set")

        if not self._anthropic_client:
            self._anthropic_client = anthropic.AsyncAnthropic(api_key=self.anthropic_key)

        for attempt in range(max_retries):
            try:
                messages = [{"role": "user", "content": prompt}]
                # Prefill assistant response with "[" to force JSON array output
                if json_mode:
                    messages.append({"role": "assistant", "content": "["})

                res = await self._anthropic_client.messages.create(
                    model=model_name,
                    max_tokens=8192,
                    temperature=temperature,
                    messages=messages,
                )

                txt = res.content[0].text.strip()
                # Restore the prefilled "[" that Claude continues from
                if json_mode:
                    txt = "[" + txt
                usage = {
                    "input_tokens": res.usage.input_tokens,
                    "output_tokens": res.usage.output_tokens,
                }
                return txt, usage

            except Exception as e:
                err_str = str(e)
                # Quota exceeded → stop immediately, don't retry
                if _is_quota_exceeded(err_str):
                    logger.error(f"Claude quota exceeded: {e}")
                    raise QuotaExceededError(f"API quota exceeded: {e}")
                is_transient = any(code in err_str for code in ["500", "503", "529", "429", "overloaded"])
                if is_transient and attempt < max_retries - 1:
                    wait = (attempt + 1) * 3
                    logger.warning(f"Claude transient error (attempt {attempt+1}/{max_retries}): {e}. Retrying in {wait}s...")
                    await asyncio.sleep(wait)
                else:
                    raise e

    # ── Multi-turn Chat Methods ──────────────────────────────────────

    async def call_chat(self, system_prompt: str, messages: list, model_name: str, temperature: float = 0.4) -> (str, Dict):
        """Dispatch multi-turn chat to the correct provider."""
        if not model_name:
            model_name = get_default_model_id()
        provider = _get_provider(model_name)
        logger.info(f"Chat dispatch: model={model_name}, provider={provider}")
        if provider == "anthropic":
            return await self._call_claude_chat(system_prompt, messages, model_name, temperature)
        else:
            return await self._call_gemini_chat(system_prompt, messages, model_name, temperature)

    async def _call_gemini_chat(self, system_prompt: str, messages: list, model_name: str, temperature: float, max_retries: int = 2) -> (str, Dict):
        gm = genai.GenerativeModel(model_name, system_instruction=system_prompt)
        config = genai.GenerationConfig(temperature=temperature)

        gemini_history = [
            {"role": "user" if m["role"] == "user" else "model", "parts": [m["content"]]}
            for m in messages[:-1]
        ]
        last_msg = messages[-1]["content"]
        chat = gm.start_chat(history=gemini_history)

        for attempt in range(max_retries):
            try:
                if hasattr(chat, 'send_message_async'):
                    res = await chat.send_message_async(last_msg, generation_config=config)
                else:
                    loop = asyncio.get_event_loop()
                    res = await loop.run_in_executor(None, lambda: chat.send_message(last_msg, generation_config=config))

                txt = res.text.strip()
                usage = {"input_tokens": 0, "output_tokens": 0}
                if res.usage_metadata:
                    usage["input_tokens"] = res.usage_metadata.prompt_token_count
                    usage["output_tokens"] = res.usage_metadata.candidates_token_count
                return txt, usage

            except Exception as e:
                err_str = str(e)
                if _is_quota_exceeded(err_str):
                    logger.error(f"Gemini chat quota exceeded: {e}")
                    raise QuotaExceededError(f"API quota exceeded: {e}")
                is_transient = any(code in err_str for code in ["500", "503", "504", "429", "DEADLINE", "overloaded"])
                if is_transient and attempt < max_retries - 1:
                    wait = (attempt + 1) * 3
                    logger.warning(f"Gemini chat transient error (attempt {attempt+1}/{max_retries}): {e}. Retrying in {wait}s...")
                    await asyncio.sleep(wait)
                else:
                    raise e

    async def _call_claude_chat(self, system_prompt: str, messages: list, model_name: str, temperature: float, max_retries: int = 2) -> (str, Dict):
        if not self.anthropic_key:
            raise ValueError("ANTHROPIC_API_KEY not set")
        if not self._anthropic_client:
            self._anthropic_client = anthropic.AsyncAnthropic(api_key=self.anthropic_key)

        claude_messages = [{"role": m["role"], "content": m["content"]} for m in messages]

        for attempt in range(max_retries):
            try:
                res = await self._anthropic_client.messages.create(
                    model=model_name,
                    max_tokens=4096,
                    temperature=temperature,
                    system=system_prompt,
                    messages=claude_messages,
                )
                txt = res.content[0].text.strip()
                usage = {
                    "input_tokens": res.usage.input_tokens,
                    "output_tokens": res.usage.output_tokens,
                }
                return txt, usage

            except Exception as e:
                err_str = str(e)
                if _is_quota_exceeded(err_str):
                    logger.error(f"Claude chat quota exceeded: {e}")
                    raise QuotaExceededError(f"API quota exceeded: {e}")
                is_transient = any(code in err_str for code in ["500", "503", "529", "429", "overloaded"])
                if is_transient and attempt < max_retries - 1:
                    wait = (attempt + 1) * 3
                    logger.warning(f"Claude chat transient error (attempt {attempt+1}/{max_retries}): {e}. Retrying in {wait}s...")
                    await asyncio.sleep(wait)
                else:
                    raise e
