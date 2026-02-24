# 🛡️ SCF Auto-Crosswalker

An open-source, AI-powered internal GRC tool designed to eliminate manual spreadsheet mapping for IT Auditors and GRC Engineers. 

Simply paste a raw IT policy, a procedure, or upload a Cloud Security finding (like AWS Security Hub JSON), and the engine will autonomously map it to the **Secure Controls Framework (SCF)** and append all related compliance regulations (GDPR, SOC 2, ISO 27001, NIST, PCI).

![Streamlit UI Demo](/home/tvobrachini/.gemini/antigravity/brain/8ea03ba3-cec0-49ed-a000-98417ec5d0ae/scf_mapping_complete_1771936245594.png)

## 📌 The GRC Assistant Suite
This project features three distinct tools accessible via a clean sidebar navigation:

### 1. 🔍 SCF Auto-Crosswalker
Paste a raw IT policy, a procedure, or upload a massive Cloud Security JSON (e.g. AWS Security Hub findings), and the LLM engine will autonomously map it to the absolute best matching SCF domains and controls with a confidence score.
- **📄 PDF Processing:** Upload massive PDF documents and have the AI parse and map the entire document.
- **📥 CSV Exports:** Instantly export the AI mappings into an Excel-ready CSV for your compliance trackers (Drata, Vanta).
- **⚙️ Custom Personas:** Force the AI to act specifically as a PCI-DSS QSA, FedRAMP Assessor, or GDPR DPO to tune the mappings.

### 2. 🎯 Audit Scope Analyzer
Upload a narrative Audit Scope Document (TXT/PDF) and the AI will strategically deduce which SCF Domains and specific baseline controls must be tested. Includes the AI's step-by-step reasoning.

### 3. 📉 Compliance Gap Analyzer
Upload a CSV listing your company's existing IT controls, select a target framework (e.g., SOC 2, HIPAA, GDPR), and instantly generate a checklist identifying exactly which baseline SCF controls are required to meet that framework.

## 🚀 Quickstart

1. Clone the repository and navigate to the project directory.
2. Set up your Python environment using `uv` (recommended) or `venv` to prevent dependency conflicts:
   ```bash
   # Using uv (extremely fast)
   uv venv
   source .venv/bin/activate
   uv pip install -r requirements.txt
   ```
3. Get a FREE API Key from [Groq Console](https://console.groq.com/keys) to run Llama-3.
4. Duplicate the example environment file and add your key. **Your `.env` file is ignored by Git and will never be uploaded to GitHub.**
   ```bash
   cp .env.example .env
   # Open .env and replace "your_api_key_here" with your actual Groq key
   ```
5. Launch the Streamlit interactive dashboard:
   ```bash
   uv run streamlit run app.py
   ```
6. *Upon first launch, click **"Force Update SCF Framework Data"** in the sidebar to securely download the latest framework into your local `data/` directory.*

## ⚖️ Licensing & Attribution
The AI mapping engine was engineered to be open-source and model-agnostic. 

*The control framework data utilized by this tool is owned, maintained, and copyrighted by the [Secure Controls Framework](https://securecontrolsframework.com).* The SCF is an indispensable free resource for the cybersecurity community and is licensed under the Creative Commons Attribution-NoDerivatives 4.0 International Public License. 

This project does not modify the underlying framework controls.
