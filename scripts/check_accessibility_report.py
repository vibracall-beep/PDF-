#!/usr/bin/env python3
"""Validate own-window AX audit artifacts; does not operate VoiceOver or grant TCC."""
import json
import os
import stat
import sys
from pathlib import Path


MAX_REPORT_BYTES = 16 * 1024 * 1024
ACTIONABLE_ROLES = {"AXButton", "AXCheckBox", "AXRadioButton", "AXPopUpButton", "AXComboBox", "AXTextField", "AXSlider", "AXMenuButton"}


def read_report(path: Path):
    flags = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_REPORT_BYTES:
            raise ValueError(f"{path}: expected a regular accessibility report of at most 16 MB")
        data = stream.read(MAX_REPORT_BYTES + 1)
        if len(data) > MAX_REPORT_BYTES:
            raise ValueError(f"{path}: accessibility report grew beyond its size limit")
    return json.loads(data)


def check(path: Path, *, report=None) -> bool:
    # The artifact gate passes the same already-opened document; do not reopen a
    # pathname that may have been replaced after its regular-file verification.
    if report is None:
        report = read_report(path)
    if not isinstance(report, dict) or type(report.get("version")) is not int or report["version"] != 1 or report.get("scope") != "current-process-own-window":
        raise ValueError(f"{path}: unsupported accessibility report")
    nodes = report.get("nodes")
    findings = report.get("findings")
    missing = report.get("missingRequiredIdentifiers")
    limited = report.get("traversalLimited")
    if not isinstance(nodes, list) or len(nodes) > 10_000 or not isinstance(findings, list) or not isinstance(missing, list) or type(limited) is not bool:
        raise ValueError(f"{path}: invalid or incomplete accessibility report fields")
    if any(not isinstance(item, dict) or not isinstance(item.get("code"), str) for item in findings) or any(not isinstance(identifier, str) for identifier in missing):
        raise ValueError(f"{path}: malformed accessibility findings or missing identifiers")
    indices = set()
    for node in nodes:
        if not isinstance(node, dict) or type(node.get("index")) is not int or node["index"] < 0 or node["index"] in indices or not isinstance(node.get("name"), str) or not isinstance(node.get("role"), str) or (node.get("identifier") is not None and not isinstance(node["identifier"], str)):
            raise ValueError(f"{path}: malformed or duplicate accessibility node")
        indices.add(node["index"])
    failures = [item for item in findings
                if item.get("code") in {"unnamed-app-control", "missing-required-identifier", "traversal-limit"}]
    if limited:
        failures.append({"code": "traversal-limit", "detail": "traversalLimited is true"})
    if missing:
        failures.append({"code": "missing-required-identifier", "detail": ", ".join(missing)})
    for node in nodes:
        if (node.get("identifier") or "").startswith("pdf.") and node["role"] in ACTIONABLE_ROLES and not node["name"].strip():
            failures.append({"code": "unnamed-app-control", "node": node["index"], "detail": node["identifier"]})
    if not nodes:
        failures.append({"code": "empty-accessibility-tree"})
    reviews = [item for item in findings if item.get("code") == "unnamed-control-review"]
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
