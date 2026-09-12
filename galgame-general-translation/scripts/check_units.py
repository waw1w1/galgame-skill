#!/usr/bin/env python3
"""Check aligned, normalized JSONL translation units; never modify either input.

Python 3.10+, standard library only. Not an engine parser or semantic checker.
Exit 0: no structural errors (warnings may remain); 1: structural errors;
2: input/options/configuration error. See references/format-qa.md for the contract.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any


def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def load_units(path: Path) -> tuple[list[dict[str, Any]], str]:
    raw = path.read_bytes()
    records = []
    for number, line in enumerate(raw.decode("utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line, object_pairs_hook=strict_object)
        except ValueError as exc:
            raise ValueError(f"{path}:{number}: {exc}") from exc
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"].strip() or not isinstance(row.get("text"), str):
            raise ValueError(f"{path}:{number}: expected object with nonempty string id and string text")
        records.append(row)
    return records, hashlib.sha256(raw).hexdigest()


def string_array(path: Path) -> list[str]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, list) or any(not isinstance(x, str) or not x for x in value):
        raise ValueError(f"{path}: expected JSON array of nonempty strings")
    return value


def protected_tokens(text: str, patterns: list[re.Pattern[str]]) -> list[str]:
    spans = sorted((m.start(), m.end(), m.group(0)) for p in patterns for m in p.finditer(text))
    end = -1
    tokens = []
    for start, stop, token in spans:
        if start == stop:
            raise ValueError("Protection patterns must not match empty text")
        if start < end:
            raise ValueError("Protection patterns overlap; make token boundaries unambiguous")
        end = stop
        tokens.append(token)
    return tokens


def check(source: Path, target: Path, patterns: list[re.Pattern[str]] | None = None,
          allowed: set[str] | None = None, max_chars: int | None = None,
          max_issues: int = 100) -> dict[str, Any]:
    if max_issues < 1 or (max_chars is not None and max_chars < 1):
        raise ValueError("Length and issue limits must be positive")
    if patterns is not None and not patterns:
        raise ValueError("Provide nonempty protection patterns or omit the option")
    src, source_hash = load_units(source)
    dst, target_hash = load_units(target)
    counts: dict[str, Counter[str]] = {"errors": Counter(), "warnings": Counter()}
    samples: dict[str, list[dict[str, str]]] = {"errors": [], "warnings": []}

    def add(level: str, kind: str, ident: str, detail: str) -> None:
        counts[level][kind] += 1
        if len(samples[level]) < max_issues:
            samples[level].append({"kind": kind, "id": ident, "detail": detail})

    for name, rows in (("source", src), ("target", dst)):
        for ident, number in Counter(r["id"] for r in rows).items():
            if number > 1:
                add("errors", "duplicate_id", ident, f"{name}: {number} occurrences")
    smap = {r["id"]: r for r in src}
    tmap = {r["id"]: r for r in dst}
    for ident in sorted(smap.keys() - tmap.keys()):
        add("errors", "missing_id", ident, "Missing from target")
    for ident in sorted(tmap.keys() - smap.keys()):
        add("errors", "extra_id", ident, "Not present in source")
    if [r["id"] for r in src] != [r["id"] for r in dst]:
        add("errors", "sequence_mismatch", "", "ID sequence differs")
    if not src:
        add("warnings", "empty_source", "", "No source units; verify the requested scope separately")
    if patterns is None:
        add("warnings", "protection_not_checked", "", "No engine-specific protection patterns supplied")
    allowed = allowed or set()
    for ident in sorted(allowed - smap.keys()):
        add("warnings", "unknown_allowlist_id", ident, "No source unit has this allowed ID")
    compared = 0
    for ident, sr in smap.items():
        if ident not in tmap:
            continue
        tr = tmap[ident]
        compared += 1
        source_meta = json.dumps({k: v for k, v in sr.items() if k != "text"}, sort_keys=True, allow_nan=False)
        target_meta = json.dumps({k: v for k, v in tr.items() if k != "text"}, sort_keys=True, allow_nan=False)
        if source_meta != target_meta:
            add("errors", "metadata_changed", ident, "Non-text fields differ")
        st, tt = sr["text"], tr["text"]
        if st.strip() and not tt.strip():
            add("errors", "empty_translation", ident, "Nonempty source has an empty target")
        if not st.strip() and tt.strip():
            add("warnings", "text_added_to_empty_source", ident, "Review whether this addition is intended")
        if st.strip() and st == tt and ident not in allowed:
            add("warnings", "unchanged_text", ident, "Review or explicitly allow this exact ID")
        if "\ufffd" in tt:
            add("warnings", "replacement_character", ident, "Target contains U+FFFD")
        if max_chars is not None and len(tt) > max_chars:
            add("warnings", "length_candidate", ident, f"{len(tt)} code points, including controls; limit {max_chars}")
        if patterns is not None and protected_tokens(st, patterns) != protected_tokens(tt, patterns):
            add("errors", "protected_tokens_changed", ident, "Protected token content, count or sequence differs")
    return {
        "tool": "check_units", "read_only": True,
        "semantic_review_performed": False, "engine_validation_performed": False,
        "limitations": "Normalized-unit structural checks only; not semantic review, engine parsing, pixel layout, encoding round-trip or runtime testing.",
        "source": {"path": str(source), "sha256": source_hash, "records": len(src)},
        "target": {"path": str(target), "sha256": target_hash, "records": len(dst)},
        "compared_unique_ids": compared, "protection_checked": patterns is not None,
        "pattern_count": len(patterns or []), "max_chars": max_chars,
        "error_count": sum(counts["errors"].values()), "warning_count": sum(counts["warnings"].values()),
        "error_counts": dict(counts["errors"]), "warning_counts": dict(counts["warnings"]),
        **samples,
        "examples_truncated": {level: sum(counts[level].values()) > len(samples[level]) for level in counts},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("--protected-patterns", type=Path)
    parser.add_argument("--allow-unchanged", type=Path)
    parser.add_argument("--max-chars", type=int)
    parser.add_argument("--max-issues", type=int, default=100)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    try:
        inputs = [p for p in (args.source, args.target, args.protected_patterns, args.allow_unchanged) if p]
        if args.report and (args.report.resolve() in {p.resolve() for p in inputs}
                            or (args.report.exists() and any(p.exists() and args.report.samefile(p) for p in inputs))):
            raise ValueError("Report must not overwrite an input or configuration file")
        patterns = [re.compile(p) for p in string_array(args.protected_patterns)] if args.protected_patterns else None
        allowed = set(string_array(args.allow_unchanged)) if args.allow_unchanged else None
        result = check(args.source, args.target, patterns, allowed, args.max_chars, args.max_issues)
        rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.report:
            with args.report.open("w", encoding="utf-8", newline="\n") as stream:
                stream.write(rendered)
        else:
            print(rendered, end="")
        return 1 if result["error_count"] else 0
    except (OSError, UnicodeError, ValueError, re.error) as exc:
        print(f"check_units: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
