# Case Study: Automating IT compliance with AI

**Role:** Personal project, not affiliated with any employer
**Core Technologies:** Python, Streamlit, LangChain, Groq LLM (Llama 3.1 8B by default), sentence-transformers, Pydantic, Pytest, GitHub Actions
**Framework:** Secure Controls Framework (SCF); its published crosswalk links onward to SOC 2, ISO 27001 and PCI DSS

---

## 🛑 The Problem

Governance, Risk, and Compliance (GRC) teams face a large operational bottleneck during audits: **The Mapping Problem**.

Whether dealing with a raw IT policy written by a developer, or a JSON export of many AWS Security Hub findings, auditors must manually read each finding, cross-reference it against a spreadsheet of baseline controls (the Secure Controls Framework has more than 1,400), and determine applicability.

**The traditional manual process:**
1. Read the finding context.
2. CTRL+F through a large SCF Excel spreadsheet.
3. Guess the closest matching control domain.
4. Manually copy/paste the data into a compliance tracker (like Drata or Vanta) to map to corresponding regulations (e.g. "Does this map to SOC 2 CC1.1 or ISO 27001 A.5.1?").

This manual mapping is slow and error-prone, and it is repeated for every new policy or finding.

---

## 🏗️ The Solution: Automation

I built **SCF Auto-Crosswalker** to shorten the first pass: it narrows the SCF down to a few candidate controls that a reviewer then accepts or rejects.

It takes policy text, a document, a scope narrative or Security Hub findings, retrieves the most similar SCF controls with embeddings, asks an LLM to pick from them, and checks the answer against the SCF database before showing it. Results export to CSV. A third tool, the Gap Analyzer, uses no LLM at all: it lists the SCF controls that SCF maps to a framework and checks which appear in an existing control list.

### Architectural Decisions:
1. **Model Selection (Llama 3.1 8B via Groq):**
   - *Decision:* Uses Groq with `llama-3.1-8b-instant` by default (configurable through `GROQ_MODEL`).
   - *Why:* Groq was chosen for low latency when mapping many findings. An 8B model is less accurate than larger ones, so every suggestion needs human review.
2. **Framework Alignment (SCF):**
   - *Decision:* Anchored the AI logic to the Secure Controls Framework (SCF).
   - *Why:* The SCF is widely used for harmonizing fragmented IT regulations. If the AI maps a finding to the SCF, it picks up the mappings SCF itself publishes. The parser keeps SCF's columns for SOC 2, ISO 27001, NIST CSF, NIST 800-53, GDPR, CCPA, HIPAA and PCI DSS.
3. **The model picks IDs; the database supplies the rest:**
   - *Decision:* The LLM returns only control IDs, a confidence score and a justification, through a Pydantic schema. Every ID is checked against the SCF database, IDs that are not there are dropped and shown to the user, and the control's domain, description and crosswalk references are copied from the database.
   - *Why:* A schema guarantees the shape of the answer, not its truth. An early sample run of the Scope Analyzer returned only NIST 800-53 IDs (AC-1, SC-8, …) instead of SCF IDs, and the Crosswalker was displaying control descriptions the model had rewritten. Both now go through the same validation, so every control shown is a real SCF control with SCF's own text.
4. **Retrieval before the LLM call:**
   - *Decision:* Embed every SCF control once, and send the model only the 50 most similar to the input. Long inputs are embedded in chunks, and Security Hub findings are reduced to their title, description and remediation first.
   - *Why:* It keeps the prompt within free-tier limits. The trade-off is that the model cannot choose a control that retrieval missed.
5. **A tested compliance tool:**
   - *Decision:* An offline test suite (fake LLM, fake embedding model, headless Streamlit tests) and a CI pipeline with type checking, SAST, dependency auditing and a container build.
   - *Why:* A tool that supports audit work should be held to the same standard of evidence it helps produce. More detail is in [DECISIONS.md](DECISIONS.md).

---

## ⚠️ Limitations and accuracy

This project has not been benchmarked. There are no measured figures for mapping precision, time per run or cost per run, and none are claimed here. Validation guarantees that a suggested control exists in the SCF, not that it fits; that judgment stays with the reviewer. The confidence score is the model's own and is not calibrated. The examples in `lab_data/` are raw outputs from an earlier version, and [`lab_data/README.md`](lab_data/README.md) explains the weak matches and invalid IDs they contain.

---

## 🔎 View the Proof of Work

You don't need to run the code to see how it works. Check the `lab_data/` directory in this repository:

1. **Input:** `lab_data/aws_securityhub_finding.json` (A raw, complex JSON format cloud finding)
2. **Input:** `lab_data/sample_endpoint_policy.txt` (A standard ITGC text snippet)
3. **Output:** `lab_data/sample_outputs/` (raw CSV and JSON output from an earlier version of the tool, annotated in `lab_data/README.md`).
