# Case Study: Automating IT compliance with AI

**Role:** IT Audit Specialist / GRC Engineer  
**Core Technologies:** Python, Streamlit, LangChain, Groq LLM (Llama-3), Pytest, CI/CD  
**Frameworks Covered:** Secure Controls Framework (SCF), SOC 2, ISO 27001, PCI-DSS  

---

## 🛑 The Problem

Governance, Risk, and Compliance (GRC) teams face a massive operational bottleneck during audits: **The Mapping Problem**. 

Whether dealing with a raw IT policy written by a developer, or a massive JSON dump of hundreds of AWS Security Hub findings, auditors must manually read each finding, cross-reference it against a spreadsheet of thousands of baseline controls (like the 1,400+ controls in the Secure Controls Framework), and determine applicability.

**The traditional manual process:**
1. Read the finding context.
2. CTRL+F through a massive SCF Excel spreadsheet.
3. Guess the closest matching control domain.
4. Manually copy/paste the data into a compliance tracker (like Drata or Vanta) to map to corresponding regulations (e.g. "Does this map to SOC 2 CC1.1 or ISO 27001 A.5.1?").

This manual mapping leads to human error, cognitive fatigue, and massive delays in audit preparation.

---

## 🏗️ The Solution: "Audit Engineering" & Automation

I built **SCF Auto-Crosswalker** to fundamentally solve this bottleneck using Large Language Models (LLMs) and structured data extraction. 

Instead of manual spreadsheet gymnastics, the tool acts as an autonomous GRC assistant. It ingests unstructured text, policies, or complex Cloud Security JSONs and strategically routes them to the correct SCF controls, exporting the results directly into an audit-ready format.

### Architectural Decisions:
1. **Model Selection (Llama-3 via Groq):** 
   - *Decision:* Used Groq's LPU acceleration with Llama-3-70b. 
   - *Why:* Speed is paramount. Mapping hundreds of AWS findings needs to happen fast. Groq provides near-instantaneous token generation.
2. **Framework Alignment (SCF):** 
   - *Decision:* Anchored the AI logic to the Secure Controls Framework (SCF). 
   - *Why:* The SCF is the gold standard for harmonizing fragmented IT regulations. If the AI maps a finding to the SCF, it automatically inherits the mappings to SOC 2, CMMC, GDPR, and ISO.
3. **Structured Outputs (Pydantic / LangChain):**
   - *Decision:* Forced the LLM to output rigid Pydantic JSON schemas.
   - *Why:* LLMs hallucinate text. Pydantic ensures the outputs can be programmatically converted into clean Pandas DataFrames for reliable CSV exports.
4. **Compliance-as-Code Quality:**
   - *Decision:* Implemented `pytest` suites and GitHub Actions CI/CD pipelines.
   - *Why:* A GRC tool needs to prove it can pass an audit itself. Strict linting and testing validate the "Audit Engineering" mindset.

---

## 📈 The Impact

While standard GRC functions rely heavily on manual tracking, shifting to an AI-driven mapping model provides significant operational ROI. 

According to industry benchmarks from reports by Thomson Reuters and ZenGRC, organizations adopting AI-powered GRC automation experience:
- **Up to a 50-70% reduction** in audit preparation and evidence-gathering time.
- **Accelerated Control Mapping**, turning cross-framework mapping exercises that traditionally took months down to mere days.

By utilizing **SCF Auto-Crosswalker**, an audit team could process a 500-item AWS Security Hub export in minutes—with a consistent AI-justified audit trail—freeing engineers to focus on actual risk remediation rather than administrative spreadsheet mapping.

---

## 🔎 View the Proof of Work

You don't need to run the code to see how it works. Check the `lab_data/` directory in this repository:

1. **Input:** `lab_data/aws_securityhub_finding.json` (A raw, complex JSON format cloud finding)
2. **Input:** `lab_data/sample_endpoint_policy.txt` (A standard ITGC text snippet)
3. **OUTPUT:** `lab_data/sample_outputs/` (The resulting structured CSV and JSON mappings generated autonomously by the engine).
