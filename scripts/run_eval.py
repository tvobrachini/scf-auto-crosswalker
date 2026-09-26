"""
Build the Security Hub -> NIST 800-53 -> SCF gold set and score the pipeline.

    # 1. Security Hub controls with their NIST 800-53 mappings (read-only call).
    #    Use the subscription ARN of the NIST SP 800-53 rev 5 standard, or AWS FSBP.
    aws securityhub describe-standards-controls \
        --standards-subscription-arn <arn> > eval/standards_controls.json

    # 2. Build the gold set and score retrieval (no Groq key needed)
    uv run python scripts/run_eval.py --controls eval/standards_controls.json

    # 3. Also score the model step (one Groq call per case)
    uv run python scripts/run_eval.py --gold eval/gold.csv --llm

Needs the SCF database in data/ and network access to Hugging Face for the
embedding model. See eval/README.md for what the numbers mean.
"""

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(ROOT, "src"))

from evaluation import (  # noqa: E402
    build_gold_set,
    nist_800_53_column,
    read_gold_csv,
    results_markdown,
    score_model,
    score_retrieval,
    write_gold_csv,
)
from fetch_scf import read_scf_release  # noqa: E402
from mapper import (  # noqa: E402
    DEFAULT_GROQ_MODEL,
    _semantic_filter,
    load_scf_database,
    map_text_to_scf,
)

EVAL_DIR = os.path.join(ROOT, "eval")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--controls", help="describe-standards-controls JSON output")
    source.add_argument("--gold", help="an existing gold CSV")
    parser.add_argument("--column", help="SCF crosswalk column for NIST 800-53")
    parser.add_argument("--llm", action="store_true", help="also score the model step")
    parser.add_argument("--limit", type=int, help="score only the first N cases")
    args = parser.parse_args(argv)

    scf_data = load_scf_database()
    if not scf_data:
        print("SCF database not found. Download it from the app sidebar first.")
        return 1
    column = nist_800_53_column(scf_data, args.column)

    if args.controls:
        if column is None and args.column:
            print(f"The SCF data has no crosswalk column named {args.column!r}.")
            return 1
        if column is None:
            print("No NIST 800-53 column in the SCF data; pass --column.")
            return 1
        with open(args.controls, encoding="utf-8") as f:
            data = json.load(f)
        controls = (
            data.get("StandardsControls", data) if isinstance(data, dict) else data
        )
        cases = build_gold_set(controls, scf_data, column)
        os.makedirs(EVAL_DIR, exist_ok=True)
        gold_path = os.path.join(EVAL_DIR, "gold.csv")
        write_gold_csv(cases, gold_path)
        print(f"Wrote {len(cases)} cases to {gold_path}")
    else:
        cases = read_gold_csv(args.gold)

    if args.limit:
        cases = cases[: args.limit]

    def retrieve(text: str, k: int) -> list[str]:
        return [c["control_id"] for c in _semantic_filter(text, scf_data, top_k=k)]

    retrieval = score_retrieval(cases, retrieve)

    model = None
    llm_name = None
    if args.llm:
        if not os.environ.get("GROQ_API_KEY"):
            print("GROQ_API_KEY is not set; skipping the model step.")
        else:
            llm_name = os.environ.get("GROQ_MODEL", DEFAULT_GROQ_MODEL)

            def suggest(text: str) -> list[str]:
                result = map_text_to_scf(text, top_k=3)
                return [m.control_id for m in result.mappings] if result else []

            model = score_model(cases, suggest)

    table = results_markdown(retrieval, model, read_scf_release(), column, llm_name)
    os.makedirs(EVAL_DIR, exist_ok=True)
    out = os.path.join(EVAL_DIR, "results.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(table)
    print(table)
    print(f"Saved to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
