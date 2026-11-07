"""
DEMO_MODE: run all three tools with no API key and no network access.

With ``DEMO_MODE=1`` (also true/yes/on), `mapper` swaps exactly three things:

- ``load_scf_database()`` returns ``DEMO_CATALOG``, a small synthetic control
  catalog written for this project. It contains no SCF control text and no
  SCF control IDs: SCF data is CC BY-ND 4.0 and this repository does not host
  it. IDs use made-up domain prefixes that start with ``D`` (``DCRY-01``,
  ``DIAM-02``, ...). The crosswalk columns name real frameworks (NIST SP
  800-53, ISO 27001, ...) with illustrative references.
- ``_get_embedding_model()`` returns ``DemoEmbeddingModel``, a hashed
  bag-of-words encoder (no Hugging Face download).
- ``_get_llm()`` returns ``CannedChatModel``, which answers through the same
  ``with_structured_output(schema)`` interface as ChatOpenAI. It picks the
  top-ranked retrieved candidates with fixed confidences and template
  justifications that say they are demo output. It also returns one ID that is
  not among the candidates (``AC-2``, a NIST SP 800-53 ID), on purpose, so the
  UI shows validation rejecting it.

Retrieval ranking, validation, enrichment, batching and ranking, the gap
analysis and the CSV/OSCAL exports are the real code, running on demo data.
Demo output says nothing about the accuracy of the real pipeline.

DEMO_MODE is refused when ``ENVIRONMENT`` is production or staging.
"""

import os
import re
import zlib

import numpy as np
from langchain_core.runnables import RunnableLambda

DEMO_BADGE = "DEMO MODE — synthetic catalog, canned model"
DEMO_NOTICE = (
    "DEMO DATA: generated in DEMO_MODE from a synthetic demo catalog (not SCF "
    "content) and a canned stand-in for the language model (no LLM was called). "
    "It says nothing about the accuracy of the real pipeline."
)
DEMO_CATALOG_TITLE = (
    "Synthetic demo catalog (DEMO_MODE; not the Secure Controls Framework)"
)
DEMO_EMBEDDING_MODEL_NAME = "demo-hashed-bag-of-words"

# Returned by the canned model on every call, deliberately, so the UI's
# "not among the candidates" warning is visible in the demo.
DEMO_REJECTED_ID = "AC-2"

_TRUTHY = {"1", "true", "yes", "on"}
_BLOCKED_ENVIRONMENTS = {"production", "prod", "staging", "stage"}


class DemoModeNotAllowedError(RuntimeError):
    """DEMO_MODE was requested in an environment where it is refused."""


def demo_mode_requested() -> bool:
    return os.environ.get("DEMO_MODE", "").strip().lower() in _TRUTHY


def demo_mode_enabled() -> bool:
    """True when DEMO_MODE is on; raises if it is on in production or staging."""
    if not demo_mode_requested():
        return False
    environment = os.environ.get("ENVIRONMENT", "local").strip().lower()
    if environment in _BLOCKED_ENVIRONMENTS:
        raise DemoModeNotAllowedError(
            f"DEMO_MODE is not allowed when ENVIRONMENT={environment!r}: demo mode "
            "replaces the SCF data and the language model with synthetic stand-ins. "
            "Unset DEMO_MODE for this deployment."
        )
    return True


# --- Synthetic catalog -------------------------------------------------------------
# Written for this demo. Control statements are generic; framework references
# are illustrative, not an authoritative crosswalk.

_NIST = "NIST 800-53 rev5"
_CSF = "NIST CSF 2.0"
_ISO = "ISO 27001 v2022"
_SOC = "AICPA SOC 2 (2017)"
_PCI = "PCI DSS v4.0"


def _control(cid, domain, weight, description, question, regulations):
    return {
        "control_id": cid,
        "domain": domain,
        "description": description,
        "weight": weight,
        "erl": f"Demo evidence for {cid}",
        "question": question,
        "regulations": regulations,
    }


