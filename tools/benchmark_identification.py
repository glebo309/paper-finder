#!/usr/bin/env python3
"""Opt-in, metadata-only identification benchmark. Never downloads documents.

Run from any directory:
  python tools/benchmark_identification.py                    # inspect cases
  python tools/benchmark_identification.py --live --output /tmp/paper-benchmark.json

This small curated smoke benchmark is not a representative accuracy estimate.
Add held-out, domain-specific queries before calibrating ranking thresholds.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / "tests" / "fixtures" / "identification_cases.json"


def load_cases(path):
    data = json.loads(Path(path).read_text())
    cases = data["cases"] if isinstance(data, dict) else data
    if not isinstance(cases, list) or not cases:
        raise ValueError("Benchmark requires a non-empty case list")
    seen = set()
    for case in cases:
        if case["id"] in seen:
            raise ValueError("Duplicate case ID: " + case["id"])
        seen.add(case["id"])
        if not case.get("query") or not (case.get("expected_ids") or case.get("must_abstain")):
            raise ValueError("Every case needs a query and expected IDs or must_abstain")
    return cases


def normalize_id(value):
    value = str(value).strip().lower()
    value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "doi:", value)
    value = re.sub(r"^https?://arxiv\.org/(?:abs|pdf)/", "arxiv:", value).removesuffix(".pdf")
    if value.startswith("10."):
        value = "doi:" + value
    value = value.replace("doi:10.48550/arxiv.", "arxiv:")
    if value.startswith("arxiv:"):
        value = re.sub(r"v\d+$", "", value)
    return value


def candidate_ids(candidate):
    values = set()
    if not candidate:
        return values
    if candidate.get("doi"):
        values.add(normalize_id(candidate["doi"]))
    if candidate.get("arxiv_id"):
        values.add(normalize_id("arxiv:" + candidate["arxiv_id"]))
    identifier = candidate.get("identifier") or {}
    if identifier.get("type") in {"doi", "arxiv", "pmid", "isbn"} and identifier.get("value"):
        values.add(normalize_id(identifier["type"] + ":" + identifier["value"]))
    for kind, value in (candidate.get("ids") or {}).items():
        if value and kind in {"doi", "arxiv", "pmid"}:
            values.add(normalize_id(value if str(value).startswith("http") else kind + ":" + str(value)))
    return values


def matches(candidate, expected):
    return bool(candidate_ids(candidate) & {normalize_id(value) for value in expected})


def run_benchmark(service, cases):
    rows = []
    for case in cases:
        start = time.monotonic()
        try:
            response = service.search(case["query"], limit=10, mode="identify")
        except Exception as exc:
            response = {"status": "unavailable", "candidates": [], "selected": None,
                        "errors": {"benchmark": {"kind": type(exc).__name__, "message": str(exc)}}}
        elapsed = time.monotonic() - start
        candidates = response.get("candidates") or []
        expected = case.get("expected_ids", [])
        selected = response.get("selected") if response.get("status") == "matched" else None
        unavailable = response.get("status") == "unavailable"
        automatic = selected is not None
        correct = automatic and matches(selected, expected) and not case.get("must_abstain", False)
        rows.append({
            "id": case["id"], "category": case.get("category", "unspecified"), "query": case["query"],
            "expected_ids": expected, "must_abstain": case.get("must_abstain", False),
            "status": response.get("status"), "latency_seconds": round(elapsed, 3),
            "top1_correct": bool(candidates and expected and matches(candidates[0], expected)),
            "top5_correct": bool(expected and any(matches(item, expected) for item in candidates[:5])),
            "correct_automatic": bool(correct), "wrong_automatic": bool(automatic and not correct),
            "abstained": not automatic and not unavailable,
            "correct_abstention": bool(case.get("must_abstain") and not automatic and not unavailable),
            "unavailable": unavailable, "errors": response.get("errors") or {},
            "selected_ids": sorted(candidate_ids(selected)),
            "candidates": [{"title": item.get("title"), "ids": sorted(candidate_ids(item)),
                            "score": item.get("score"), "match_reasons": item.get("match_reasons", [])}
                           for item in candidates[:5]],
        })
    summary = {key: sum(bool(row[key]) for row in rows) for key in
               ("top1_correct", "top5_correct", "correct_automatic", "wrong_automatic",
                "abstained", "correct_abstention", "unavailable")}
    latencies = sorted(row["latency_seconds"] for row in rows)
    summary.update({"cases": len(rows), "target_cases": sum(bool(row["expected_ids"]) for row in rows),
                    "must_abstain_cases": sum(row["must_abstain"] for row in rows),
                    "api_errors": sum(len(row["errors"]) for row in rows),
                    "median_latency_seconds": statistics.median(latencies) if latencies else None,
                    "max_latency_seconds": max(latencies) if latencies else None})
    return {"generated_at": datetime.now(timezone.utc).isoformat(), "mode": "metadata-only",
            "note": "Curated smoke cases, not a general accuracy estimate. Unavailable APIs are not counted as correct abstentions.",
            "summary": summary, "cases": rows}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true", help="Allow metadata API requests; never downloads PDFs")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--case", action="append", default=[], help="Run specified case ID (repeatable)")
    parser.add_argument("--output", type=Path, help="Write full JSON report")
    parser.add_argument("--timeout", type=float, default=8, help="Per-provider timeout seconds")
    parser.add_argument("--deadline", type=float, default=25, help="Per-query deadline seconds")
    args = parser.parse_args(argv)
    cases = load_cases(args.cases)
    if args.case:
        known = {case["id"] for case in cases}
        unknown = set(args.case) - known
        if unknown:
            parser.error("Unknown case IDs: " + ", ".join(sorted(unknown)))
        cases = [case for case in cases if case["id"] in args.case]
    if not args.live:
        print(f"{len(cases)} cases ready. Add --live to query metadata APIs. No downloads are performed.")
        for case in cases:
            print(f"{case['id']}: {case['query']}")
        return 0
    if args.timeout <= 0 or args.deadline <= 0:
        parser.error("--timeout and --deadline must be positive")
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from src.core.discovery import DiscoveryService
    report = run_benchmark(DiscoveryService(timeout=args.timeout, deadline=args.deadline), cases)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 2 if report["summary"]["unavailable"] == len(cases) else 0


if __name__ == "__main__":
    raise SystemExit(main())
