# Architecture Decision Records: SCF Auto-Crosswalker

This file records the design decisions as the code implements them today. Each record says what the code does, and what that does and does not give you. Where the repository history or a code comment explains a choice, the record cites it. Where it does not, the record does not guess at motive.

---

## ADR-001: Anchor every mapping to the Secure Controls Framework

**Status:** Accepted

**Decision.** All three tools output SCF control IDs. Links to other frameworks (SOC 2, ISO 27001, NIST CSF, NIST 800-53, GDPR, CCPA, HIPAA, PCI DSS) are read from the crosswalk columns SCF publishes in its workbook (`parse_scf` in `src/fetch_scf.py`). The tool never produces them itself.

**Consequences.**
- One mapping target instead of eight. A finding mapped to an SCF control inherits SCF's published references.
- Those references are only as good as SCF's crosswalk. The UI labels them "from SCF's crosswalk".
- `parse_scf` keeps only the columns whose names contain one of the eight framework keywords (compared with spaces and line breaks removed, so "NIST SP 800-53 R5" and "NIST\n800-53\nrev5" both match), so any other framework in the workbook is dropped.

---

## ADR-002: Do not host SCF data; download and derive it at runtime

**Status:** Accepted

**Decision.** `download_scf` fetches the `.xlsx` asset from the latest release of the official `securecontrolsframework/securecontrolsframework` GitHub repository. `parse_scf` derives `data/scf_parsed.json` from it. `data/` is git-ignored and is a named volume under Docker. The history of this decision is in commit `1bd4a5f` ("stop hosting SCF data").

**Consequences.**
- The repository does not redistribute a modified copy of the SCF, which CC BY-ND 4.0 does not allow.
- The first run needs network access to GitHub.
- The download is trusted on the basis of its source and HTTPS only; SCF publishes no checksum to verify against.
- The download goes to `scf_raw.xlsx.part` and is renamed into place only when it is complete, so an interrupted download never leaves a truncated workbook that later runs would accept. **Download / Update SCF Data** passes `force=True`, so it always fetches the current release.
- `scf_parsed.json` is also written to a temp file and renamed, so a crash mid-write never leaves truncated JSON. A parse that keeps no valid records returns an error and leaves the previous database in place.
- The sheet name of the parsed release (e.g. "SCF 2025.4") is recorded in `data/scf_meta.json`, shown in the sidebar, and written into OSCAL exports.
- `load_scf_database` caches the parsed file keyed on its modification time and never caches a missing or unreadable file, so a database rebuilt from the sidebar or from `python src/fetch_scf.py` is picked up without a restart.

---

## ADR-003: Retrieve candidates with embeddings, then make one LLM call

**Status:** Accepted

**Decision.** `_semantic_filter` (`src/mapper.py`) embeds the input with `all-MiniLM-L6-v2` and ranks every SCF control by cosine similarity. The Crosswalker sends the top 50 candidates to the LLM and the Scope Analyzer the top 60. The Scope Analyzer also sends the full list of SCF domains with their ID prefixes, so its domain suggestions can cover the whole framework. The retrieval step replaced keyword matching in commit `5ed1f81`.

**Consequences.**
- The prompt stays small enough for Groq's free-tier limits instead of carrying roughly 1,400 controls.
- The model can only pick a control that retrieval found: validation (ADR-004) accepts only candidate IDs. A retrieval miss is an answer miss, which is why the evaluation (ADR-009) measures retrieval on its own.
- The embedding model truncates at 256 word pieces. The input is therefore embedded in 150-word chunks, and each control keeps its best chunk score (`_chunk_words`). Security Hub findings are first reduced to their descriptive fields (`src/findings.py`), because roughly the first 700 characters of a raw finding are ARNs, IDs and timestamps.
- Control embeddings are cached in `data/scf_embeddings.npz` together with a SHA-256 fingerprint of the embedding model name and every control text. A cache whose fingerprint or row count does not match the current database is rebuilt, so row *i* always belongs to control *i*.
- The cache is written to a temp file and renamed, and any cache that cannot be read (for example, truncated by a crash or by two sessions building it at once) is rebuilt rather than failing every request. The last embeddings are also kept in memory, so a batch does not re-read the file for each finding.

---

## ADR-004: The model picks IDs; the database supplies everything else

**Status:** Accepted

**Decision.** The LLM-facing schemas (`_LLMMappedControl`, `ScopeRecommendation`) ask only for control IDs, a confidence score, a justification (and, for scope, domains and reasoning). After the call:

- `_validate_mapping_result` and `_validate_scope_recommendation` normalize each ID (trim, strip brackets, uppercase), drop IDs that were not among the retrieved candidates, drop duplicates, and keep at most top k (3 per Crosswalker input, 10 per scope). The dropped IDs are returned in `rejected_control_ids` and shown in the UI.
- Scope domain names must match an SCF domain name (case-insensitive); others are returned in `rejected_domains`.
- Confidence is clamped to 0–100; a fraction such as 0.85 is read as 85%.
- `domain`, `description` and `regulations` are copied from the database record.

