#!/usr/bin/env python3
"""Score a running RAHBAR against a golden set, and gate CI on the result (section 5).

    python eval/run_eval.py --api http://<ingress>                 # your corpus
    python eval/run_eval.py --api ... --golden eval/fixtures/golden.fixture.yaml
    python eval/run_eval.py --api ... --update-baseline            # after a deliberate improvement

Exit code 0 when every gate passes, 1 when any fails. CI relies on that exit code.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import httpx
import yaml

HERE = Path(__file__).resolve().parent

# The gate from section 5.4. Change these only with a reason written in docs/PIPELINE.md.
MAX_RECALL5_DROP = 0.05        # recall@5 may fall at most 5 points below the baseline
MIN_CITATION_VALIDITY = 0.95   # at least 95% of citations must match retrieved passages
REQUIRED_ABSTENTION = 1.0      # every must-abstain question must be declined


def load_golden(path: Path) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    questions = data.get("questions") or []
    if not questions:
        sys.exit(f"no questions in {path}")
    return questions


def ask(client: httpx.Client, api: str, question: str) -> dict:
    """POST one question and return the AskResponse as a dict (see api/app/schemas.py)."""
    response = client.post(f"{api.rstrip('/')}/api/ask", json={"question": question})
    response.raise_for_status()
    return response.json()


def _normalize_name(name: str) -> str:
    return re.sub(r"[\s\-_.]+", "", Path(name).stem.lower())


def _match_passage(rel: dict, ret: dict) -> bool:
    """Check if retrieved passage matches relevant expectation by source and section."""
    rel_src = _normalize_name(rel.get("source", ""))
    ret_src = _normalize_name(ret.get("source", ""))
    src_match = (not rel_src) or (rel_src in ret_src) or (ret_src in rel_src)

    rel_sec = str(rel.get("section", "")).strip().lower()
    ret_sec = str(ret.get("section", "")).strip().lower()

    # Clause number matching (e.g. "1.21", "5.4")
    rel_clauses = re.findall(r"\d+\.\d+", rel_sec)
    ret_clauses = re.findall(r"\d+\.\d+", ret_sec)
    if rel_clauses and ret_clauses:
        sec_match = (rel_clauses[0] == ret_clauses[0])
    else:
        # Substring / keyword matching
        rel_clean = re.sub(r"[^\w\s]", "", rel_sec)
        ret_clean = re.sub(r"[^\w\s]", "", ret_sec)
        sec_match = (rel_clean in ret_clean) or (ret_clean in rel_clean) or (not rel_sec)

    return src_match and sec_match


def recall_at_k(relevant: list[dict], retrieved: list[dict], k: int) -> float | None:
    """Fraction of the relevant (source, section) pairs found in the top k retrieved.
    Return None when the question has no relevant passages (must-abstain questions)."""
    if not relevant:
        return None
    top_k = retrieved[:k]
    hits = 0
    for rel in relevant:
        if any(_match_passage(rel, ret) for ret in top_k):
            hits += 1
    return float(hits / len(relevant))


def citation_validity(response: dict) -> float | None:
    """Fraction of the response's citations that match a passage in response['retrieved'].
    Return None when there are no citations."""
    citations = response.get("citations", [])
    if not citations:
        return None
    retrieved = response.get("retrieved", [])
    if not retrieved:
        return 0.0

    valid_count = 0
    for c in citations:
        if any(_match_passage(c, ret) for ret in retrieved):
            valid_count += 1
    return float(valid_count / len(citations))


def summarise(rows: list[dict]) -> dict:
    """Overall recall@3, recall@5, citation validity and abstention correctness, plus
    recall@5 broken down by question type. This dict becomes results.json."""
    r3_scores: list[float] = []
    r5_scores: list[float] = []
    type_r5: dict[str, list[float]] = {}
    citation_scores: list[float] = []
    must_abstain_total = 0
    must_abstain_correct = 0
    latencies: list[float] = []

    for r in rows:
        latencies.append(r.get("seconds", 0.0))
        resp = r.get("response", {})
        relevant = r.get("relevant") or []
        retrieved = resp.get("retrieved", [])
        qtype = r.get("type", "ordinary")

        if r.get("must_abstain", False):
            must_abstain_total += 1
            if not resp.get("answered_from_context", True):
                must_abstain_correct += 1
        else:
            r3 = recall_at_k(relevant, retrieved, 3)
            r5 = recall_at_k(relevant, retrieved, 5)
            if r3 is not None:
                r3_scores.append(r3)
            if r5 is not None:
                r5_scores.append(r5)
                type_r5.setdefault(qtype, []).append(r5)

        cv = citation_validity(resp)
        if cv is not None:
            citation_scores.append(cv)

    avg_r3 = round(sum(r3_scores) / len(r3_scores), 4) if r3_scores else 0.0
    avg_r5 = round(sum(r5_scores) / len(r5_scores), 4) if r5_scores else 0.0
    avg_cv = round(sum(citation_scores) / len(citation_scores), 4) if citation_scores else 1.0
    abst_corr = round(must_abstain_correct / must_abstain_total, 4) if must_abstain_total else 1.0

    by_type = {}
    for t, scores in type_r5.items():
        by_type[t] = {
            "recall@5": round(sum(scores) / len(scores), 4) if scores else 0.0,
            "count": len(scores),
        }

    sorted_latencies = sorted(latencies)
    mean_lat = round(sum(latencies) / len(latencies), 3) if latencies else 0.0
    p95_idx = int(0.95 * len(sorted_latencies))
    p95_lat = sorted_latencies[min(p95_idx, len(sorted_latencies) - 1)] if sorted_latencies else 0.0

    return {
        "recall@3": avg_r3,
        "recall@5": avg_r5,
        "citation_validity": avg_cv,
        "abstention_correctness": abst_corr,
        "by_type": by_type,
        "latency_seconds": {
            "mean": mean_lat,
            "p95": p95_lat,
        },
    }


def _print_summary_table(results: dict) -> None:
    print("\n" + "=" * 55)
    print("  RAHBAR EVALUATION METRIC SUMMARY")
    print("=" * 55)
    print(f"  recall@3:                {results.get('recall@3', 0.0):.4f}")
    print(f"  recall@5:                {results.get('recall@5', 0.0):.4f}")
    print(f"  citation validity:       {results.get('citation_validity', 0.0):.4f}")
    print(f"  abstention correctness:  {results.get('abstention_correctness', 0.0):.4f}")
    print("-" * 55)
    print("  recall@5 by Question Type:")
    for qtype, data in results.get("by_type", {}).items():
        print(f"    - {qtype:<12}: {data.get('recall@5', 0.0):.4f} ({data.get('count', 0)} questions)")
    lat = results.get("latency_seconds", {})
    print("-" * 55)
    print(f"  latency (mean / p95):    {lat.get('mean', 0.0):.3f}s / {lat.get('p95', 0.0):.3f}s")
    print("=" * 55)


def gate(results: dict, baseline: dict | None) -> list[str]:
    """Return one message per failed gate (section 5.4); an empty list means pass."""
    failures: list[str] = []

    # 1. Gate: recall@5 may fall at most 5 points below baseline
    current_r5 = results.get("recall@5", 0.0)
    if baseline and "recall@5" in baseline:
        base_r5 = baseline["recall@5"]
        if current_r5 < (base_r5 - MAX_RECALL5_DROP):
            failures.append(
                f"recall@5 dropped from baseline {base_r5:.4f} to {current_r5:.4f} "
                f"(max allowed drop: {MAX_RECALL5_DROP})"
            )

    # 2. Gate: citation validity must be at least 95%
    cit_val = results.get("citation_validity", 1.0)
    if cit_val < MIN_CITATION_VALIDITY:
        failures.append(
            f"citation validity {cit_val:.4f} is below minimum required {MIN_CITATION_VALIDITY}"
        )

    # 3. Gate: abstention correctness must be 100%
    abst_corr = results.get("abstention_correctness", 1.0)
    if abst_corr < REQUIRED_ABSTENTION:
        failures.append(
            f"abstention correctness {abst_corr:.4f} is below required {REQUIRED_ABSTENTION} (must decline 100% of out-of-scope)"
        )

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate RAHBAR against a golden set.")
    parser.add_argument("--api", required=True, help="base URL, e.g. http://192.168.49.2")
    parser.add_argument("--host", help="Host header, when your Ingress rule names a host")
    parser.add_argument("--golden", type=Path, default=HERE / "golden.yaml")
    parser.add_argument("--baseline", type=Path, default=HERE / "baseline.json")
    parser.add_argument("--out", type=Path, default=HERE / "results.json")
    parser.add_argument("--update-baseline", action="store_true",
                        help="write these results as the new baseline")
    args = parser.parse_args()

    questions = load_golden(args.golden)
    rows = []
    headers = {"Host": args.host} if args.host else {}
    with httpx.Client(timeout=120.0, headers=headers) as client:
        for q in questions:
            started = time.perf_counter()
            response = ask(client, args.api, q["question"])
            rows.append({
                "id": q["id"], "type": q.get("type", "ordinary"),
                "must_abstain": bool(q.get("must_abstain", False)),
                "relevant": q.get("relevant") or [],
                "expect": q.get("expect"),
                "response": response,
                "seconds": round(time.perf_counter() - started, 2),
            })
            print(f"  {q['id']:<5} {rows[-1]['seconds']:>6.2f}s  {q['question'][:60]}")

    results = summarise(rows)
    _print_summary_table(results)
    baseline = json.loads(args.baseline.read_text(encoding="utf-8")) if args.baseline.exists() else None
    failures = gate(results, baseline)

    results["golden"] = str(args.golden)
    results["questions"] = len(rows)
    args.out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nresults written to {args.out}")
    if args.update_baseline:
        args.baseline.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"baseline updated: {args.baseline}")

    if failures:
        print("\nGATE FAILED")
        for message in failures:
            print(f"  - {message}")
        sys.exit(1)
    print("\ngate passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
