# Case Study: Control mapping an auditor can check

**Role:** Personal project, not affiliated with any employer
**Stack:** Python, Streamlit, sentence-transformers, LangChain with Groq (Llama 3.1 8B by default), Pydantic, pytest, GitHub Actions
**Framework:** Secure Controls Framework (SCF). Its published crosswalk links each control onward to SOC 2, ISO 27001, NIST CSF, NIST SP 800-53, PCI DSS, GDPR, HIPAA and CCPA.

---

## The problem

Before an auditor can test a control, they have to decide which control a piece of evidence concerns. A new policy, an AWS Security Hub finding or an audit scope has to be placed against a control framework. With the SCF that means searching 1,591 controls (release 2026.3) in a spreadsheet for each input. The work is slow, it is repeated for every new document, and two people often place the same finding differently.

Language models can shorten that first pass, but they introduce a new risk for audit work: an answer that looks right but refers to a control that does not exist, or that paraphrases a control's text into something the framework never said. In an audit file, both are errors of fact.

## The approach

The tool narrows the SCF to a shortlist, lets a model choose from that shortlist, and then checks the choice against the framework itself:

1. **Retrieve.** Embed the input and rank every SCF control by similarity. The model sees only the top 50 (60 for scope documents).
2. **Choose.** One model call returns control IDs, a confidence score and a one-sentence justification. Nothing else.
3. **Check.** Any ID that was not in the shortlist is dropped and shown to the user as rejected. The control's domain, text and framework references are then copied from the SCF database, so every word of control text on screen is SCF's own.
4. **Record.** Results export to CSV and to an OSCAL mapping-collection with status `draft`, so they can enter a GRC toolchain as unreviewed suggestions.

A third tool, the Gap Analyzer, uses no model at all. It takes an existing control list, either numbered with SCF IDs or with a column mapping each control to them, and reports, per framework requirement, whether any SCF control mapped to it is on the list, optionally counting only controls with an in-place status.

## Decisions that came from the audit side

- **The model is not a source of truth.** It proposes IDs; the framework supplies the content. This came from an early sample run in which the Scope Analyzer returned only NIST SP 800-53 IDs (`AC-1`, `SC-8`, …) for an SCF test plan, and the Crosswalker displayed control descriptions the model had rewritten. Both now fail validation visibly instead of reaching the page.
- **Claims are scoped to what the tool can know.** A control in the gap report is *listed*, not *covered*: the tool sees an ID in a spreadsheet, not a control operating. Confidence is labeled as the model's own, uncalibrated number. The OSCAL export records every map as `intersects-with`, the weakest positive relationship in NIST IR 8477, because the tool does not establish subset, superset or equality.
- **Gaps are counted the way an assessor counts them.** The first version counted SCF controls: 405 of the 407 mapped to SOC 2 were "not listed" for the sample list. An assessor works from the 61 criteria SCF cites, so the report now leads with those (8 have a listed control for the mapped sample) and treats a criterion with a listed control as a place to start testing, not as met.
- **Framework data is handled under its license.** The SCF is licensed CC BY-ND 4.0, which does not allow redistributing modified copies, so the repository does not host SCF data. The app downloads the official release and derives its working copy locally.
- **Data leaving the machine is disclosed.** Submitted text goes to Groq's API; the UI says so next to the submit button, and Security Hub findings are reduced to their descriptive fields before anything is sent.

## Measuring it

A mapping tool needs a number, and hand-labeled gold sets are expensive. `scripts/run_eval.py` builds one from two published mappings instead: AWS's mapping of each Security Hub control to NIST SP 800-53, and SCF's mapping of its controls to NIST SP 800-53. It reports retrieval hit rate, recall and MRR at k, which needs no API key, and optionally the precision of the model's suggestions. The labels are transitive, so the result measures consistency with AWS's and SCF's published mappings rather than ground truth.

The first run scored retrieval only, on SCF 2026.3 and the 221 Security Hub controls in the AWS user guide (as of March 2023) that cite NIST SP 800-53. Two things came out of it before any number did. First, the join was silently broken: SCF writes `AC-02(01)` where AWS writes `AC-2(1)`, so about half the cases and 82% of the gold links were missing until both sides were normalized. Second, a hit rate alone means little when a case can have 28 gold controls, so the report puts it next to the exact expectation for random ranking and a TF-IDF baseline.

The result is modest. At k = 50, the shortlist the model sees, 62% of cases include a control the published mappings link to the Security Hub control (TF-IDF 46%, random 23%), and the top-ranked control is linked in 11% of cases. For the other 38%, the model cannot agree with the published mappings whatever it does, which makes retrieval, not the model, the first thing to improve. The embedding model ran from an ONNX export verified by hash, because Hugging Face was out of reach, and the model step is still unscored. [`eval/README.md`](eval/README.md) has the full tables, provenance and caveats.

## Limitations

- Only retrieval has been evaluated. The model step has not been run against a Groq model, so there is no precision figure. The retrieval numbers rest on transitive labels, a March 2023 snapshot of the AWS docs and an ONNX export of the embedding model, not the PyTorch model the app loads.
- Validation guarantees that a suggested control exists and was among the candidates, not that it fits the input. That judgment stays with the reviewer.
- Retrieval bounds the answer: a control the embedding search misses cannot be suggested.
- The sample outputs in `lab_data/` come from an earlier version and show the failure modes described above; `lab_data/README.md` annotates them.

More detail is in [DECISIONS.md](DECISIONS.md) (architecture decision records) and the [README](README.md).
