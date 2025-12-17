import os
import json
import google.generativeai as genai
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from typing import Optional
from pydantic import BaseModel, Field
from typing import List

class PluralResponse(BaseModel):
    plural: str = Field(description="The plural form of the word.")
    language: str = Field(description="The detected language code (e.g. en, de, fr).")

load_dotenv()

# Konfiguration aus .env
from . import models
from sqlalchemy.orm import Session
API_KEY = os.getenv("GOOGLE_API_KEY")
if API_KEY:
    genai.configure(api_key=API_KEY)
import re

# --- Tag Compression Logic (Simulated Tag Groups) ---
# Compresses sequences of adjacent tags <1><2>... into single tokens <901>
# Decompresses them back after AI processing.

def _compress_tags(text: str) -> tuple[str, dict]:
    """
    Finds sequences of XML tags (e.g. <1><2>) and replaces them with <90X>.
    Uses stack-based matching to ensure <901>...<901> pairing where possible.
    """
    if not text:
        return text, {}
        
    mapping = {}
    counter = 901
    
    # We need to process the string linearly to handle nesting/pairing.
    # Regex to find ANY sequence of tags
    # Group 1: The full sequence
    tag_seq_pattern = re.compile(r'((?:</?\d+>)+)')
    
    matches = []
    for m in tag_seq_pattern.finditer(text):
        matches.append({
            "start": m.start(),
            "end": m.end(),
            "text": m.group(1),
            "is_close": "</" in m.group(1),
            "ids": re.findall(r'\d+', m.group(1))
        })
        
    # Stack for Open Tags: stores { "ids": [...], "syn_id": "901" }
    stack = []
    
    # We build the new string by slicing
    last_pos = 0
    new_text = ""
    
    for m in matches:
        # Append text before this tag match
        new_text += text[last_pos:m["start"]]
        
        assigned_id = None
        
        if not m["is_close"]:
            # OPEN TAG (or sequence)
            # Assign new ID
            assigned_id = str(counter)
            counter += 1
            
            # Use raw ID for mapping (no slash)
            mapping[assigned_id] = m["text"]
            
            # Push to stack
            stack.append({"ids": m["ids"], "syn_id": assigned_id})
            
            # Append replacement
            new_text += f"<{assigned_id}>"
            
        else:
            # CLOSE TAG (or sequence)
            # Try to match with top of stack
            # Logic: Close IDs [2, 1] should match Open IDs [1, 2] (Reversed)
            # But sometimes partial matches happen. 
            # Strict Exact Match is safest for "Group" logic.
            
            is_match = False
            if stack:
                top = stack[-1]
                # Check if IDs correspond (Reverse check)
                # match["ids"] are strings.
                if top["ids"] == m["ids"][::-1]:
                    # Match!
                    assigned_id = top["syn_id"]
                    stack.pop()
                    is_match = True
            
            if is_match:
                # Use same ID
                mapping[f"/{assigned_id}"] = m["text"]
                # XML style close
                new_text += f"</{assigned_id}>"
            else:
                # No match (Crossing or Orphan or Unbalanced)
                # Assign NEW unique ID to avoid confusion
                assigned_id = str(counter)
                counter += 1
                mapping[f"/{assigned_id}"] = m["text"]
                new_text += f"</{assigned_id}>"
                
        last_pos = m["end"]
        
    # Append rest of text
    new_text += text[last_pos:]
    
    return new_text, mapping

def _decompress_tags(text: str, mapping: dict) -> str:
    """
    Restores tags from <90X> or </90X> using the mapping.
    """
    if not text or not mapping:
        return text
        
    # We iterate the known keys in the mapping and replace?
    # Or strict regex for 900s?
    # Strict regex is better to finding what the AI outputted.
    
    def repl(match):
        token = match.group(1) # "901" or "/901"
        is_close = token.startswith("/")
        
        # Cleanup token to key
        key = token
        
        if key in mapping:
            return mapping[key]
        
        # Fallback: If AI made up a tag <999>, we strip it or leave it?
        # If we leave it, it breaks XML parsing likely.
        # But if it's unknown, maybe it corresponds to a lost tag.
        return "" # Remove hallucinated system tags
        
    return re.sub(r'<([/]?9\d\d)>', repl, text)

# Export for use in other modules
def compress_tags_for_ai(text): return _compress_tags(text)
def decompress_tags_from_ai(text, mapping): return _decompress_tags(text, mapping)


