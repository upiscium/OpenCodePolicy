#!/usr/bin/env python3
"""Backward-compatible dual-consumer audit CLI."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from policy_audit import (
    audit_profiles,
    format_summary,
    invalid_consumer_roots,
    result_exit_code,
)
from validate_policy import ROOT, load_policy, validate_policy


def audit(dotnix: Path, templates: Path, policy_root: Path = ROOT) -> tuple[list[str], Counter[str]]:
    errors = validate_policy(policy_root)
    if errors:
        return [f"DIFF POLICY_INVALID {error}" for error in errors], Counter(DIFF=len(errors))
    documents, _ = load_policy(policy_root)
    return audit_profiles({"global": dotnix, "agent-core": templates}, documents)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dotnix", type=Path, required=True)
    parser.add_argument("--templates", type=Path, required=True)
    parser.add_argument("--strict", action="store_true", help="return non-zero for unexpected drift")
    args = parser.parse_args()
    roots = {"global": args.dotnix.resolve(), "agent-core": args.templates.resolve()}
    invalid = invalid_consumer_roots(roots)
    if invalid:
        for path in invalid:
            print(f"ERROR consumer path is not a directory: {path}")
        return 2
    lines, counts = audit(roots["global"], roots["agent-core"])
    for line in lines:
        print(line)
    print(format_summary(counts))
    return result_exit_code(lines, counts, args.strict)


if __name__ == "__main__":
    raise SystemExit(main())
