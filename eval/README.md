# Evaluation

`scripts/run_eval.py` measures how well the pipeline agrees with two published mappings. It needs no hand labeling.

## How the gold set is built

1. **AWS → NIST.** Every AWS Security Hub control lists the NIST SP 800-53 rev 5 requirements AWS maps it to (`RelatedRequirements`, e.g. `NIST.800-53.r5 SC-8(1)`). `aws securityhub describe-standards-controls` returns them, and so does the control reference in the AWS Security Hub user guide.
2. **NIST → SCF.** The SCF workbook maps each SCF control to NIST SP 800-53. That column (`NIST 800-53 R5.2` in release 2026.3) is kept in `data/scf_parsed.json`. SCF zero-pads the IDs (`AC-02(01)`) and AWS does not (`AC-2(1)`), so both sides are normalized to one spelling before the join.
3. **Gold.** A Security Hub control's gold SCF controls are the SCF controls that SCF maps to any of its 800-53 requirements. The input text is the control's title and description.

The mapping is transitive. A gold pair says the finding and the SCF control share an 800-53 requirement, not that a reviewer judged the pair. One 800-53 requirement often maps to several SCF controls, so each case can have many gold controls. The numbers measure consistency with AWS's and SCF's published mappings. They are not ground-truth accuracy.

## Run it

You need the SCF database (click **Download / Update SCF Data** in the app once) and the Security Hub controls, from either source below. The embedding model comes from Hugging Face, or from its ONNX export with `--onnx-model`.

```bash
# 1a. Security Hub controls with their NIST mappings, from the API (read-only).
#     Use the subscription ARN of the "NIST SP 800-53 Revision 5" standard (or AWS FSBP)
#     from `aws securityhub get-enabled-standards`.
aws securityhub describe-standards-controls \
    --standards-subscription-arn <arn> > data/standards_controls.json

# 1b. Or from the public user guide sources (no AWS account). The repository is
#     archived; its last commit deletes the content, so check out the parent.
git clone https://github.com/awsdocs/aws-security-hub-user-guide.git awsdocs
git -C awsdocs checkout 47bfe2f1de2e486914543113d2e751f3e2ed8868
uv run python scripts/import_awsdocs_controls.py --repo awsdocs   # -> data/awsdocs_controls.json

# 2. Build eval/gold.csv and score retrieval. No Groq key needed.
uv run python scripts/run_eval.py --controls data/awsdocs_controls.json

# 2b. Same, with the ONNX export of all-MiniLM-L6-v2 instead of Hugging Face.
#     The archive hash is the one chromadb pins; run_eval.py then refuses any
#     model.onnx other than the one the published results used.
curl -sSLo onnx.tar.gz https://chroma-onnx-models.s3.amazonaws.com/all-MiniLM-L6-v2/onnx.tar.gz
echo "913d7300ceae3b2dbc2c50d1de4baacab4be7b9380491c27fab7418616a16ec3  onnx.tar.gz" | sha256sum -c -
tar xzf onnx.tar.gz   # -> onnx/model.onnx, onnx/tokenizer.json
uv run --with onnxruntime python scripts/run_eval.py \
    --controls data/awsdocs_controls.json --onnx-model onnx

# 3. Score the model step too: one Groq call per case.
uv run python scripts/run_eval.py --gold eval/gold.csv --llm

# 3b. Or on an OpenRouter model instead of Groq (needs OPENROUTER_API_KEY;
#     langchain-openai is not a project dependency, only used for this).
uv run --with langchain-openai python scripts/run_eval.py \
    --gold eval/gold.csv --llm --openrouter-model <model id>
```

The report is written to `eval/results.md` and the per-case ranks to `eval/per_case_retrieval.csv`. Both hold only IDs and numbers. `eval/gold.csv` and the control files hold AWS documentation text (CC BY-SA 4.0) and are not committed.

## Metrics

| Stage | Metric | Meaning |
|---|---|---|
| Retrieval | Hit rate @k | Share of cases where at least one gold control is among the top k retrieved candidates. At k = 50 (what the model sees), a miss means the model cannot give an answer the gold set counts as correct. |
| Retrieval | Mean recall @k | Mean share of each case's gold controls found in the top k. |
| Retrieval | MRR @k | Mean of 1 / (rank of the first gold control), counting 0 when none is in the top k. It rewards putting a gold control near the top, not just somewhere in the top k. |
| Baseline | Random (expected) | The exact expectation of each metric for a retriever that ranks the 1,591 controls at random, given each case's gold-set size. Big gold sets make hit rate cheap; this is the floor. |
| Baseline | TF-IDF | A lexical retriever over the same control texts (`scikit-learn` `TfidfVectorizer`, English stop words, sublinear tf, unigrams and bigrams, cosine similarity). The embedding model has to beat word overlap to earn its place. |
| Model | Precision of suggestions | Share of the controls the pipeline suggested (up to 3 per case) that are gold. |
| Model | Hit rate | Share of cases with at least one gold suggestion. |
| Model | Cases with no suggestion | Cases where the pipeline suggested nothing: the model returned no IDs, or every ID it returned was rejected. |
| Model | Cases where the call failed | Cases where the Groq call failed after retries. They are skipped, not retried, and count as misses in the hit rate. |

