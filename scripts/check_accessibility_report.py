#!/usr/bin/env python3
"""Validate own-window AX audit artifacts; does not operate VoiceOver or grant TCC."""
import json
import sys
from pathlib import Path


def check(path: Path) -> bool:
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("version") != 1 or report.get("scope") != "current-process-own-window":
        raise ValueError(f"{path}: unsupported accessibility report")
    failures = [item for item in report.get("findings", [])
                if item.get("code") in {"unnamed-app-control", "missing-required-identifier", "traversal-limit"}]
    nodes = report.get("nodes", [])
    if not nodes:
        failures.append({"code": "empty-accessibility-tree"})
    reviews = [item for item in report.get("findings", []) if item.get("code") == "unnamed-control-review"]
    print(f"{path.name}: {len(nodes)} nodes, {len(failures)} failures, {len(reviews)} controls to review")
    for item in failures + reviews:
        print(f"  {item.get('code')}: {item.get('detail', '')} (node {item.get('node', '-')})")
    print("  VoiceOver interaction, contrast and PDF reading order require separate checks.")
    return not failures


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Usage: check_accessibility_report.py REPORT.json [REPORT.json ...]")
    outcomes = [check(Path(argument)) for argument in sys.argv[1:]]
    raise SystemExit(0 if all(outcomes) else 1)