DEMO_CATALOG: list[dict] = [
    _control(
        "DGOV-01",
        "Demo Governance",
        9,
        "A security policy is approved by management, published to staff and reviewed every year.",
        "Is the security policy approved, published and reviewed annually?",
        {_NIST: "PM-1", _CSF: "GV.PO-01", _ISO: "5.1", _SOC: "CC5.3"},
    ),
    _control(
        "DGOV-02",
        "Demo Governance",
        6,
        "Staff complete security awareness training when they join and every year after.",
        "Do all staff complete security awareness training?",
        {
            _NIST: "AT-2",
            _ISO: "6.3",
            _SOC: "CC2.2",
            _PCI: "12.6.1",
            "HIPAA": "164.308(a)(5)",
        },
    ),
    _control(
        "DCRY-01",
        "Demo Encryption",
        10,
        "Stored data, including databases, storage buckets and backups, is encrypted at rest with strong algorithms such as AES-256.",
        "Is sensitive data encrypted at rest?",
        {
            _NIST: "SC-28",
            _CSF: "PR.DS-01",
            _ISO: "8.24",
            _SOC: "CC6.1",
            _PCI: "3.5.1",
            "GDPR": "Art 32",
            "HIPAA": "164.312(a)(2)(iv)",
        },
    ),
    _control(
        "DCRY-02",
        "Demo Encryption",
        9,
        "Data in transit is encrypted with TLS: web endpoints and content delivery services accept HTTPS only or redirect HTTP to HTTPS.",
        "Is data encrypted in transit over public and internal networks?",
        {
            _NIST: "SC-8",
            _CSF: "PR.DS-02",
            _ISO: "8.24",
            _SOC: "CC6.7",
            _PCI: "4.2.1",
            "GDPR": "Art 32",
            "HIPAA": "164.312(e)(1)",
        },
    ),
    _control(
        "DCRY-03",
        "Demo Encryption",
        7,
        "Encryption keys are generated, stored, rotated and retired through a managed key service.",
        "Are encryption keys managed and rotated?",
        {_NIST: "SC-12", _ISO: "8.24", _SOC: "CC6.1", _PCI: "3.6.1"},
    ),
    _control(
        "DIAM-01",
        "Demo Identity & Access",
        8,
        "Every user has a unique account that is created on approval and removed promptly when the user leaves.",
        "Are user accounts unique, approved and removed on departure?",
        {
            _NIST: "AC-2",
            _CSF: "PR.AA-01",
            _ISO: "5.16",
            _SOC: "CC6.2",
            _PCI: "8.2.1",
            "HIPAA": "164.312(a)(2)(i)",
        },
    ),
    _control(
        "DIAM-02",
        "Demo Identity & Access",
        10,
        "Multi-factor authentication (MFA) is required for administrator, developer and remote access to systems and cloud consoles.",
        "Is MFA enforced for privileged and remote access?",
        {_NIST: "IA-2(1)", _CSF: "PR.AA-03", _ISO: "8.5", _SOC: "CC6.1", _PCI: "8.4.2"},
    ),
    _control(
        "DIAM-03",
        "Demo Identity & Access",
        6,
        "Access rights are reviewed by system owners every quarter and excess privileges are revoked.",
        "Are access rights reviewed periodically?",
        {_NIST: "AC-6(7)", _ISO: "5.18", _SOC: "CC6.3", _PCI: "7.2.4"},
    ),
    _control(
        "DLOG-01",
        "Demo Logging & Monitoring",
        8,
        "Security events, including logins, failed access attempts and administrative actions, are logged centrally and retained.",
        "Are security events logged centrally?",
        {
            _NIST: "AU-2",
            _CSF: "DE.CM-03",
            _ISO: "8.15",
            _SOC: "CC7.2",
            _PCI: "10.2.1",
            "HIPAA": "164.312(b)",
        },
    ),
    _control(
        "DLOG-02",
        "Demo Logging & Monitoring",
        8,
        "Monitoring raises alerts on suspicious activity and unauthorized access attempts, and the security operations team triages them.",
        "Are alerts raised and triaged for suspicious activity?",
        {_NIST: "SI-4", _CSF: "DE.AE-02", _ISO: "8.16", _SOC: "CC7.3", _PCI: "10.4.1"},
    ),
    _control(
        "DEND-01",
        "Demo Endpoint Security",
        7,
        "Corporate laptops and mobile devices use full-disk encryption and are managed centrally.",
        "Are laptops and mobile devices encrypted and managed?",
        {_NIST: "AC-19(5)", _ISO: "8.1", _SOC: "CC6.8", "GDPR": "Art 32"},
    ),
    _control(
        "DEND-02",
        "Demo Endpoint Security",
        5,
        "Lost or stolen devices are reported promptly and wiped remotely.",
        "Can lost or stolen devices be wiped remotely?",
        {_NIST: "AC-19", _ISO: "6.7"},
    ),
    _control(
        "DEND-03",
        "Demo Endpoint Security",
        4,
        "Use of removable media such as USB drives is restricted, and company data on it must be encrypted.",
        "Is removable media restricted?",
        {_NIST: "MP-7", _ISO: "7.10", _SOC: "CC6.7"},
    ),
    _control(
        "DNET-01",
        "Demo Network Security",
        8,
        "Firewalls and security groups restrict network traffic to what is required, and production networks are segmented.",
        "Is network traffic restricted and segmented?",
        {_NIST: "SC-7", _CSF: "PR.IR-01", _ISO: "8.20", _SOC: "CC6.6", _PCI: "1.2.1"},
    ),
    _control(
        "DNET-02",
        "Demo Network Security",
        6,
        "Public web applications sit behind a web application firewall and a content delivery network.",
        "Are public web applications protected at the edge?",
        {_NIST: "SC-7", _ISO: "8.20", _SOC: "CC6.6", _PCI: "6.4.2"},
    ),
    _control(
        "DVUL-01",
        "Demo Vulnerability Management",
        8,
        "Systems are scanned for vulnerabilities and missing patches, and findings are fixed within set timeframes.",
        "Are vulnerabilities scanned for and remediated on time?",
        {_NIST: "RA-5", _CSF: "ID.RA-01", _ISO: "8.8", _SOC: "CC7.1", _PCI: "11.3.1"},
    ),
    _control(
        "DBCR-01",
        "Demo Resilience",
        7,
        "Backups are taken daily, stored separately and restored in a test at least once a year.",
        "Are backups taken and restore-tested?",
        {
            _NIST: "CP-9",
            _CSF: "PR.DS-11",
            _ISO: "8.13",
            _SOC: "A1.2",
            "HIPAA": "164.308(a)(7)",
        },
    ),
    _control(
        "DDAT-01",
        "Demo Data Handling",
        7,
        "Personal data (PII) and other sensitive data are classified and recorded in a data inventory.",
        "Is personal data classified and inventoried?",
        {
            _NIST: "RA-2",
            _ISO: "5.12",
            _SOC: "C1.1",
            "GDPR": "Art 30",
            "CCPA": "1798.100",
        },
    ),
    _control(
        "DDAT-02",
        "Demo Data Handling",
        5,
        "Data is kept only as long as the retention schedule allows and is then securely disposed of.",
        "Is data retained and disposed of according to a schedule?",
        {
            _NIST: "MP-6",
            _ISO: "8.10",
            _SOC: "C1.2",
            "GDPR": "Art 5",
            "CCPA": "1798.105",
        },
    ),
]


