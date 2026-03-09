import json
import logging
import os

import numpy as np
import streamlit as st
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# Load environment variables (like GROQ_API_KEY)
load_dotenv()

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
PARSED_JSON_FILE = os.path.join(DATA_DIR, "scf_parsed.json")
EMBEDDINGS_CACHE_FILE = os.path.join(DATA_DIR, "scf_embeddings.npy")

# Sentence-transformers model for embedding-based semantic retrieval
_EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"


class MappedControl(BaseModel):
    control_id: str = Field(description="The exact SCF ID, e.g., 'GOV-01'")
    domain: str = Field(description="The primary SCF Domain")
    confidence: int = Field(description="Confidence score from 0 to 100")
    justification: str = Field(
        description="A concise 1-sentence justification for why this control matches the input."
    )
    description: str = Field(
        default="",
        description="The full text description of the control from the SCF database.",
    )
    regulations: dict = Field(
        default_factory=dict,
        description="Regulatory frameworks mapped to this control.",
    )


class MappingResult(BaseModel):
    mappings: list[MappedControl] = Field(
        description="A list of the top recommended SCF controls."
    )


class ScopeRecommendation(BaseModel):
    recommended_domains: list[str] = Field(
        description="List of major SCF Domains relevant to the audit scope."
    )

    recommended_control_ids: list[str] = Field(
        description="List of specific SCF Control IDs recommended for testing based on the scope."
    )
    reasoning: str = Field(
        description="A brief comprehensive explanation of why these areas were selected based on the scope."
    )


