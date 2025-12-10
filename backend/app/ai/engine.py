import os
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from .memory import TranslationMemory

class AITranslator:
    def __init__(self):
        self.memory = TranslationMemory()
        
        # User requested LangChain as "pass" / placeholder for now.
        # We prepare the client but don't force it to be used yet if no key.
        self.llm = None
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key:
            self.llm = ChatOpenAI(model="gpt-3.5-turbo", temperature=0.3)
        else:
            print("WARN: No OPENAI_API_KEY found. AI Translation will fall back to dummy mode.")

    def translate_segment(self, source_text: str, target_lang: str = "de") -> str:
        """
        Translates a single segment.
        """
        # 1. Check Memory (RAG)
        # similar = self.memory.search_similar(source_text)
        # Setup for future RAG usage
        
        # 2. Translate
        if self.llm:
            try:
                # Improved prompt for new tags
                system_text = (
                    f"You are a professional translator. Translate the text to {target_lang}. "
                    "1. Preserve XML-like tags <n>...</n> exactly. "
                    "2. Preserve <n>[COMMENT]</n> tags and do NOT translate the marker. "
                    "3. Preserve <n>LinkText</n> tags but translate the content inside if it is text."
                )
                prompt = ChatPromptTemplate.from_messages([
                    ("system", system_text),
                    ("user", "{text}")
                ])
                chain = prompt | self.llm | StrOutputParser()
                return chain.invoke({"text": source_text})
            except Exception as e:
                print(f"Error calling LLM: {e}")
                return self._dummy_fallback(source_text)
        else:
            return self._dummy_fallback(source_text)

    def _dummy_fallback(self, text: str) -> str:
        """
        Fallback logic (from dummy_translator)
        """
        return f"AI_PASS: {text}"