def get_ai_response(project_title: str, user_message: str, history: list):
    """
    Generiert eine Antwort basierend auf dem Projektkontext.
    Nutzt den vom Frontend übergebenen System-Prompt (mit LogFrame-Kontext).
    """
    if not API_KEY:
        return "⚠️ Kein API-Key konfiguriert. Bitte GOOGLE_API_KEY in .env setzen."

    # 1. System Prompt und History extrahieren
    system_instruction = f"Du bist ein erfahrener Solution Architect für NGO-Projekte. Projekt: {project_title}."
    chat_history = []

    if history:
        # Check for System Prompt in history (usually the first item)
        if history[0].get('role') == 'system':
            system_instruction = history[0].get('parts', [""])[0]
            # Filter out system message from chat history
            raw_history = history[1:]
        else:
            raw_history = history

        # Map frontend roles to Gemini roles ('ai' -> 'model', 'user' -> 'user')
        for msg in raw_history:
            role = 'model' if msg.get('role') == 'ai' else 'user'
            parts = msg.get('parts', [])
            if parts:
                chat_history.append({"role": role, "parts": parts})

    # 2. Modell initialisieren mit System Instruction
    model = genai.GenerativeModel('gemini-2.0-flash', system_instruction=system_instruction)

    # 3. Chat starten
    chat = model.start_chat(history=chat_history)
    
    try:
        response = chat.send_message(user_message)
        text_response = response.text.strip()
        
        # Versuch, JSON zu parsen (Falls die KI Vorschläge macht)
        if text_response.startswith("{") and "type" in text_response:
            return text_response 
            
        return text_response
        
    except Exception as e:
        return f"Fehler bei der KI-Anfrage: {str(e)}"

# --- LANGCHAIN IMPLEMENTATION ---

class DescriptionSuggestion(BaseModel):
    suggestion: str = Field(description="The generated description text for the logframe activity.")
    reasoning: str = Field(description="Brief explanation of why this description fits.")

class IndicatorSuggestion(BaseModel):
    description: str = Field(description="The SMART indicator description.")
    baseline_value: str = Field(description="Suggested baseline (e.g., '0' or 'TBD').")
    target_value: str = Field(description="Suggested target value.")
    source_of_verification: str = Field(description="Suggested means of verification.")
    source_of_verification: str = Field(description="Suggested means of verification.")
    reasoning: str = Field(description="Why this indicator is suitable.")

class RiskSuggestion(BaseModel):
    category: str = Field(description="Risk category: 'contextual', 'programmatic', 'institutional', 'safety'.")
    description: str = Field(description="Description of the risk (e.g. 'Inflation rises above 10%').")
    mitigation: str = Field(description="Mitigation strategy.")
    probability: int = Field(description="Probability level (1-5).")
    impact: int = Field(description="Impact level (1-5).")

class RiskAnalysisResult(BaseModel):
    risks: List[RiskSuggestion] = Field(description="List of 3 identified risks.")

def generate_description(data: dict):
    if not API_KEY:
        return {"suggestion": "Error: No API Key configured."}

    # 1. Setup Model
    llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash", google_api_key=API_KEY, temperature=0.7)
    
    # 2. Setup Parser
    parser = JsonOutputParser(pydantic_object=DescriptionSuggestion)

    # 3. Setup Prompt
    template = """
    You are an expert proposal writer for NGO projects. Your task is to generate a detailed, professional, and specific description for a LogFrame activity based on the provided context.

    Context:
    - Project: {project_title}
    - Problem: {problem_description}
    - LogFrame Hierarchy: {logframe_path}
    - Target Group: {target_group}
    - Budget/Resources: {budget_info}

    Instructions:
    - Write a clear, action-oriented description.
    - Be specific about what will be done.
    - Incorporate the target group and budget details if relevant (e.g., "Conduct 5 workshops for 100 youths...").
    - Keep it concise but comprehensive (2-3 sentences).
    - Output MUST be valid JSON with 'suggestion' and 'reasoning' fields.

    {format_instructions}
    """

    prompt = PromptTemplate(
        template=template,
        input_variables=["project_title", "problem_description", "logframe_path", "target_group", "budget_info"],
        partial_variables={"format_instructions": parser.get_format_instructions()}
    )

    # 4. Execute Chain
    chain = prompt | llm | parser

    try:
        # Extract data safely
        ctx = data.get('project_context', {})
        
        # Format LogFrame Path for readability
        path_str = " > ".join([f"{node.get('levelName')} ({node.get('description')})" for node in data.get('logframe_path', [])])
        
        # Format Budget
        budget_str = ", ".join([f"{b.get('description')} ({b.get('amount')} {b.get('unit')})" for b in data.get('budget_info', [])])
        
        # Format Target Group
        tg = data.get('target_group', {})
        tg_str = f"{tg.get('name')} (Count: {tg.get('count')})"

        result = chain.invoke({
            "project_title": ctx.get('title', 'Unknown Project'),
            "problem_description": ctx.get('problem_description', 'N/A'),
            "logframe_path": path_str,
            "target_group": tg_str,
            "budget_info": budget_str
        })
        
        return result

    except Exception as e:
        print(f"LangChain Error: {e}")
        return {"suggestion": f"Error generating description: {str(e)}", "reasoning": "System Error"}

