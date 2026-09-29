# Case Study: Control mapping an auditor can check

**Role:** Personal project, not affiliated with any employer
**Stack:** Python, Streamlit, sentence-transformers, LangChain with OpenRouter (Llama 3.1 8B by default), Pydantic, pytest, GitHub Actions
**Framework:** Secure Controls Framework (SCF). Its published crosswalk links each control onward to SOC 2, ISO 27001, NIST CSF, NIST SP 800-53, PCI DSS, GDPR, HIPAA and CCPA.

---

## The problem

Before an auditor can test a control, they have to decide which control a piece of evidence concerns. A new policy, an AWS Security Hub finding or an audit scope has to be placed against a control framework. With the SCF that means searching 1,591 controls (release 2026.3) in a spreadsheet for each input. The work is slow, it is repeated for every new document, and two people often place the same finding differently.

Language models can shorten that first pass, but they introduce a new risk for audit work: an answer that looks right but refers to a control that does not exist, or that paraphrases a control's text into something the framework never said. In an audit file, both are errors of fact.

## The approach

The tool narrows the SCF to a shortlist, lets a model choose from that shortlist, and then checks the choice against the framework itself:

1. **Retrieve.** Embed the input and rank every SCF control by similarity. The model sees only the top 50 (60 for scope documents).
2. **Choose.** One model call returns control IDs, a confidence score and a one-sentence justification. Nothing else.
3. **Check.** Any ID that was not in the shortlist is dropped and shown to the user as rejected. The control's domain, text and framework references are then copied from the SCF database, so every word of control text on screen is SCF's own. What remains for the reviewer is a judgment of fit, never a check of facts.
4. **Record.** Results export to CSV and to an OSCAL mapping-collection with status `draft`, so they can enter a GRC toolchain as unreviewed suggestions.

A third tool, the Gap Analyzer, uses no model at all. It takes an existing control list, either numbered with SCF IDs or with a column mapping each control to them, and reports, per framework requirement, whether any SCF control mapped to it is on the list, optionally counting only controls with an in-place status.

## Decisions that came from the audit side

- **The model is not a source of truth.** It proposes IDs; the framework supplies the content. This came from an early sample run in which the Scope Analyzer returned only NIST SP 800-53 IDs (`AC-1`, `SC-8`, …) for an SCF test plan, and the Crosswalker displayed control descriptions the model had rewritten. Both now fail validation visibly instead of reaching the page.
- **Claims are scoped to what the tool can know.** A control in the gap report is *listed*, not *covered*: the tool sees an ID in a spreadsheet, not a control operating. Confidence is labeled as the model's own, uncalibrated number. The OSCAL export records every map as `intersects-with`, the weakest positive relationship in NIST IR 8477, because the tool does not establish subset, superset or equality.
- **Gaps are counted the way an assessor counts them.** The first version counted SCF controls: 405 of the 407 mapped to SOC 2 were "not listed" for the sample list. An assessor works from the 61 criteria SCF cites, so the report now leads with those (8 have a listed control for the mapped sample) and treats a criterion with a listed control as a place to start testing, not as met.
- **Framework data is handled under its license.** The SCF is licensed CC BY-ND 4.0, which does not allow redistributing modified copies, so the repository does not host SCF data. The app downloads the official release and derives its working copy locally.
- **Data leaving the machine is disclosed.** Submitted text goes to OpenRouter's API; the UI says so next to the submit button, and Security Hub findings are reduced to their descriptive fields before anything is sent.

## Measuring it

A mapping tool needs a number, and hand-labeled gold sets are expensive. `scripts/run_eval.py` builds one from two published mappings instead: AWS's mapping of each Security Hub control to NIST SP 800-53, and SCF's mapping of its controls to NIST SP 800-53. That gives 221 cases and 1,866 labeled links from SCF 2026.3 and the AWS Security Hub user guide (March 2023 edition), with no hand labeling. Because the labels are transitive, a score measures agreement with what AWS and SCF have published, which is the reference an auditor would cite anyway.

**The evaluation caught a bug before it produced a number.** SCF writes `AC-02(01)` where AWS writes `AC-2(1)`. The join silently dropped about half the cases and 82% of the gold links until both sides were normalized. Any score computed before that fix would have looked plausible and been wrong, which is the same failure this tool is built to prevent in audit files.

**Retrieval narrows 1,591 controls to 50, and 62% of the time the shortlist holds a control the published mappings link to the input.** That is 2.7 times what random ranking achieves (22.8%, computed exactly for each case's gold-set size) and 16 points above a TF-IDF baseline over the same texts (46.2%; paired McNemar p ≈ 4e-5). The embedding search finds 53 cases that word overlap misses. Word overlap finds 18 that the embedding search misses.

**The small model is the right size.** Retrieval is the stage to improve, so the obvious upgrades were tested: bge-small and bge-base (up to five times the parameters), and hybrid rankers that fuse embeddings with TF-IDF or with each other. None is a significant improvement once the number of variants tried is taken into account, and none beats the app's model at k = 10. The 22M-parameter MiniLM stays: it runs on a laptop CPU, and the remaining misses trace to short, generic inputs and to the 815 SCF controls with no 800-53 entry, not to model capacity.

Every input is pinned: the SCF workbook, the AWS docs commit and each embedding model are checked by sha256, and a rerun from scratch reproduces the published tables exactly. [`eval/README.md`](eval/README.md) has the full tables, the paired tests and the provenance. The next number is the model step's precision: `run_eval.py --llm` scores it with one OpenRouter call per case.

More detail is in [DECISIONS.md](DECISIONS.md) (architecture decision records) and the [README](README.md).