**Consequences.**
- Every control shown to the user exists in the downloaded SCF release, was among the candidates the model saw, and its text is SCF's own text.
- Validating against the candidates rather than the whole SCF gives up any correct control the model knows from pretraining but retrieval missed. In exchange, the documented contract ("the model picks from the shortlist") is enforced, and retrieval quality can be measured separately.
- Model text that is displayed (justifications, reasoning) is Markdown-escaped, so a prompt-injected input cannot make the page render a link or load an external image. CSV exports neutralize cells that would start a spreadsheet formula.
- ID validation was added to the Scope Analyzer after its sample output (`lab_data/sample_outputs/audit_scope_analysis_result.json`) turned out to contain only NIST SP 800-53 IDs. Before that, only the Crosswalker validated IDs, and both tools displayed control descriptions written by the model.
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
- `_invoke_chain` retries only rate limits, timeouts, connection errors and 5xx responses (at most 3 attempts, exponential backoff). The Groq client's own retries are turned off (`max_retries=0`), so this is the only retry layer. Authentication and bad-request errors fail at once instead of retrying for each finding in a batch.
- In batch mode, identical finding texts are sent once (`src/crosswalk.py`), at most 50 distinct findings are mapped per batch, and an error on one finding is reported on that finding without stopping the batch.
- The submitted text is sent to Groq. The UI and SECURITY.md say so.

---

## ADR-006: The Gap Analyzer is deterministic and compares IDs only

**Status:** Accepted

**Decision.** `analyze_gaps` (`src/gap_analysis.py`) lists every SCF control with an entry in the chosen crosswalk column and marks it *Listed* when its SCF ID appears in the uploaded CSV. The user picks one crosswalk column, for example one ISO 27001 edition, rather than all columns whose names match. IDs in the CSV that are not SCF IDs are reported. If the CSV has a status column, the user can count only rows with an in-place status; "Not Implemented", "Partially implemented" and "Planned" are excluded by default.

**Consequences.**
- There is no LLM in the loop, so the same input always gives the same result.
- The uploaded list must use SCF IDs. A list with its own numbering matches nothing, which is why unknown IDs are surfaced rather than silently counted as gaps.
- *Listed* means only that the ID is present. The tool does not compare control names or check design or operating effectiveness, and the UI says this next to the metrics.

---

## ADR-007: Offline tests with fakes at the model boundaries

**Status:** Accepted

**Decision.** The tests replace `_get_llm` with a fake chat model built from a LangChain `RunnableLambda`, and `_get_embedding_model` with a bag-of-words encoder (`tests/conftest.py`, `tests/test_pipeline.py`). The UI is exercised with Streamlit's `AppTest` against a fixture database (`tests/test_app.py`). CI requires 85% line coverage of `src/`.

**Consequences.**
- CI needs no API keys and no network access to Groq, Hugging Face or GitHub, and runs in seconds.
- The tests cover the code around the model: prompts, validation, enrichment, caching, retries, parsing, exports and the UI's success paths. They say nothing about how good the model's choices are; that is what the evaluation (ADR-009) is for.
- Tests import modules the way the app does (`src/` on `sys.path`), so the app and the tests share one copy of each module.

---

## ADR-008: Export OSCAL mapping-collections as drafts

**Status:** Accepted

**Decision.** `oscal_mapping_collection` (`src/exports.py`) turns crosswalk results into an OSCAL 1.2 `mapping-collection`:

- **Provenance:** method `automation`, matching rationale `semantic`, status `draft`, and a mapping description that says the maps are unreviewed model suggestions.
- **Sources:** Security Hub control IDs (such as `CloudFront.3`, from `Compliance.SecurityControlId`, `ProductFields.ControlId` or the `GeneratorId`) are `control` items under a source resource that points to the Security Hub controls reference. Pasted text and documents are `statement` items.
- **Targets:** SCF controls, in a `catalog` target resource.
- **Maps:** every map uses the relationship `intersects-with` and carries the model's confidence as `confidence-score.percentage` and its justification in `remarks`. Duplicate source–target pairs are merged, keeping the highest confidence.
- The SCF release is recorded in the metadata remarks.

**Consequences.**
- The output can be loaded by OSCAL tooling. `tests/test_exports.py` parses it with compliance-trestle's OSCAL models (a dev-only dependency).
- `intersects-with` is the weakest positive relationship in NIST IR 8477. The tool does not establish subset, superset or equality, so it does not claim them. A reviewer who confirms a map can tighten the relationship and change the status.
- OSCAL's mapping model is designed for control-to-control mappings. Policy text and documents are not controls, so they are modeled as `statement` sources under a local `#inputs` resource; the text itself is not embedded in the export.

---

## ADR-009: Evaluate against published mappings, not hand labels

**Status:** Accepted

**Decision.** `src/evaluation.py` and `scripts/run_eval.py` build a gold set from two published mappings: AWS's mapping of each Security Hub control to NIST SP 800-53 rev 5 (`RelatedRequirements` from `describe-standards-controls`), and SCF's crosswalk from its controls to NIST SP 800-53. A Security Hub control's gold SCF controls are the SCF controls that SCF maps to any of its 800-53 requirements. The script reports retrieval hit rate and mean recall at k = 10 and 50, and, with `--llm`, the precision and hit rate of the pipeline's suggestions.

**Consequences.**
- Anyone with read-only AWS access and the SCF download can reproduce the numbers; no labeling effort is needed, and the retrieval score needs no API key.
- The labels are transitive and coarse: one 800-53 requirement often maps to several SCF controls, and "shares an 800-53 requirement" is weaker than a reviewer's judgment. The numbers measure consistency with AWS's and SCF's mappings, not ground-truth accuracy, and the README says so.
- The inputs are Security Hub control titles and descriptions, so the score says nothing direct about policy text or scope documents.
- Results are not published yet; `eval/README.md` holds the method and will hold the numbers.