@st.cache_resource(show_spinner="Loading SCF database...")
def load_scf_database():
    """Loads the parsed JSON database of the SCF framework. Cached across Streamlit reruns."""
    if not os.path.exists(PARSED_JSON_FILE):
        logger.warning("SCF Database not found. Please run fetch_scf.py first.")
        return []
    with open(PARSED_JSON_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


@st.cache_resource(show_spinner="Building semantic search index...")
def _get_embedding_model() -> SentenceTransformer:
    """Load the sentence-transformers model. Cached so it is only downloaded once."""
    return SentenceTransformer(_EMBEDDING_MODEL_NAME)


def _build_or_load_embeddings(scf_data: list[dict]) -> np.ndarray:
    """
    Build (or load from disk cache) embeddings for all SCF control descriptions.

    Embeddings are persisted to EMBEDDINGS_CACHE_FILE so they are computed
    only once per SCF release, not on every Streamlit rerun.
    """
    if os.path.exists(EMBEDDINGS_CACHE_FILE):
        logger.info("Loading cached SCF embeddings from %s", EMBEDDINGS_CACHE_FILE)
        return np.load(EMBEDDINGS_CACHE_FILE)

    logger.info(
        "Building SCF embeddings for %d controls (one-time cost)...", len(scf_data)
    )
    model = _get_embedding_model()
    texts = [f"{c['control_id']} {c['domain']}: {c['description']}" for c in scf_data]
    embeddings = model.encode(texts, show_progress_bar=False, convert_to_numpy=True)
    np.save(EMBEDDINGS_CACHE_FILE, embeddings)
    logger.info("Saved embeddings cache to %s", EMBEDDINGS_CACHE_FILE)
    return embeddings


def _semantic_filter(
    input_text: str, scf_data: list[dict], top_k: int = 50
) -> list[dict]:
    """
    Return the top_k most semantically similar SCF controls to the input text.

    Uses sentence-transformers (all-MiniLM-L6-v2) + cosine similarity instead of
    naive keyword matching — correctly handles synonyms like 'encryption'/'cryptography'.
    """
    model = _get_embedding_model()
    corpus_embeddings = _build_or_load_embeddings(scf_data)

    query_embedding = model.encode([input_text], convert_to_numpy=True)
    similarities = cosine_similarity(query_embedding, corpus_embeddings)[0]

    top_indices = np.argsort(similarities)[::-1][:top_k]
    results = [scf_data[i] for i in top_indices]
    logger.info(
        "Semantic filter: top-%d controls retrieved (best similarity=%.3f)",
        top_k,
        float(similarities[top_indices[0]]),
    )
    return results


def _validate_mapping_result(
    result: MappingResult, scf_dict: dict[str, dict]
) -> MappingResult:
    """
    Post-LLM validation: remove hallucinated control IDs and clamp confidence values.

    Checks each returned control_id against the live SCF database and filters out
    any IDs that do not exist. Confidence is clamped to [0, 100].
    """
    valid_mappings = []
    for m in result.mappings:
        if m.control_id not in scf_dict:
            logger.warning(
                "LLM hallucinated control ID '%s' — not found in SCF database. Dropping.",
                m.control_id,
            )
            continue
        m.confidence = max(0, min(100, m.confidence))
        valid_mappings.append(m)

    result.mappings = valid_mappings
    return result


def construct_scf_context(scf_data):
    """
    To avoid token limits, we format the SCF data concisely.
    For production with 1000+ controls, a Vector DB (RAG) is ideal.
    For this portfolio prototype using Llama-3's large context window,
    we will pass a condensed version of the controls.
    """
    condensed_list = []
    for control in scf_data:
        condensed_list.append(
            f"[{control['control_id']}] {control['domain']}: {control['description']}"
        )

    return "\n".join(condensed_list)


@retry(
    wait=wait_exponential(multiplier=1, min=2, max=60),
    stop=stop_after_attempt(3),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
def _invoke_chain(chain, inputs: dict):
    """Invoke a LangChain chain with exponential backoff retry for transient errors."""
    return chain.invoke(inputs)


def map_text_to_scf(input_text: str, top_k: int = 3, persona_prompt: str = None):
    """
    Takes an input string (policy snippet or JSON dump) and asks the LLM
    to map it to the top_k most relevant SCF controls.
    """
    scf_data = load_scf_database()
    if not scf_data:
        return None

    llm = ChatGroq(
        temperature=0, model_name=os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")
    )
    structured_llm = llm.with_structured_output(MappingResult)

    base_persona = "You are an expert IT Auditor and GRC Engineer."
    if persona_prompt:
        base_persona = f"{base_persona} {persona_prompt}"

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                f"{base_persona} Your task is to map the user's input (a policy snippet or a cloud security finding) to the most relevant controls from the Secure Controls Framework (SCF).\n\nHere is the SCF database:\n{{scf_context}}",
            ),
            (
                "user",
                "Please map the following input to the top {top_k} most relevant SCF controls.\n\nINPUT:\n{input_text}",
            ),
        ]
    )

    chain = prompt | structured_llm

    logger.info("Sending mapping request to Groq (Llama-3)...")

    # Semantic RAG filter: embed + cosine similarity instead of naive keyword matching
    filtered_scf = _semantic_filter(input_text, scf_data, top_k=50)

    context_str = construct_scf_context(filtered_scf)
    logger.info(
        "Semantic filter selected %d controls for LLM context.", len(filtered_scf)
    )

    response = _invoke_chain(
        chain, {"scf_context": context_str, "input_text": input_text, "top_k": top_k}
    )

    # Build lookup dict for validation and regulation enrichment
    scf_dict = {c["control_id"]: c for c in scf_data}

    # Post-LLM validation: drop hallucinated IDs, clamp confidence
    response = _validate_mapping_result(response, scf_dict)

    # Enrich with regulatory mappings from the database
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

    llm = ChatGroq(
        temperature=0, model_name=os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")
    )
    structured_llm = llm.with_structured_output(ScopeRecommendation)

    # Compress context to bypass strict Groq rate limits.
    # Instead of passing 1,451 IDs, we just pass the Domain and its specific ID Prefix.
    domain_prefixes = {}
    for c in scf_data:
        prefix = c["control_id"].split("-")[0]
        domain_prefixes[c["domain"]] = prefix

    context_lines = []
    for dom, prefix in domain_prefixes.items():
        context_lines.append(f"{dom} (Prefix: {prefix}-)")

    domain_context = (
        "Available SCF Domains and their Control ID Prefixes:\n"
        + "\n".join(context_lines)
    )

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are an expert IT Auditor. Provide a strategic test plan based on the provided audit scope. Use the provided SCF Domains to guide your recommendations. You MUST format the requested Control IDs using ONLY the EXACT prefix associated with the Domain, followed by a two or three digit number (e.g., 'CLD-01', 'CLD-02'). DO NOT include any additional text, descriptions, or punctuation in the control IDs list. Return a list of the highly relevant domains, 5-10 specific control IDs that must be tested (ONLY THE IDs), and a unified reasoning paragraph.\n\nContext:\n{domain_context}",
            ),
            ("user", "Audit Scope Document:\n\n{scope_text}"),
        ]
    )

    chain = prompt | structured_llm

    response = _invoke_chain(
        chain, {"domain_context": domain_context, "scope_text": scope_text}
    )

    return response


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # A simple test run if executed directly
    test_policy = "All cloud storage buckets (S3) must be configured to prohibit public read and write access to protect sensitive customer data."
    logger.info("Testing mapping engine on input: %s", test_policy)

    try:
        result = map_text_to_scf(test_policy)
        if result:
            logger.info("Mapping Results:")
            for mapping in result.mappings:
                logger.info(
                    " - %s (%s) [Confidence: %d%%]",
                    mapping.control_id,
                    mapping.domain,
                    mapping.confidence,
                )
                logger.info("   Justification: %s", mapping.justification)
                if mapping.regulations:
                    regs = list(mapping.regulations.keys())
                    display_regs = [
                        r
                        for r in regs
                        if "GDPR" in r
                        or "CCPA" in r
                        or "NIST" in r
                        or "ISO" in r
                        or "SOC 2" in r
                        or "PCI" in r
                    ]
                    if not display_regs:
                        display_regs = regs[:4]
                    logger.info(
                        "   Related Frameworks: %s (+%d more)",
                        ", ".join(display_regs),
                        len(regs) - len(display_regs),
                    )
    except Exception as e:
        logger.error("Error running Groq mapping: %s", e)
        logger.error("Ensure you have set your GROQ_API_KEY environment variable.")
