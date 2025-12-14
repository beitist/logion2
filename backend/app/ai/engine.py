import os
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field
from typing import List, Optional
from .memory import TranslationMemory

# --- Structured Output Schema ---
class TranslationResponse(BaseModel):
    translation_text: str = Field(description="The translated text, preserving tags exactly.")
    reasoning: str = Field(description="Explanation of terminology choices, style adaptations, or key decisions.")
    alternatives: List[str] = Field(description="1-2 alternative translations if impactful differences exist, or empty list.")

class AITranslator:
    def __init__(self, default_model: str = "gemini-2.5-pro"):
        self.memory = TranslationMemory()
        self.api_key = os.getenv("GOOGLE_API_KEY")
        self.default_model = default_model
        self.parser = JsonOutputParser(pydantic_object=TranslationResponse)
        
        # Cache specific LLM instances by model_name to avoid re-init overhead
        self._llm_cache = {}

    def _get_llm(self, model_name: str):
        if not self.api_key: return None
        
        # Check cache
        if model_name in self._llm_cache:
            return self._llm_cache[model_name]
            
        try:
            llm = ChatGoogleGenerativeAI(
                model=model_name, 
                temperature=0.3, 
                google_api_key=self.api_key
            )
            self._llm_cache[model_name] = llm
            return llm
        except Exception as e:
            print(f"Error init LLM {model_name}: {e}")
            return None

    def translate_segment(self, 
                          current_text: str, 
                          target_lang: str = "de", 
                          project_config: Optional[dict] = None,
                          prev_context: List[dict] = [],
                          next_context: List[dict] = [],
                          glossary_matches: List[dict] = []
                          ) -> dict:
        """
        Translates a single segment with Smart Context and Glossary.
        """
        # Determine Model
        model_name = self.default_model
        custom_prompt = ""
        
        if project_config:
            custom_prompt = project_config.get("custom_prompt", "")
            if project_config.get("ai_model"):
                model_name = project_config.get("ai_model")

        llm = self._get_llm(model_name)
        if not llm:
            return {"translation_text": f"AI_PASS: {current_text}", "reasoning": "No API Key"}

        try:
            # Prepare Context and Glossary
            prev_context_str = "\n".join([
                f"[Seg {s.get('index', '?')}] Source: {s.get('source')}\n[Seg {s.get('index', '?')}] Target: {s.get('target')}"
                for s in prev_context
            ]) or "None (Start)"
            
            next_context_str = "\n".join([
                f"[Seg {s.get('index', '?')}] Source: {s.get('source')}"
                for s in next_context
            ]) or "None (End)"
            
            glossary_str = "None"
            if glossary_matches:
                glossary_str = "\n".join([
                    f"- {m['source']} -> {m['target']} ({m.get('note', '')})"
                    for m in glossary_matches
                ])

            # System Prompt
            system_text = (
                f"You are a professional translator translating from Source to {target_lang}.\n"
                "Your goal is to produce a high-quality, context-aware translation that fits the document flow.\n\n"
                "CRITICAL INSTRUCTIONS:\n"
                "1. Preserve XML-like tags <n>...</n> EXACTLY.\n"
                "2. Preserve <n>[COMMENT]</n> tags.\n"
                "3. Preserve <n>LinkText</n> tags.\n"
                "4. Use GLOSSARY terms strictly if they appear in the source.\n"
                "5. Output must be valid JSON.\n"
            )
            
            # User Prompt
            user_template = """
            Project Settings / Instructions:
            {custom_prompt}
            
            ---
            GLOSSARY (Mandatory Terminology):
            {glossary_str}
            
            ---
            Previous Context:
            {prev_context}
            
            ---
            Following Context:
            {next_context}
            
            ---
            CURRENT SEGMENT TO TRANSLATE:
            {current_text}
            
            {format_instructions}
            """
            
            prompt = ChatPromptTemplate.from_messages([
                ("system", system_text),
                ("user", user_template)
            ])
            
            # Invoke Chain
            chain = prompt | llm | self.parser
            
            result = chain.invoke({
                "custom_prompt": custom_prompt,
                "prev_context": prev_context_str,
                "next_context": next_context_str,
                "glossary_str": glossary_str,
                "current_text": current_text,
                "format_instructions": self.parser.get_format_instructions()
            })
            
            return result
            
        except Exception as e:
            print(f"Error calling LLM: {e}")
            # Fallback to simple string return wrapped in dict
            return {
                "translation_text": f"[Error] {current_text}", 
                "reasoning": f"System Error: {str(e)}",
                "alternatives": []
            }

    def _dummy_fallback(self, text: str) -> str:
        return f"AI_PASS: {text}"