# --- Local embedder ------------------------------------------------------------------

_DIM = 512
_STOPWORDS = frozenset(
    "a an and are as at be by for from has have in is it its of on or should the "
    "their this to used using via was were when which with all any must be that".split()
)


def _tokens(text: str) -> list[str]:
    """Lowercase words, stopwords dropped, cut to 5 letters as a crude stemmer."""
    return [
        w[:5]
        for w in re.findall(r"[a-z0-9]+", text.lower())
        if len(w) > 2 and w not in _STOPWORDS
    ]


class DemoEmbeddingModel:
    """
    A deterministic hashed bag-of-words encoder with the `encode` signature
    mapper uses. Similar wording scores high; it understands nothing else.
    """

    def encode(self, texts, **kwargs) -> np.ndarray:
        rows = np.zeros((len(texts), _DIM))
        for i, text in enumerate(texts):
            for token in _tokens(text):
                rows[i, zlib.crc32(token.encode("utf-8")) % _DIM] += 1.0
        rows = np.log1p(rows)
        norms = np.linalg.norm(rows, axis=1, keepdims=True)
        return rows / np.where(norms == 0, 1.0, norms)


# --- Canned model ----------------------------------------------------------------------

_CONFIDENCES = (82, 64, 47, 38, 31, 27)
_CANDIDATE_LINE = re.compile(r"^\[([^\]\s]+)\]\s*([^:]*):", re.MULTILINE)
_TOP_K = re.compile(r"top (\d+) most relevant")
_SCOPE_PICKS = 6