## Results

### Retrieval, 2026-09-27

Only the retrieval step has been scored. The model step has not been run: there was no Groq API key for this run, so there are no precision or model hit-rate figures yet.

**Inputs and provenance**

| Input | Source | Identity |
|---|---|---|
| SCF | Release 2026.3, `secure-controls-framework-scf-2026-3.xlsx` from [securecontrolsframework/securecontrolsframework](https://github.com/securecontrolsframework/securecontrolsframework) at commit `d08211314fc7ccfca8e6c84d2b27a2030339ef9c` | Workbook sha256 `5a89bf2d3c106a9a87d4b6e3d62dd3e147d0e960d4c07473045a10aa8a7df697`. Parsed by `src/fetch_scf.py` into 1,591 controls. 800-53 column `NIST 800-53 R5.2` (776 controls have an entry). |
| Security Hub controls | `doc_source/*-controls.md` of [awsdocs/aws-security-hub-user-guide](https://github.com/awsdocs/aws-security-hub-user-guide) at commit `47bfe2f1de2e486914543113d2e751f3e2ed8868` (tip of `master`; the parent of `8923bfa`, the `archived` branch head, which deletes the content). The content was last refreshed on 2023-03-10. | 251 controls parsed by `scripts/import_awsdocs_controls.py`. |
| Embedding model | `all-MiniLM-L6-v2`, ONNX export at `https://chroma-onnx-models.s3.amazonaws.com/all-MiniLM-L6-v2/onnx.tar.gz` (a path left in its `tokenizer_config.json` points to Hugging Face snapshot `7dbbc90392e2f80f3d3c277d6e90027e55de9125` of `sentence-transformers/all-MiniLM-L6-v2`, which suggests, but does not prove, what it was exported from) | Archive sha256 `913d7300ceae3b2dbc2c50d1de4baacab4be7b9380491c27fab7418616a16ec3`, equal to the `_MODEL_SHA256` that chromadb 1.5.9 pins in `chromadb/utils/embedding_functions/onnx_mini_lm_l6_v2.py` (wheel downloaded from PyPI). `model.onnx` sha256 `4f148ba8ae9c2c7fbee4af2b132db8d06c6a6545b47fc83bbb98c3d22b8393e6`. |

**Cross-check of the model.** Qdrant's fastembed publishes a separate ONNX export of the same model (`https://storage.googleapis.com/qdrant-fastembed/sentence-transformers-all-MiniLM-L6-v2.tar.gz`, archive sha256 `2735afe656e156af64ed603dbb1c96f3cae7f937286a8feb27fff7fa979f6a77`, a different `model.onnx` file, sha256 `bbd7b466…`). Run through `src/onnx_encoder.py` on 50 texts (25 SCF control texts, 23 Security Hub cases, a one-word text and a 480-word text), the two exports gave identical embeddings: maximum absolute difference 0, minimum cosine similarity 0.99999988 (float32 rounding). fastembed's own pipeline agreed with our encoder to a maximum absolute difference of 5.6e-8 on the 49 texts under 128 tokens. On the 480-word text it differs (cosine 0.897) because fastembed truncates at the tokenizer file's 128 tokens, while sentence-transformers, and our encoder, truncate at 256. Encoding in padded batches and one text at a time gave identical results.

**What was scored.** `_semantic_filter` from `src/mapper.py`, unchanged: control text `"{ID} {domain}: {description}"`, input chunked at 150 words, best chunk per control, top 50 candidates. Only `_get_embedding_model` was swapped for the ONNX encoder. The input is `Title: … Description: …`, where the description is the first prose paragraph of the control's section in the user guide.

```bash
uv run --with onnxruntime python scripts/run_eval.py \
    --controls data/awsdocs_controls.json --onnx-model <extracted onnx dir>
```

**Gold set**

| | |
|---|---|
| Security Hub controls read | 251 |
| Dropped: no NIST 800-53 rev 5 requirement | 30 |
| Dropped: SCF maps none of their 800-53 requirements | 0 |
| Cases | 221 |
| Gold links (case, SCF control) | 1,866, over 133 distinct SCF controls |
| Gold controls per case | median 7, mean 8.4, quartiles 4 / 12, max 28 |
| Cases with at most 10 gold controls | 140 |

13 of the 123 distinct 800-53 IDs AWS cites have no SCF mapping; they add nothing to a case's gold set. Before the ID normalization (SCF writes `AC-02(01)`, AWS `AC-2(1)`), the join kept only 107 cases and 334 gold links.

**All 221 cases**

| k | Embedding hit rate | TF-IDF hit rate | Random hit rate | Embedding recall | TF-IDF recall | Random recall | Embedding MRR | TF-IDF MRR | Random MRR |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 11.3% | 7.2% | 0.5% | 1.3% | 0.7% | 0.1% | 0.113 | 0.072 | 0.005 |
| 3 | 18.6% | 16.7% | 1.6% | 2.7% | 2.3% | 0.2% | 0.145 | 0.115 | 0.010 |
| 5 | 24.9% | 20.8% | 2.6% | 4.2% | 3.4% | 0.3% | 0.159 | 0.124 | 0.012 |
| 10 | 38.0% | 27.1% | 5.2% | 7.4% | 4.5% | 0.6% | 0.176 | 0.132 | 0.015 |
| 20 | 50.7% | 36.7% | 10.0% | 13.0% | 7.2% | 1.3% | 0.184 | 0.139 | 0.019 |
| 50 | 62.0% | 46.2% | 22.8% | 21.7% | 10.7% | 3.1% | 0.188 | 0.142 | 0.022 |

**Stricter: the 140 cases with at most 10 gold controls**

| k | Embedding hit rate | TF-IDF hit rate | Random hit rate | Embedding recall | TF-IDF recall | Random recall | Embedding MRR | TF-IDF MRR | Random MRR |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 7.1% | 4.3% | 0.3% | 1.1% | 0.6% | 0.1% | 0.071 | 0.043 | 0.003 |
| 3 | 13.6% | 11.4% | 1.0% | 2.8% | 2.3% | 0.2% | 0.101 | 0.074 | 0.006 |
| 5 | 18.6% | 14.3% | 1.6% | 4.6% | 3.7% | 0.3% | 0.113 | 0.081 | 0.008 |
| 10 | 27.1% | 17.1% | 3.3% | 7.8% | 4.9% | 0.6% | 0.123 | 0.084 | 0.010 |
| 20 | 37.9% | 25.0% | 6.4% | 13.2% | 8.0% | 1.3% | 0.130 | 0.090 | 0.012 |
| 50 | 47.9% | 35.0% | 15.2% | 20.8% | 11.7% | 3.1% | 0.134 | 0.093 | 0.014 |

The generated report is [`results.md`](results.md); per-case ranks (control ID, number of 800-53 references, gold-set size, rank of the first gold control for each retriever, random hit probability at 50) are in [`per_case_retrieval.csv`](per_case_retrieval.csv).

**What the numbers show**

- At k = 50, the shortlist the model sees, 84 of 221 cases (38%) contain no control that the published mappings link to the finding. For those, the model cannot give an answer that agrees with AWS and SCF. Among cases with at most 10 gold controls, the share is 52%. Retrieval is the pipeline's main bottleneck on this data.
- Embeddings beat word overlap: at k = 50, 62.0% against 46.2% for TF-IDF over the same texts (paired on the same cases: 53 cases only the embedding finds, 18 only TF-IDF finds; exact McNemar p ≈ 4e-5). At k = 10 it is 38.0% against 27.1% (40 vs 16, p ≈ 0.002). The 18 cases only TF-IDF finds suggest that a hybrid ranker could help; that has not been tried.
- Both are far above chance. Random ranking would already reach 22.8% at k = 50 because gold sets are large, which is why the random column is there.
- With 221 cases, a hit rate near 62% has a 95% interval of roughly ±6 points.

**What they do not show**

- **Whether a suggestion is right.** The labels are transitive. A "miss" can be an SCF control that fits the finding but that SCF did not map to the same 800-53 requirement; 815 of the 1,591 SCF controls have no 800-53 entry at all and can never count as a hit. A "hit" can be a loose fit that happens to share a broad requirement.
- **The model step.** No Groq key was available, so the precision of the pipeline's suggestions is unmeasured.
- **Today's Security Hub.** The control list and texts are the user guide as of March 2023. AWS has since added and renamed controls and changed mappings. The description is the guide's first paragraph, an approximation of the API's `Description` field.
- **The exact production model.** The app runs the PyTorch model through sentence-transformers. This run used an ONNX export whose hash matches the one chromadb pins and which matches a second, independent export exactly, but it was not compared with the PyTorch model itself (Hugging Face was not reachable).
- **Other inputs.** The inputs are short Security Hub control titles and descriptions, not live findings, policy text or scope documents.
