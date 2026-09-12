#!/usr/bin/env python3
"""Read-only JSONL glossary audit. Flags candidates; never decides or merges terms.

Python 3.10+, standard library only. Exit 0: valid schema (review flags may
remain); 1: schema errors; 2: invalid input/options. No model or network calls.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sys
import unicodedata
from typing import Any

STATUSES = {"candidate", "provisional", "approved", "unresolved"}


def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def audit(paths: list[Path], max_groups: int = 100) -> dict[str, Any]:
    if not paths or max_groups < 1:
        raise ValueError("Provide at least one input and a positive --max-groups")
    records: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    inputs: list[dict[str, Any]] = []
    for path in paths:
        raw = path.read_bytes()
        seen: set[str] = set()
        valid_count = 0
        for number, line in enumerate(raw.decode("utf-8-sig").splitlines(), 1):
            if not line.strip():
                continue
            at = {"file": str(path), "line": number}
            try:
                row = json.loads(line, object_pairs_hook=strict_object)
            except ValueError as exc:
                errors.append({**at, "issue": str(exc)})
                continue
            if not isinstance(row, dict):
                errors.append({**at, "issue": "Each line must be an object"})
                continue
            issues = []
            for field in ("id", "source", "target", "meaning", "scope", "status"):
                value = row.get(field)
                if not isinstance(value, str) or (field != "target" and not value.strip()):
                    issues.append(f"{field} must be a nonempty string (target may be empty when unresolved)")
            if issues:
                errors.append({**at, "issue": "; ".join(issues)})
                continue
            if row["id"] in seen:
                issues.append("Duplicate id within this input")
            seen.add(row["id"])
            if row["status"] not in STATUSES:
                issues.append("Unknown status")
            if not row["target"].strip() and row["status"] != "unresolved":
                issues.append("Empty target requires status=unresolved")
            for field in ("aliases", "occurrences"):
                value = row.get(field, [])
                if not isinstance(value, list) or any(not isinstance(v, str) or not v.strip() for v in value):
                    issues.append(f"{field} must be an array of nonempty strings")
            if "canonical_id" in row and (not isinstance(row["canonical_id"], str) or not row["canonical_id"].strip()):
                issues.append("canonical_id must be a nonempty string")
            evidence = row.get("evidence", [])
            if not isinstance(evidence, list) or any(
                not isinstance(e, dict)
                or not isinstance(e.get("location"), str) or not e["location"].strip()
                or not isinstance(e.get("quote"), str) or not e["quote"].strip()
                for e in evidence
            ):
                issues.append("evidence must contain objects with nonempty location and quote")
            if issues:
                errors.append({**at, "id": row["id"], "issue": "; ".join(issues)})
                continue
            if row["status"] != "approved" and not evidence:
                warnings.append({**at, "id": row["id"], "issue": "No source evidence for coordinator review"})
            if row["status"] == "unresolved":
                warnings.append({**at, "id": row["id"], "issue": "Unresolved term"})
            records.append({"row": row, "at": at})
            valid_count += 1
        inputs.append({"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "valid_records": valid_count})

    # Literal overlap is only a retrieval aid: homographs must be judged in context.
    by_surface: dict[str, set[int]] = defaultdict(set)
    by_canonical: dict[str, set[int]] = defaultdict(set)
    approved_ids = {r["row"]["id"] for r in records if r["row"]["status"] == "approved"}
    for index, record in enumerate(records):
        row = record["row"]
        for surface in [row["source"], *row.get("aliases", [])]:
            by_surface[unicodedata.normalize("NFC", surface).strip()].add(index)
        if row["status"] == "approved":
            by_canonical[row["id"]].add(index)
        if row.get("canonical_id"):
            by_canonical[row["canonical_id"]].add(index)
            if row["canonical_id"] not in approved_ids:
                warnings.append({**record["at"], "id": row["id"], "issue": "Referenced canonical_id not present as approved in supplied inputs"})

    groups: list[dict[str, Any]] = []
    group_count = 0
    for kind, mapping in (("literal_overlap", by_surface), ("canonical_reference", by_canonical)):
        for key in sorted(mapping):
            members = sorted(mapping[key])
            if len(members) < 2:
                continue
            group_count += 1
            if len(groups) >= max_groups:
                continue
            rows = [records[i] for i in members]
            groups.append({
                "kind": kind, "key": key,
                "different_targets": len({r["row"]["target"] for r in rows}) > 1,
                "decision": "human_or_coordinator_context_review_required",
                "members": [{**r["at"], **r["row"]} for r in rows],
            })
    return {
        "tool": "term_audit", "read_only": True,
        "semantic_conflicts_resolved": False, "glossary_modified": False,
        "limitations": "Lexical/reference candidate grouping only; no semantic conflict verdict, deduplication or glossary merge.",
        "inputs": inputs, "records": len(records),
        "error_count": len(errors), "warning_count": len(warnings),
        "errors": errors, "warnings": warnings,
        "review_group_count": group_count, "review_groups": groups,
        "groups_truncated": group_count > len(groups),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--max-groups", type=int, default=100)
    args = parser.parse_args(argv)
    try:
        if args.report and (args.report.resolve() in {p.resolve() for p in args.files}
                            or (args.report.exists() and any(p.exists() and args.report.samefile(p) for p in args.files))):
            raise ValueError("Report must not overwrite an input")
        result = audit(args.files, args.max_groups)
        rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.report:
            with args.report.open("w", encoding="utf-8", newline="\n") as stream:
                stream.write(rendered)
        else:
            print(rendered, end="")
        return 1 if result["error_count"] else 0
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"term_audit: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