def generate_indicator_suggestion(data: dict):
    if not API_KEY:
        return {"description": "Error: No API Key", "reasoning": "Configuration missing"}

    llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash", google_api_key=API_KEY, temperature=0.7)
    parser = JsonOutputParser(pydantic_object=IndicatorSuggestion)

    mode = data.get('mode', 'create') # create, find, match
    candidates = data.get('candidates', [])
    candidates_str = "\n".join([f"- ID {c.get('value')}: {c.get('label')}" for c in candidates])

    # Common Context
    base_template = """
    You are an expert M&E (Monitoring and Evaluation) specialist for NGO projects.
    Context:
    - Project: {project_title}
    - LogFrame Hierarchy: {logframe_path}
    - Activity Description: {activity_description}
    - Existing/Draft Indicator: {user_draft}
    
    Available Framework Indicators (Candidates):
    {candidates}
    """

    if mode == 'find':
        instruction = """
        Task: Identify the BEST matching indicator from the candidates list and ADAPT it to the local context.
        - You MUST select one candidate ID and set it as 'alignment_id'.
        - Refine the description to be specific to the activity (localize it).
        - Suggest Baseline (usually 0).
        - Suggest Target: MUST be a specific value with unit (e.g. "500 Households", "80%", "5 Schools"). NOT a sentence.
        - Suggest Source of Verification.
        - LANGUAGE: Respond in the same language as the Activity Description.
        - Ensure 'reasoning' is populated with a clear explanation.
        """
    elif mode == 'match':
        instruction = """
        Task: Find the best framework alignment for the user's draft indicator.
        - Compare the 'Existing/Draft Indicator' with the candidates.
        - Return the best matching 'alignment_id' and the 'description' (clean up the draft if needed).
        - Suggest Baseline/Target/SoV matches the draft. Target MUST be value+unit.
        - Argument why it matches in 'reasoning'.
        - LANGUAGE: Respond in the same language as the draft.
        - Ensure 'reasoning' is populated with a clear explanation.
        """
    else: # 'create' (default)
        instruction = """
        Task: Create a NEW, high-quality SMART indicator.
        - LOOK at the candidates for INSPIRATION on phrasing and standards.
        - If a candidate is a good match, use its ID as 'alignment_id', otherwise leave it null.
        - Suggest Baseline (0 for new projects).
        - Suggest Target: MUST be a specific value with unit (e.g. "500 Households", "80%").
        - Suggest Source of Verification.
        - LANGUAGE: Respond in the same language as the Activity Description.
        - Ensure 'reasoning' is populated with a clear explanation.
        """

    final_prompt = base_template + "\n" + instruction + "\n{format_instructions}"

    prompt = PromptTemplate(
        template=final_prompt,
        input_variables=["project_title", "logframe_path", "activity_description", "user_draft", "candidates"],
        partial_variables={"format_instructions": parser.get_format_instructions()}
    )

    chain = prompt | llm | parser

    try:
        ctx = data.get('project_context', {})
        path_str = " > ".join([f"{node.get('levelName')} ({node.get('description')})" for node in data.get('logframe_path', [])])
        
        result = chain.invoke({
            "project_title": ctx.get('title', 'Unknown Project'),
            "logframe_path": path_str,
            "activity_description": data.get('activity_description', ''),
            "user_draft": data.get('user_draft', ''),
            "candidates": candidates_str
        })
        return result
    except Exception as e:
        print(f"AI Error: {e}")
    except Exception as e:
        print(f"AI Error: {e}")
        return {"description": "Error generating indicator.", "reasoning": str(e)}

def analyze_risks(data: dict):
    if not API_KEY:
        return {"risks": []}
        
    llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash", google_api_key=API_KEY, temperature=0.7)
    parser = JsonOutputParser(pydantic_object=RiskAnalysisResult)
    
    template = """
    You are an experienced Risk Manager for NGO organizations.
    Task: Identify 3 potential risks for the following activity.
    Estimate Probability (1-5) and Impact (1-5) conservatively.
    
    Context:
    - Project: {project_title}
    - Activity: {activity_description}
    - Location/Context: {project_location}
    
    Ensure categories are one of: 'contextual', 'programmatic', 'institutional', 'safety'.
    
    {format_instructions}
    """
    
    prompt = PromptTemplate(
        template=template,
        input_variables=["project_title", "activity_description", "project_location"],
        partial_variables={"format_instructions": parser.get_format_instructions()}
    )
    
    chain = prompt | llm | parser
    
    try:
        ctx = data.get('project_context', {})
        res = chain.invoke({
            "project_title": ctx.get('title', 'Unknown Project'),
            "activity_description": data.get('activity_description', ''),
            "project_location": ctx.get('country', 'Unknown Location')
        })
        return res
    except Exception as e:
        print(f"Risk AI Error: {e}")
        return {"risks": []}

