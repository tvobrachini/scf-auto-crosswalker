import os
import json
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

# Load environment variables (like GROQ_API_KEY)
load_dotenv()

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
PARSED_JSON_FILE = os.path.join(DATA_DIR, 'scf_parsed.json')

class MappedControl(BaseModel):
    control_id: str = Field(description="The exact SCF ID, e.g., 'GOV-01'")
    domain: str = Field(description="The primary SCF Domain")
    confidence: int = Field(description="Confidence score from 0 to 100")
    justification: str = Field(description="A concise 1-sentence justification for why this control matches the input.")
    regulations: dict = Field(default_factory=dict, description="Regulatory frameworks mapped to this control.")

class ScopeRecommendation(BaseModel):
    recommended_domains: list[str] = Field(description="List of major SCF Domains relevant to the audit scope.")
    recommended_control_ids: list[str] = Field(description="List of specific SCF Control IDs recommended for testing based on the scope.")
    reasoning: str = Field(description="A brief comprehensive explanation of why these areas were selected based on the scope.")

def load_scf_database():
    """Loads the parsed JSON database of the SCF framework."""
    if not os.path.exists(PARSED_JSON_FILE):
        print("[-] SCF Database not found. Please run fetch_scf.py first.")
        return []
    with open(PARSED_JSON_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def construct_scf_context(scf_data):
    """
    To avoid token limits, we format the SCF data concisely.
    For production with 1000+ controls, a Vector DB (RAG) is ideal. 
    For this portfolio prototype using Llama-3's large context window, 
    we will pass a condensed version of the controls.
    """
    condensed_list = []
    # If there are too many (1400+), we might need to truncate for the LLM 
    # context window, or use a naive keyword filter first. 
    # For now, let's load all and let the LLM handle the massive text blob if possible.
    for control in scf_data:
        condensed_list.append(f"[{control['control_id']}] {control['domain']}: {control['description']}")
    
    return "\n".join(condensed_list)

def map_text_to_scf(input_text: str, top_k: int = 3, persona_prompt: str = None):
    """
    Takes an input string (policy snippet or JSON dump) and asks the LLM 
    to map it to the top_k most relevant SCF controls.
    """
    scf_data = load_scf_database()
    if not scf_data:
        return None

    llm = ChatGroq(temperature=0, model_name="llama-3.3-70b-versatile")
    structured_llm = llm.with_structured_output(MappingResult)
    
    base_persona = "You are an expert IT Auditor and GRC Engineer."
    if persona_prompt:
        base_persona = f"{base_persona} {persona_prompt}"

    prompt = ChatPromptTemplate.from_messages([
        ("system", f"{base_persona} Your task is to map the user's input (a policy snippet or a cloud security finding) to the most relevant controls from the Secure Controls Framework (SCF).\n\nHere is the SCF database:\n{{scf_context}}"),
        ("user", "Please map the following input to the top {top_k} most relevant SCF controls.\n\nINPUT:\n{input_text}")
    ])

    chain = prompt | structured_llm

    print(f"[*] Sending mapping request to Groq (Llama-3)...")
    
    # We will pass the full context block. Llama-3-70b handles 8k tokens. 
    # The full SCF is ~50k-80k tokens. 
    # NOTE: Since 1451 controls might exceed the 8k window of `llama3-70b-8192`, 
    # we need a simple keyword filter to reduce the context size before sending.
    
    # Simple Keyword Filter (Naive RAG alternative)
    keywords = input_text.lower().replace(",", "").replace(".", "").split()
    filtered_scf = []
    for c in scf_data:
        desc = str(c['description']).lower()
        if any(kw in desc for kw in keywords if len(kw) > 4): # Only match words > 4 chars
            filtered_scf.append(c)

    # If the filter is too aggressive, fallback to a slice of the full DB
    if not filtered_scf:
        filtered_scf = scf_data[:100]
    else:
        # Sort by most keyword matches (very naive but works for a fast prototype)
        filtered_scf.sort(key=lambda c: sum(1 for kw in keywords if kw in str(c['description']).lower()), reverse=True)
        filtered_scf = filtered_scf[:50] # Send only top 50 matches to fit in token window

    context_str = construct_scf_context(filtered_scf)
    print(f"[*] Filtered context down to {len(filtered_scf)} potential controls to fit Groq context window.")

    response = chain.invoke({
        "scf_context": context_str,
        "input_text": input_text,
        "top_k": top_k
    })
    
    # Enrich the LLM response with the regulatory mappings from our database
    scf_dict = {c["control_id"]: c for c in scf_data}
    for mapping in response.mappings:
        if mapping.control_id in scf_dict:
            mapping.regulations = scf_dict[mapping.control_id].get("regulations", {})
            
    return response

def analyze_audit_scope(scope_text: str):
    """
    Takes an audit scope document/text and asks the LLM to recommend relevant SCF Domains and Controls to test.
    """
    scf_data = load_scf_database()
    if not scf_data:
        return None

    llm = ChatGroq(temperature=0, model_name="llama-3.3-70b-versatile")
    structured_llm = llm.with_structured_output(ScopeRecommendation)

    # We need to give the LLM a highly condensed version of domains and descriptions
    # to fit within the context, but let's give it the full list of domains at least.
    unique_domains = list(set([c["domain"] for c in scf_data]))
    domain_context = "Available SCF Domains: " + ", ".join(unique_domains)

    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are an expert IT Auditor. Provide a strategic test plan based on the provided audit scope. Use the provided SCF Domains to guide your recommendations. Return a list of the highly relevant domains, 5-10 specific control IDs that must be tested, and a unified reasoning paragraph.\n\nContext:\n{domain_context}"),
        ("user", "Audit Scope Document:\n\n{scope_text}")
    ])

    chain = prompt | structured_llm
    
    response = chain.invoke({
        "domain_context": domain_context,
        "scope_text": scope_text
    })

    return response

if __name__ == "__main__":
    # A simple test run if executed directly
    test_policy = "All cloud storage buckets (S3) must be configured to prohibit public read and write access to protect sensitive customer data."
    print(f"[*] Testing mapping engine on input:\n\"{test_policy}\"")
    
    try:
        result = map_text_to_scf(test_policy)
        if result:
            print("\n[+] Mapping Results:")
            for mapping in result.mappings:
                print(f" - {mapping.control_id} ({mapping.domain}) [Confidence: {mapping.confidence}%]")
                print(f"   Justification: {mapping.justification}")
                if mapping.regulations:
                    regs = list(mapping.regulations.keys())
                    display_regs = [r for r in regs if 'GDPR' in r or 'CCPA' in r or 'NIST' in r or 'ISO' in r or 'SOC 2' in r or 'PCI' in r]
                    if not display_regs:
                        display_regs = regs[:4]
                    print(f"   Related Frameworks: {', '.join(display_regs)} (+{len(regs) - len(display_regs)} more)")
    except Exception as e:
        print(f"\n[-] Error running Groq mapping: {e}")
        print("[-] Ensure you have set your GROQ_API_KEY environment variable.")
