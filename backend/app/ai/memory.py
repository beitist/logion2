import chromadb
from chromadb.utils import embedding_functions
import os
from typing import List, Dict

# Persist DB in backend root for now
CHROMA_DB_PATH = "./chroma_db"

class TranslationMemory:
    def __init__(self):
        # Initialize Client
        self.client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
        
        # We use a default embedding function for now (SentenceTransformer usually)
        # Or OpenAI embeddings if key is present. 
        # Chroma default is all-MiniLM-L6-v2 (local, free). Good for MVP.
        self.ef = embedding_functions.DefaultEmbeddingFunction()
        
        # Get or Create Collection
        self.collection = self.client.get_or_create_collection(
            name="translation_memory",
            embedding_function=self.ef
        )

    def add_segment(self, source_text: str, target_text: str, source_lang: str, target_lang: str):
        """
        Adds a translation pair to the memory.
        """
        # ID strategy: simplified hash or random
        import hashlib
        doc_id = hashlib.md5(f"{source_text}{target_text}".encode()).hexdigest()
        
        self.collection.add(
            documents=[source_text],
            metadatas=[{
                "target": target_text,
                "source_lang": source_lang,
                "target_lang": target_lang
            }],
            ids=[doc_id]
        )

    def search_similar(self, source_text: str, n_results: int = 3) -> List[Dict]:
        """
        Returns similar segments usually for Few-Shot examples.
        """
        results = self.collection.query(
            query_texts=[source_text],
            n_results=n_results
        )
        
        # Format results
        hits = []
        if results['documents']:
            for i, doc in enumerate(results['documents'][0]):
                meta = results['metadatas'][0][i]
                hits.append({
                    "source": doc,
                    "target": meta["target"],
                    "distance": results['distances'][0][i] if results['distances'] else 0
                })
        return hits
