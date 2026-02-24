# 🛡️ SCF Auto-Crosswalker

An open-source, AI-powered internal GRC tool designed to eliminate manual spreadsheet mapping for IT Auditors and GRC Engineers. 

Simply paste a raw IT policy, a procedure, or upload a Cloud Security finding (like AWS Security Hub JSON), and the engine will autonomously map it to the **Secure Controls Framework (SCF)** and append all related compliance regulations (GDPR, SOC 2, ISO 27001, NIST, PCI).

![Streamlit UI Demo](/home/tvobrachini/.gemini/antigravity/brain/8ea03ba3-cec0-49ed-a000-98417ec5d0ae/scf_mapping_complete_1771936245594.png)

## 📌 Features
- **Always Current Framework:** Connects directly to the SCF GitHub repository to automatically download and parse the ~1,400+ controls upon setup.
- **AI Mapping Engine (Free & Fast):** Utilizes `LangChain` and structurally enforces JSON outputs from Llama-3 to find the absolute best matching domains and controls with a confidence score.
- **Regulatory Extractor:** Automatically pulls over 30 related framework mappings for every single control (e.g., NIST CSF, SOC 2, HIPAA).
- **Interactive UI:** Built using `Streamlit` to provide a clean, modern dashboard for testers or auditors to upload their evidence.
- **Safe Lab Environment:** Includes a ready-to-test `lab_data/` directory with sample files so you can test the AI engine without risking real company data.

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
