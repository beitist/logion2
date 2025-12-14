import os
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.pydantic_v1 import BaseModel, Field
from typing import List, Optional
from .memory import TranslationMemory

# --- Structured Output Schema ---
class TranslationResponse(BaseModel):
    translation_text: str = Field(description="The translated text, preserving tags exactly.")
    reasoning: str = Field(description="Explanation of terminology choices, style adaptations, or key decisions.")
    alternatives: List[str] = Field(description="1-2 alternative translations if impactful differences exist, or empty list.")

class AITranslator:
    def __init__(self, model_name: str = "gemini-2.0-pro-exp-02-05"):
        self.memory = TranslationMemory()
        
        # Switched to Gemini (User Request)
        self.llm = None
        api_key = os.getenv("GOOGLE_API_KEY")
        
        # User requested specific models. Default: gemini-2.5-pro (mapped to actual ID if known, else pass through)
        # Note: "gemini-2.5-pro" is likely "gemini-1.5-pro" or a future preview. 
        # For now, we allow passing the model_name.
        
        if api_key:
            # We use a high context model by default
            self.llm = ChatGoogleGenerativeAI(
                model=model_name, 
                temperature=0.3, 
                google_api_key=api_key
            )
            
            # Setup Parser
            self.parser = JsonOutputParser(pydantic_object=TranslationResponse)
        else:
            print("WARN: No GOOGLE_API_KEY found. AI Translation will fall back to dummy mode.")

    def translate_segment(self, 
                          current_text: str, 
                          target_lang: str = "de", 
                          project_config: Optional[dict] = None,
                          prev_context: List[dict] = [],
                          next_context: List[dict] = []
                          ) -> dict:
        """
        Translates a single segment with Smart Context.
        Returns a dict: {'translation_text': str, 'reasoning': str, ...}
        """
        # 1. Dummy Fallback
        if not self.llm:
            return {"translation_text": f"AI_PASS: {current_text}", "reasoning": "No API Key"}

        try:
            # 2. Prepare Context Strings
            custom_prompt = ""
            if project_config:
                # Extract custom prompt from config (assuming structure)
                # config might be {"custom_prompt": "..."} or raw dict
                custom_prompt = project_config.get("custom_prompt", "")
                
            prev_context_str = "\n".join([
                f"[Seg {s.get('index', '?')}] Source: {s.get('source')}\n[Seg {s.get('index', '?')}] Target: {s.get('target')}"
                for s in prev_context
            ])
            
            next_context_str = "\n".join([
                f"[Seg {s.get('index', '?')}] Source: {s.get('source')}"
                for s in next_context
            ])
            
            # 3. Construct System Prompt
            system_text = (
                f"You are a professional translator translating from Source to {target_lang}.\n"
                "Your goal is to produce a high-quality, context-aware translation that fits the document flow.\n\n"
                "CRITICAL INSTRUCTIONS:\n"
                "1. Preserve XML-like tags <n>...</n> EXACTLY. Do not translate them, do not reorder them unless grammar requires it.\n"
                "2. Preserve <n>[COMMENT]</n> tags and do NOT translate the marker.\n"
                "3. Preserve <n>LinkText</n> tags but translate the content inside if it is text.\n"
                "4. Output must be valid JSON.\n"
            )
            
            # 4. Construct Human Prompt with Context
            user_template = """
            Project Settings / Instructions:
            {custom_prompt}
            
            ---
            Previous Context (The story so far):
            {prev_context}
            
            ---
            Following Context (Preview):
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
            
            # 5. Invoke Chain
            chain = prompt | self.llm | self.parser
            
            result = chain.invoke({
                "custom_prompt": custom_prompt,
                "prev_context": prev_context_str if prev_context else "None (Start of Document)",
                "next_context": next_context_str if next_context else "None (End of Document)",
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