def _candidates(system_text: str) -> list[tuple[str, str]]:
    """(ID, domain) of each candidate line in the prompt, in retrieval order."""
    _, _, section = system_text.partition("Candidate SCF controls:")
    return _CANDIDATE_LINE.findall(section)


class CannedChatModel:
    """
    Stands in for ChatOpenAI. `with_structured_output(schema)` returns a runnable
    that reads the candidate list out of the rendered prompt and fills the
    schema deterministically. It never makes a network call.
    """

    def with_structured_output(self, schema):
        fields = set(schema.model_fields)

        def respond(prompt_value):
            messages = prompt_value.to_messages()
            system = str(messages[0].content) if messages else ""
            user = str(messages[-1].content) if messages else ""
            candidates = _candidates(system)
            if "mappings" in fields:
                return schema(**_mapping_payload(candidates, user))
            if "recommended_control_ids" in fields:
                return schema(**_scope_payload(candidates))
            raise TypeError(f"CannedChatModel has no demo answer for {schema!r}")

        return RunnableLambda(respond)


def _mapping_payload(candidates: list[tuple[str, str]], user: str) -> dict:
    match = _TOP_K.search(user)
    top_k = int(match.group(1)) if match else 3
    picks = candidates[: min(top_k, len(_CONFIDENCES))]
    _demo_relationships = ("subset", "intersects", "equal", "superset")
    mappings = [
        {
            "control_id": cid,
            "confidence": _CONFIDENCES[rank],
            "relationship": _demo_relationships[rank % len(_demo_relationships)],
            "source_quote": "DEMO: Requirement clause from input",
            "control_quote": f"DEMO: Control clause from {cid}",
            "justification": (
                f"DEMO OUTPUT (canned model, no LLM): rank {rank + 1} of "
                f"{len(candidates)} candidates by local demo retrieval similarity."
            ),
        }
        for rank, (cid, _) in enumerate(picks)
    ]
    mappings.append(
        {
            "control_id": DEMO_REJECTED_ID,
            "confidence": 90,
            "relationship": "intersects",
            "source_quote": "DEMO: Requirement clause from input",
            "control_quote": "DEMO: Rejected candidate control clause",
            "justification": (
                "DEMO OUTPUT: a NIST SP 800-53 ID returned on purpose, so validation "
                "can be seen rejecting an ID that was not among the candidates."
            ),
        }
    )
    return {"mappings": mappings}


def _scope_payload(candidates: list[tuple[str, str]]) -> dict:
    picks = candidates[:_SCOPE_PICKS]
    domains = list(dict.fromkeys(domain.strip() for _, domain in picks))
    return {
        "recommended_domains": domains,
        "recommended_control_ids": [cid for cid, _ in picks] + [DEMO_REJECTED_ID],
        "reasoning": (
            f"DEMO OUTPUT (canned model, no LLM): these are the {len(picks)} "
            "candidate controls that the local demo retrieval ranked highest for "
            "this scope, and their domains. The canned model also returned "
            f"{DEMO_REJECTED_ID}, a NIST SP 800-53 ID, on purpose, to show "
            "validation rejecting it. No judgment about the scope was made."
        ),
    }
