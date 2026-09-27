"""
Build the Security Hub control list for scripts/run_eval.py from the public
AWS Security Hub user guide sources, for when `aws securityhub
describe-standards-controls` is not an option (no AWS account at hand).

    git clone https://github.com/awsdocs/aws-security-hub-user-guide.git awsdocs
    git -C awsdocs checkout 47bfe2f1de2e486914543113d2e751f3e2ed8868
    uv run python scripts/import_awsdocs_controls.py --repo awsdocs
    uv run python scripts/run_eval.py --controls data/awsdocs_controls.json

The repository is archived: its last commit on `archived` (8923bfa) deletes
the content, so use its parent 47bfe2f (the tip of `master`), whose
doc_source/ was last refreshed on 2023-03-10. Each doc_source/*-controls.md
page documents the controls for one AWS service with their "Related
requirements", including NIST.800-53.r5 IDs.

The output holds AWS documentation text (CC BY-SA 4.0), so it goes to data/,
which is git-ignored. Commit only IDs and numbers derived from it.
"""

import argparse
import glob
import json
import os
import subprocess  # nosec B404
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(ROOT, "src"))

from evaluation import parse_awsdocs_controls  # noqa: E402

SOURCE_REPO = "https://github.com/awsdocs/aws-security-hub-user-guide"
DEFAULT_OUT = os.path.join(ROOT, "data", "awsdocs_controls.json")


def git_head(repo: str) -> str | None:
    """The checkout's commit, for provenance. A fixed git command, no shell."""
    try:
        out = subprocess.run(  # nosec B603 B607
            ["git", "-C", repo, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip() or None


def import_controls(doc_source: str) -> tuple[list[dict], list[str]]:
    """Controls from every *-controls.md page, first occurrence of each ID kept."""
    controls: dict[str, dict] = {}
    duplicates = []
    for path in sorted(glob.glob(os.path.join(doc_source, "*-controls.md"))):
        with open(path, encoding="utf-8") as f:
            for control in parse_awsdocs_controls(f.read()):
                if control["ControlId"] in controls:
                    duplicates.append(control["ControlId"])
                    continue
                control["SourceFile"] = os.path.basename(path)
                controls[control["ControlId"]] = control
    return list(controls.values()), duplicates


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo", required=True, help="clone of the awsdocs repo")
    parser.add_argument("--out", default=DEFAULT_OUT, help="output JSON path")
    args = parser.parse_args(argv)

    doc_source = os.path.join(args.repo, "doc_source")
    if not os.path.isdir(doc_source):
        print(f"No doc_source/ in {args.repo}; check out commit 47bfe2f (see --help).")
        return 1
    controls, duplicates = import_controls(doc_source)
    if not controls:
        print(f"No controls found under {doc_source}.")
        return 1
    source = {"repo": SOURCE_REPO, "commit": git_head(args.repo), "path": "doc_source"}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"Source": source, "StandardsControls": controls}, f, indent=1)
    with_nist = sum(
        any(r.startswith("NIST.800-53.r5") for r in c["RelatedRequirements"])
        for c in controls
    )
    print(
        f"Wrote {len(controls)} controls ({with_nist} with NIST 800-53 rev 5 "
        f"requirements) from commit {source['commit']} to {args.out}"
    )
    if duplicates:
        print(f"Skipped duplicate control IDs: {', '.join(duplicates)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
