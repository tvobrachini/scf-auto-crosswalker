# Architecture Decision Records: SCF Auto-Crosswalker

This file records the design decisions as the code implements them today. Each record says what the code does, and what that does and does not give you. Where the repository history or a code comment explains a choice, the record cites it. Where it does not, the record does not guess at motive.

---

## ADR-001: Anchor every mapping to the Secure Controls Framework

**Status:** Accepted

**Decision.** All three tools output SCF control IDs. Links to other frameworks (SOC 2, ISO 27001, NIST CSF, NIST 800-53, GDPR, CCPA, HIPAA, PCI DSS) are read from the crosswalk columns SCF publishes in its workbook (`parse_scf` in `src/fetch_scf.py`). The tool never produces them itself.

**Consequences.**
- One mapping target instead of eight. A finding mapped to an SCF control inherits SCF's published references.
- Those references are only as good as SCF's crosswalk. The UI labels them "from SCF's crosswalk".
- `parse_scf` keeps only the columns whose names contain one of the eight framework keywords, so any other framework in the workbook is dropped.

---

## ADR-002: Do not host SCF data; download and derive it at runtime

**Status:** Accepted

**Decision.** `download_scf` fetches the `.xlsx` asset from the latest release of the official `securecontrolsframework/securecontrolsframework` GitHub repository. `parse_scf` derives `data/scf_parsed.json` from it. `data/` is git-ignored and is a named volume under Docker. The history of this decision is in commit `1bd4a5f` ("stop hosting SCF data").

**Consequences.**
- The repository does not redistribute a modified copy of the SCF, which CC BY-ND 4.0 does not allow.
- The first run needs network access to GitHub.
- The download is trusted on the basis of its source and HTTPS only; SCF publishes no checksum to verify against.
- The download goes to `scf_raw.xlsx.part` and is renamed into place only when it is complete, so an interrupted download never leaves a truncated workbook that later runs would accept. **Download / Update SCF Data** passes `force=True`, so it always fetches the current release.
- A parse that keeps no valid records returns an error and leaves the previous database in place.

---

## ADR-003: Retrieve candidates with embeddings, then make one LLM call

**Status:** Accepted

**Decision.** `_semantic_filter` (`src/mapper.py`) embeds the input with `all-MiniLM-L6-v2` and ranks every SCF control by cosine similarity. The Crosswalker sends the top 50 candidates to the LLM and the Scope Analyzer the top 60. The Scope Analyzer also sends the full list of SCF domains with their ID prefixes, so its domain suggestions can cover the whole framework. The retrieval step replaced keyword matching in commit `5ed1f81`.

**Consequences.**
- The prompt stays small enough for Groq's free-tier limits instead of carrying roughly 1,400 controls.
- The model can only pick a control that retrieval found. A retrieval miss is an answer miss, and the UI cannot show it.
- The embedding model truncates at 256 word pieces. The input is therefore embedded in 150-word chunks, and each control keeps its best chunk score (`_chunk_words`). Security Hub findings are first reduced to their descriptive fields (`src/findings.py`), because roughly the first 700 characters of a raw finding are ARNs, IDs and timestamps.
- Control embeddings are cached in `data/scf_embeddings.npz` together with a SHA-256 fingerprint of the embedding model name and every control text. A cache whose fingerprint or row count does not match the current database is rebuilt, so row *i* always belongs to control *i*.

---

## ADR-004: The model picks IDs; the database supplies everything else

**Status:** Accepted

**Decision.** The LLM-facing schemas (`_LLMMappedControl`, `ScopeRecommendation`) ask only for control IDs, a confidence score, a justification (and, for scope, domains and reasoning). After the call:

- `_validate_mapping_result` and `_validate_scope_recommendation` normalize each ID (trim, strip brackets, uppercase), drop IDs that are not in the SCF database, and drop duplicates. The dropped IDs are returned in `rejected_control_ids` and shown in the UI.
- Confidence is clamped to 0–100.
- `domain`, `description` and `regulations` are copied from the database record.

**Consequences.**
- Every control shown to the user exists in the downloaded SCF release, and its text is SCF's own text.
- This check was added to the Scope Analyzer after its sample output (`lab_data/sample_outputs/audit_scope_analysis_result.json`) turned out to contain only NIST SP 800-53 IDs. Before that, only the Crosswalker validated IDs, and both tools displayed control descriptions written by the model.
- Validation shows that an ID exists. It does not show that the control fits the input.
- The confidence score is the model's own number and is not calibrated. The UI and CSV label it "model confidence".

---

## ADR-005: Groq with Llama 3.1 8B by default

**Status:** Accepted

**Decision.** `_get_llm` builds `ChatGroq(temperature=0)` with the model from `GROQ_MODEL`, defaulting to `llama-3.1-8b-instant`. Structured output goes through LangChain's `with_structured_output`.

**Consequences.**
- It is free to try and has low latency, which matters in batch mode, where each finding is a separate call.
- An 8B model makes weaker choices than larger models; the committed samples include weak matches. Any Groq model can be set through `GROQ_MODEL`.
- Temperature 0 lowers variance but does not make the output deterministic.
- `_invoke_chain` retries only rate limits, timeouts, connection errors and 5xx responses (3 attempts, exponential backoff). Authentication and bad-request errors fail at once instead of retrying for each finding in a batch.
- The submitted text is sent to Groq. The UI and SECURITY.md say so.

---

## ADR-006: The Gap Analyzer is deterministic and compares IDs only

**Status:** Accepted

**Decision.** `analyze_gaps` (`src/gap_analysis.py`) lists every SCF control with an entry in the chosen crosswalk column and marks it *Listed* when its SCF ID appears in the uploaded CSV. The user picks one crosswalk column, for example one ISO 27001 edition, rather than all columns whose names match. IDs in the CSV that are not SCF IDs are reported.

**Consequences.**
- There is no LLM in the loop, so the same input always gives the same result.
- The uploaded list must use SCF IDs. A list with its own numbering matches nothing, which is why unknown IDs are surfaced rather than silently counted as gaps.
- *Listed* means only that the ID is present. The tool does not compare control names or check design or operating effectiveness, and the UI says this next to the metrics.

---

## ADR-007: Offline tests with fakes at the model boundaries

**Status:** Accepted

**Decision.** The tests replace `_get_llm` with a fake chat model built from a LangChain `RunnableLambda`, and `_get_embedding_model` with a bag-of-words encoder (`tests/conftest.py`, `tests/test_pipeline.py`). The UI is exercised with Streamlit's `AppTest` against a fixture database (`tests/test_app.py`). CI requires 80% line coverage of `src/`.

**Consequences.**
- CI needs no API keys and no network access to Groq, Hugging Face or GitHub, and runs in seconds.
- The tests cover the code around the model: prompts, validation, enrichment, caching, retries and parsing. They say nothing about how good the model's choices are. No evaluation set exists yet (see the README's limitations section).