def generate_plural(word: str, db: Session = None):
    # 1. Check Cache
    if db:
        cached = db.query(models.AiWordCache).filter(models.AiWordCache.word == word.strip()).first()
        if cached:
            print(f"DEBUG: Cache hit for '{word}' -> '{cached.plural}'")
            return {"plural": cached.plural, "language": cached.language}

    if not API_KEY:
        return {"plural": word + "s", "language": "unknown"} # Fallback

    llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash", google_api_key=API_KEY, temperature=0.1)
    parser = JsonOutputParser(pydantic_object=PluralResponse)

    template = """
    Task: Convert the given singular noun to its plural form.
    - Detect the language of the input word.
    - Return the plural form in that language.
    - If it's already plural, return as is.
    - If the word represents a concept with no commonly used plural (e.g. "Peace", "Monitoring"), return the singular form as the plural.
    
    Word: {word}
    
    {format_instructions}
    """

    prompt = PromptTemplate(
        template=template,
        input_variables=["word"],
        partial_variables={"format_instructions": parser.get_format_instructions()}
    )

    chain = prompt | llm | parser

    try:
        result = chain.invoke({"word": word})
        
        # 2. Save to Cache
        if db and result.get('plural'):
            # Double check race condition or just try/except
            try:
                new_cache = models.AiWordCache(
                    word=word.strip(),
                    plural=result['plural'],
                    language=result.get('language', 'unknown')
                )
                db.add(new_cache)
                db.commit()
            except Exception as e:
                db.rollback()
                print(f"Cache Save Error: {e}")
                
        return result


    except Exception as e:
        print(f"Plural AI Error: {e}")
        return {"plural": word, "language": "error"}

class NarrativeImprovementResponse(BaseModel):
    improved_text: str = Field(description="The rewritten or generated text.")
    reasoning: str = Field(description="Brief explanation of changes.")

def improve_narrative_text(data: dict):
    if not API_KEY:
        return {"improved_text": data.get('text', ''), "reasoning": "Error: No API Key configured."}

    llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash", google_api_key=API_KEY, temperature=0.7)
    parser = JsonOutputParser(pydantic_object=NarrativeImprovementResponse)

    # Context Extraction
    ctx = data.get('context_data', {})
    project_title = ctx.get('project', {}).get('title', 'Unknown Project')
    
    # Simple Context Helper
    logframe_summary = "N/A"
    if ctx.get('logframe'):
        # Extract top 3 activities
        logframe_summary = ", ".join([n.get('description', '') for n in ctx.get('logframe', [])[:3]])

    risks_summary = "N/A"
    if ctx.get('risks'):
         risks_summary = ", ".join([r.get('description', '') for r in ctx.get('risks', [])[:3]])

    template = """
    You are an expert NGO proposal writer.
    Task: {instruction}
    
    Context:
    - Project: {project_title}
    - Key Activities: {logframe_summary}
    - Key Risks: {risks_summary}
    - Target Group Summary: {beneficiary_summary}

    Input Text (Keywords or Draft):
    "{text}"

    Instructions:
    - If "Draft from Keywords": Treat the input as keywords/notes and write 2-5 professional paragraphs connecting them to the project context.
    - If "Improve/Fix": Rewrite the input text to be more professional, precise, and impactful ("NGO-Speak").
    - If "Shorten": Condense the text without losing key information.
    - If "Lengthen": Expand on the points, connecting them to the LogFrame/Risks context.
    - Output valid JSON.

    {format_instructions}
    """

    prompt = PromptTemplate(
        template=template,
        input_variables=["instruction", "project_title", "logframe_summary", "risks_summary", "beneficiary_summary", "text"],
        partial_variables={"format_instructions": parser.get_format_instructions()}
    )

    chain = prompt | llm | parser

    try:
        instruction_map = {
            "fix": "Improve grammar and professional tone.",
            "shorter": "Shorten the text significantly.",
            "longer": "Expand the text with more detail and context.",
            "draft": "Draft a detailed narrative (2-5 paragraphs) based on these keywords.",
             # Fallback
            "improve": "Improve writing style."
        }
        
        user_instr = data.get('instruction', 'improve').lower()
        instruction_text = instruction_map.get(user_instr, user_instr)

        result = chain.invoke({
            "instruction": instruction_text,
            "project_title": project_title,
            "logframe_summary": logframe_summary,
            "risks_summary": risks_summary,
            "beneficiary_summary": ctx.get('beneficiary_summary', "N/A"),
            "text": data.get('text', '')
        })
        
        return result

    except Exception as e:
        print(f"Narrative AI Error: {e}")
        return {"improved_text":Data.get('text', ''), "reasoning": f"Error: {str(e)}"}