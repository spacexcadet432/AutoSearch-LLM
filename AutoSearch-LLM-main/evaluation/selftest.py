"""Deterministic verification of the evaluation metric arithmetic.

No network, no API keys, no LLM. Feeds hand-built records with known-correct
expected values into the metric functions and asserts the output.

This validates the MEASUREMENT CODE only. It produces no baseline numbers and
must never be presented as evaluation results.

Run:  python -m evaluation.selftest
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evaluation.metrics import (  # noqa: E402
    compute_latency_metrics,
    compute_retrieval_metrics,
    compute_router_metrics,
    percentile,
    registrable_domain,
    summarize_latency,
)

CHECKS: list[tuple[str, object, object]] = []


def check(label: str, actual: object, expected: object) -> None:
    CHECKS.append((label, actual, expected))


# --------------------------------------------------------------------------
# percentile / latency summary
# --------------------------------------------------------------------------
check("percentile empty", percentile([], 95), None)
check("percentile single", percentile([7.0], 95), 7.0)
# 1..10, rank = 9 * 0.95 = 8.55 -> data[8] + 0.55*(data[9]-data[8]) = 9 + 0.55 = 9.55.
# round(9.55, 1) is 9.5 because 9.55 is not exactly representable in binary floats.
check("percentile interpolated", percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 95), 9.5)
# Clean interpolation check with an exactly-representable result.
check("percentile interpolates midpoint", percentile([0, 10], 50), 5.0)
check("percentile interpolates quarter", percentile([0, 100], 25), 25.0)
check("percentile median", percentile([1, 2, 3, 4], 50), 2.5)

summary = summarize_latency([100.0, 200.0, 300.0])
check("latency n", summary["n"], 3)
check("latency mean", summary["mean_ms"], 200.0)
check("latency median", summary["median_ms"], 200.0)
check("latency p95 small-sample flag", summary["p95_reliable"], False)
check("latency empty", summarize_latency([])["mean_ms"], None)
check("p95 reliable at n=20", summarize_latency([1.0] * 20)["p95_reliable"], True)

check("domain strips www", registrable_domain("https://www.Example.com/a/b"), "example.com")
check("domain bare", registrable_domain("https://news.bbc.co.uk/x"), "news.bbc.co.uk")

# --------------------------------------------------------------------------
# router metrics
# --------------------------------------------------------------------------
# 8 usable cases: 3 search-expected, 3 direct-expected, 1 ambiguous, 1 errored.
router_records = [
    # expected search, predicted search  -> TP
    {"id": "a1", "query": "q", "category": "time_sensitive_explicit",
     "expected_route": "search", "predicted_route": "search", "confidence": 0.9,
     "repeat_decisions": ["search", "search"], "error": None},
    {"id": "a2", "query": "q", "category": "time_sensitive_explicit",
     "expected_route": "search", "predicted_route": "search", "confidence": 0.8,
     "repeat_decisions": ["search", "search"], "error": None},
    # expected search, predicted direct -> FN (missed retrieval)
    {"id": "a3", "query": "q", "category": "routing_traps",
     "expected_route": "search", "predicted_route": "direct", "confidence": 0.6,
     "repeat_decisions": ["direct", "search"], "error": None},
    # expected direct, predicted direct -> TN
    {"id": "b1", "query": "q", "category": "timeless_factual",
     "expected_route": "direct", "predicted_route": "direct", "confidence": 0.95,
     "repeat_decisions": ["direct", "direct"], "error": None},
    {"id": "b2", "query": "q", "category": "timeless_factual",
     "expected_route": "direct", "predicted_route": "direct", "confidence": 0.95,
     "repeat_decisions": ["direct", "direct"], "error": None},
    # expected direct, predicted search -> FP (unnecessary retrieval)
    {"id": "b3", "query": "q", "category": "routing_traps",
     "expected_route": "direct", "predicted_route": "search", "confidence": 0.7,
     "repeat_decisions": ["search", "search"], "error": None},
    # ambiguous -> excluded from accuracy
    {"id": "c1", "query": "q", "category": "ambiguous_borderline",
     "expected_route": "either", "predicted_route": "search", "confidence": 0.5,
     "repeat_decisions": ["search", "search"], "error": None},
    # errored -> counted as error, never scored
    {"id": "d1", "query": "q", "category": "timeless_factual",
     "expected_route": "direct", "predicted_route": None, "confidence": None,
     "repeat_decisions": [], "error": "APIError: boom"},
]
rm = compute_router_metrics(router_records)

check("router n_cases", rm["n_cases"], 8)
check("router n_errors", rm["n_errors"], 1)
check("router n_scored (excludes ambiguous + errored)", rm["n_scored"], 6)
check("router n_excluded_ambiguous", rm["n_excluded_ambiguous"], 1)
check("router correct", rm["correct"], 4)                     # a1 a2 b1 b2
check("router accuracy", rm["accuracy"], round(4 / 6, 4))
check("router TP", rm["confusion_matrix"]["correct_search"], 2)
check("router TN", rm["confusion_matrix"]["correct_direct"], 2)
check("router FP unnecessary", rm["confusion_matrix"]["unnecessary_retrieval"], 1)
check("router FN missed", rm["confusion_matrix"]["missed_retrieval"], 1)
check("router unnecessary rate = 1/(1+2)", rm["unnecessary_retrieval_rate"], round(1 / 3, 4))
check("router missed rate = 1/(2+1)", rm["missed_retrieval_rate"], round(1 / 3, 4))
check("router precision = 2/(2+1)", rm["search_precision"], round(2 / 3, 4))
check("router recall = 2/(2+1)", rm["search_recall"], round(2 / 3, 4))
check("router f1", rm["search_f1"], round(2 / 3, 4))
check("router ambiguous search rate", rm["ambiguous_search_rate"], 1.0)
check("router failure count", len(rm["all_failures"]), 2)
check("router unstable count (a3 flipped)", rm["determinism"]["n_unstable"], 1)
check("router repeated cases", rm["determinism"]["n_repeated_cases"], 7)
check("router stability 6/7", rm["determinism"]["stability_rate"], round(6 / 7, 4))
check("router category accuracy timeless (b1,b2 ok; d1 errored)",
      rm["by_category"]["timeless_factual"]["accuracy"], 1.0)
check("router traps accuracy 0/2", rm["by_category"]["routing_traps"]["accuracy"], 0.0)
check("router error id surfaced", rm["errors"][0]["id"], "d1")

# An all-ambiguous set must not fabricate an accuracy of 0 or 1.
rm_empty = compute_router_metrics([
    {"id": "x", "query": "q", "category": "ambiguous_borderline", "expected_route": "either",
     "predicted_route": "direct", "confidence": 0.5, "repeat_decisions": ["direct"], "error": None},
])
check("router accuracy is None when nothing scorable", rm_empty["accuracy"], None)

# --------------------------------------------------------------------------
# retrieval metrics
# --------------------------------------------------------------------------
retrieval_records = [
    {  # 3 sources, 2 domains, rank-1 on topic, 2/3 chunks on topic
        "id": "r1", "query": "q", "category": "retrieval_useful",
        "keywords": ["bitcoin"],
        "sources": [
            {"url": "https://www.a.com/1", "title": "Bitcoin price", "snippet": "",
             "chunk_text": "bitcoin is trading at"},
            {"url": "https://a.com/2", "title": "", "snippet": "",
             "chunk_text": "unrelated content here"},
            {"url": "https://b.com/1", "title": "", "snippet": "",
             "chunk_text": "BITCOIN hit a high"},
        ],
        "stats": {"failure_reason": None, "discover_ms": 100.0, "fetch_ms": 500.0,
                  "rank_ms": 2.0,
                  "page_outcomes": [{"outcome": "extracted"}, {"outcome": "fetch_error"}]},
        "latency_ms": 620.0, "error": None,
    },
    {  # returned nothing
        "id": "r2", "query": "q", "category": "retrieval_useful",
        "keywords": ["nvidia"], "sources": [],
        "stats": {"failure_reason": "no_extractable_content", "discover_ms": 90.0,
                  "fetch_ms": 3400.0, "page_outcomes": [{"outcome": "thin_content"}]},
        "latency_ms": 3500.0, "error": None,
    },
    {  # errored
        "id": "r3", "query": "q", "category": "retrieval_useful", "keywords": ["x"],
        "sources": [], "stats": {}, "latency_ms": None, "error": "RuntimeError: nope",
    },
]
qm = compute_retrieval_metrics(retrieval_records)

check("retrieval n_queries", qm["n_queries"], 3)
check("retrieval n_errors", qm["n_errors"], 1)
check("retrieval success rate 1/2 (errored excluded)", qm["retrieval_success_rate"], 0.5)
check("retrieval returned nothing", qm["n_returned_nothing"], 1)
check("retrieval failure reason recorded",
      qm["failure_reasons"]["no_extractable_content"], 1)
check("retrieval page outcomes aggregated", qm["page_fetch_outcomes"]["fetch_error"], 1)
check("retrieval domains per query mean", qm["domains_per_query"]["mean"], 2.0)
check("retrieval sources per query mean", qm["sources_per_query"]["mean"], 3.0)
check("retrieval query-level hit rate 1/1", qm["topical_keyword_proxy"]["query_level_hit_rate"], 1.0)
check("retrieval chunk-level hit rate 2/3",
      qm["topical_keyword_proxy"]["chunk_level_hit_rate"], round(2 / 3, 4))
check("retrieval rank1 hit rate 1/1", qm["topical_keyword_proxy"]["rank1_hit_rate"], 1.0)
check("retrieval latency mean over ok runs", qm["latency"]["mean_ms"], 2060.0)
check("retrieval discover stage n", qm["stage_latency"]["discover_ms"]["n"], 2)

# --------------------------------------------------------------------------
# latency metrics
# --------------------------------------------------------------------------
latency_records = [
    {"id": "l1", "query": "q", "category": "c", "expected_route": "search", "repeat": 1,
     "trace": {"used_search": True, "routing_ms": 400.0, "retrieval_ms": 1000.0,
               "generation_ms": 1600.0, "total_ms": 3000.0, "generation_mode": "grounded",
               "retrieval": {"discover_ms": 200.0, "fetch_ms": 780.0, "rank_ms": 1.0}},
     "error": None},
    {"id": "l1", "query": "q", "category": "c", "expected_route": "search", "repeat": 2,
     "trace": {"used_search": True, "routing_ms": 600.0, "retrieval_ms": 2000.0,
               "generation_ms": 2400.0, "total_ms": 5000.0, "generation_mode": "grounded",
               "retrieval": {"discover_ms": 300.0, "fetch_ms": 1690.0, "rank_ms": 2.0}},
     "error": None},
    {"id": "l2", "query": "q", "category": "c", "expected_route": "direct", "repeat": 1,
     "trace": {"used_search": False, "routing_ms": 500.0, "generation_ms": 700.0,
               "total_ms": 1200.0, "generation_mode": "direct"},
     "error": None},
    {"id": "l3", "query": "q", "category": "c", "expected_route": "direct", "repeat": 1,
     "trace": {}, "error": "TimeoutError: slow"},
]
lm = compute_latency_metrics(latency_records)

check("latency n_runs", lm["n_runs"], 4)
check("latency n_errors", lm["n_errors"], 1)
check("latency search runs", lm["n_search_runs"], 2)
check("latency direct runs", lm["n_direct_runs"], 1)
check("latency search total mean", lm["search_path"]["total_ms"]["mean_ms"], 4000.0)
check("latency search routing mean", lm["search_path"]["routing_ms"]["mean_ms"], 500.0)
check("latency direct total mean", lm["direct_path"]["total_ms"]["mean_ms"], 1200.0)
check("latency substage fetch mean", lm["retrieval_substages_search_path"]["fetch_ms"]["mean_ms"], 1235.0)
check("latency substage only counts search runs",
      lm["retrieval_substages_search_path"]["discover_ms"]["n"], 2)
check("latency generation modes", lm["generation_modes"]["grounded"], 2)
check("latency overall mean over 3 ok runs",
      lm["overall"]["total_ms"]["mean_ms"], round((3000 + 5000 + 1200) / 3, 1))


def main() -> int:
    failures = [(l, a, e) for l, a, e in CHECKS if a != e]
    for label, actual, expected in CHECKS:
        status = "PASS" if actual == expected else "FAIL"
        line = f"[{status}] {label}"
        if status == "FAIL":
            line += f"\n         expected={expected!r}\n         actual  ={actual!r}"
        print(line)
    print(f"\n{len(CHECKS) - len(failures)}/{len(CHECKS)} metric checks passed")
    if failures:
        print("METRIC SELF-TEST FAILED", file=sys.stderr)
        return 1
    print("Metric arithmetic verified. (This is NOT a baseline result.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
