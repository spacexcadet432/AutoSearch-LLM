"""Pure metric computation for the AutoSearch-LLM evaluation.

Kept free of I/O and network calls so the arithmetic can be verified
deterministically by ``evaluation/selftest.py``.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from typing import Any, Iterable, Sequence
from urllib.parse import urlparse

# Cases labelled "either" are excluded from strict accuracy; see dataset.json.
SCORABLE_ROUTES = ("search", "direct")


# --------------------------------------------------------------------------
# generic helpers
# --------------------------------------------------------------------------
def percentile(values: Sequence[float], pct: float) -> float | None:
    """Linear-interpolated percentile. Returns None for empty input."""
    data = sorted(float(v) for v in values)
    if not data:
        return None
    if len(data) == 1:
        return round(data[0], 1)
    rank = (len(data) - 1) * (pct / 100.0)
    low = int(rank)
    high = min(low + 1, len(data) - 1)
    frac = rank - low
    return round(data[low] + (data[high] - data[low]) * frac, 1)


def summarize_latency(values: Sequence[float]) -> dict[str, Any]:
    """Summary stats for a latency sample, with an explicit sample size."""
    data = [float(v) for v in values]
    if not data:
        return {"n": 0, "mean_ms": None, "median_ms": None, "p95_ms": None,
                "min_ms": None, "max_ms": None, "stdev_ms": None}
    return {
        "n": len(data),
        "mean_ms": round(statistics.fmean(data), 1),
        "median_ms": round(statistics.median(data), 1),
        "p95_ms": percentile(data, 95),
        "min_ms": round(min(data), 1),
        "max_ms": round(max(data), 1),
        "stdev_ms": round(statistics.stdev(data), 1) if len(data) > 1 else 0.0,
        # p95 on a small sample is indicative only, not a stable tail estimate.
        "p95_reliable": len(data) >= 20,
    }


def registrable_domain(url: str) -> str:
    """Coarse domain key for diversity counting (host minus a leading 'www.')."""
    try:
        host = (urlparse(url).netloc or "").lower()
    except Exception:
        return ""
    return host[4:] if host.startswith("www.") else host


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


# --------------------------------------------------------------------------
# router metrics
# --------------------------------------------------------------------------
def compute_router_metrics(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """
    Aggregate router results.

    Each record: {id, query, category, expected_route, predicted_route,
                  confidence, error, repeat_decisions}
    ``predicted_route`` is None when the call errored; such cases are counted
    as errors and never silently dropped or scored as correct.
    """
    records = list(records)

    errored = [r for r in records if r.get("error")]
    ok = [r for r in records if not r.get("error")]

    scorable = [r for r in ok if r["expected_route"] in SCORABLE_ROUTES]
    ambiguous = [r for r in ok if r["expected_route"] == "either"]

    correct = [r for r in scorable if r["predicted_route"] == r["expected_route"]]
    # Confusion matrix on the "search" class.
    tp = [r for r in scorable if r["expected_route"] == "search" and r["predicted_route"] == "search"]
    fn = [r for r in scorable if r["expected_route"] == "search" and r["predicted_route"] == "direct"]
    fp = [r for r in scorable if r["expected_route"] == "direct" and r["predicted_route"] == "search"]
    tn = [r for r in scorable if r["expected_route"] == "direct" and r["predicted_route"] == "direct"]

    precision = _rate(len(tp), len(tp) + len(fp))
    recall = _rate(len(tp), len(tp) + len(fn))
    f1 = (
        round(2 * precision * recall / (precision + recall), 4)
        if precision and recall
        else (0.0 if precision is not None and recall is not None else None)
    )

    # Per-category breakdown.
    by_category: dict[str, dict[str, Any]] = {}
    cats: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in ok:
        cats[r["category"]].append(r)
    for cat, rows in sorted(cats.items()):
        scored = [r for r in rows if r["expected_route"] in SCORABLE_ROUTES]
        hits = [r for r in scored if r["predicted_route"] == r["expected_route"]]
        by_category[cat] = {
            "n": len(rows),
            "n_scored": len(scored),
            "accuracy": _rate(len(hits), len(scored)),
            "search_rate": _rate(
                sum(1 for r in rows if r["predicted_route"] == "search"), len(rows)
            ),
            "failures": [
                {
                    "id": r["id"],
                    "query": r["query"],
                    "expected": r["expected_route"],
                    "predicted": r["predicted_route"],
                    "confidence": r.get("confidence"),
                }
                for r in scored
                if r["predicted_route"] != r["expected_route"]
            ],
        }

    # Determinism across repeated identical calls (temperature=0 should be stable).
    repeated = [r for r in ok if len(r.get("repeat_decisions") or []) > 1]
    unstable = [
        {"id": r["id"], "query": r["query"], "decisions": r["repeat_decisions"]}
        for r in repeated
        if len(set(r["repeat_decisions"])) > 1
    ]

    confidences = [r["confidence"] for r in ok if isinstance(r.get("confidence"), (int, float))]
    correct_ids = {r["id"] for r in correct}
    conf_correct = [
        r["confidence"] for r in scorable
        if r["id"] in correct_ids and isinstance(r.get("confidence"), (int, float))
    ]
    conf_wrong = [
        r["confidence"] for r in scorable
        if r["id"] not in correct_ids and isinstance(r.get("confidence"), (int, float))
    ]

    return {
        "n_cases": len(records),
        "n_errors": len(errored),
        "errors": [{"id": r["id"], "error": r["error"]} for r in errored],
        "n_scored": len(scorable),
        "n_excluded_ambiguous": len(ambiguous),
        "accuracy": _rate(len(correct), len(scorable)),
        "correct": len(correct),
        "confusion_matrix": {
            "correct_search": len(tp),
            "correct_direct": len(tn),
            "unnecessary_retrieval": len(fp),
            "missed_retrieval": len(fn),
        },
        "unnecessary_retrieval_rate": _rate(len(fp), len(fp) + len(tn)),
        "missed_retrieval_rate": _rate(len(fn), len(tp) + len(fn)),
        "search_precision": precision,
        "search_recall": recall,
        "search_f1": f1,
        "ambiguous_search_rate": _rate(
            sum(1 for r in ambiguous if r["predicted_route"] == "search"), len(ambiguous)
        ),
        "confidence": {
            "mean_all": round(statistics.fmean(confidences), 3) if confidences else None,
            "mean_on_correct": round(statistics.fmean(conf_correct), 3) if conf_correct else None,
            "mean_on_incorrect": round(statistics.fmean(conf_wrong), 3) if conf_wrong else None,
            "distinct_values": sorted({round(float(c), 3) for c in confidences}),
        },
        "determinism": {
            "n_repeated_cases": len(repeated),
            "n_unstable": len(unstable),
            "stability_rate": _rate(len(repeated) - len(unstable), len(repeated)),
            "unstable_cases": unstable,
        },
        "by_category": by_category,
        "all_failures": [
            {
                "id": r["id"],
                "category": r["category"],
                "query": r["query"],
                "expected": r["expected_route"],
                "predicted": r["predicted_route"],
                "confidence": r.get("confidence"),
            }
            for r in scorable
            if r["predicted_route"] != r["expected_route"]
        ],
    }


# --------------------------------------------------------------------------
# retrieval metrics
# --------------------------------------------------------------------------
def compute_retrieval_metrics(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """
    Aggregate retrieval results.

    Each record: {id, query, keywords, sources[list of {url, chunk_text}],
                  stats{...}, latency_ms, error}
    """
    records = list(records)
    errored = [r for r in records if r.get("error")]
    ok = [r for r in records if not r.get("error")]

    non_empty = [r for r in ok if r.get("sources")]
    empty = [r for r in ok if not r.get("sources")]

    failure_reasons = Counter(
        (r.get("stats") or {}).get("failure_reason") or "unknown" for r in empty
    )
    page_outcomes: Counter[str] = Counter()
    for r in ok:
        for outcome in ((r.get("stats") or {}).get("page_outcomes") or []):
            page_outcomes[outcome.get("outcome", "unknown")] += 1

    # Topical keyword hit rate (a weak relevance proxy - see README limitations).
    query_level_hits = 0
    chunk_hits = 0
    chunk_total = 0
    rank1_hits = 0
    rank1_total = 0
    per_query: list[dict[str, Any]] = []

    domain_counts: list[int] = []
    source_counts: list[int] = []

    for r in non_empty:
        keywords = [k.lower() for k in (r.get("keywords") or [])]
        sources = r["sources"]
        source_counts.append(len({s.get("url") for s in sources if s.get("url")}))
        domain_counts.append(
            len({registrable_domain(s.get("url") or "") for s in sources if s.get("url")})
        )

        hits = []
        for idx, s in enumerate(sources):
            haystack = " ".join(
                str(s.get(field) or "") for field in ("chunk_text", "title", "snippet")
            ).lower()
            hit = any(k in haystack for k in keywords) if keywords else None
            hits.append(hit)
            if hit is not None:
                chunk_total += 1
                chunk_hits += int(hit)
                if idx == 0:
                    rank1_total += 1
                    rank1_hits += int(hit)
        if keywords and any(hits):
            query_level_hits += 1

        per_query.append({
            "id": r["id"],
            "query": r["query"],
            "n_sources": len(sources),
            "n_domains": domain_counts[-1],
            "on_topic_chunks": sum(1 for h in hits if h),
            "rank1_on_topic": hits[0] if hits else None,
            "latency_ms": r.get("latency_ms"),
            "urls": [s.get("url") for s in sources],
        })

    latencies = [r["latency_ms"] for r in ok if isinstance(r.get("latency_ms"), (int, float))]
    stage = {}
    for key in ("discover_ms", "fetch_ms", "rank_ms"):
        vals = [
            (r.get("stats") or {}).get(key)
            for r in ok
            if isinstance((r.get("stats") or {}).get(key), (int, float))
        ]
        stage[key] = summarize_latency(vals)

    return {
        "n_queries": len(records),
        "n_errors": len(errored),
        "errors": [{"id": r["id"], "error": r["error"]} for r in errored],
        "retrieval_success_rate": _rate(len(non_empty), len(ok)),
        "n_returned_sources": len(non_empty),
        "n_returned_nothing": len(empty),
        "failure_reasons": dict(failure_reasons),
        "page_fetch_outcomes": dict(page_outcomes),
        "sources_per_query": summarize_count(source_counts),
        "domains_per_query": summarize_count(domain_counts),
        "single_domain_queries": sum(1 for d in domain_counts if d <= 1),
        "topical_keyword_proxy": {
            "query_level_hit_rate": _rate(query_level_hits, len(non_empty)),
            "chunk_level_hit_rate": _rate(chunk_hits, chunk_total),
            "rank1_hit_rate": _rate(rank1_hits, rank1_total),
            "n_chunks_scored": chunk_total,
            "note": "Weak proxy: keyword presence, NOT a human relevance judgement.",
        },
        "latency": summarize_latency(latencies),
        "stage_latency": stage,
        "per_query": per_query,
    }


def summarize_count(values: Sequence[int]) -> dict[str, Any]:
    """Mean/median/min/max for small integer count samples."""
    data = list(values)
    if not data:
        return {"n": 0, "mean": None, "median": None, "min": None, "max": None}
    return {
        "n": len(data),
        "mean": round(statistics.fmean(data), 2),
        "median": statistics.median(data),
        "min": min(data),
        "max": max(data),
    }


# --------------------------------------------------------------------------
# latency metrics
# --------------------------------------------------------------------------
STAGE_KEYS = ("routing_ms", "retrieval_ms", "generation_ms", "total_ms")


def compute_latency_metrics(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """
    Aggregate end-to-end pipeline runs.

    Each record: {id, query, expected_route, repeat, trace{...}, error}
    Retrieval sub-stages are reported only over runs that actually retrieved.
    """
    records = list(records)
    errored = [r for r in records if r.get("error")]
    ok = [r for r in records if not r.get("error")]

    def traces(rows: Iterable[dict[str, Any]], key: str) -> list[float]:
        out = []
        for r in rows:
            v = (r.get("trace") or {}).get(key)
            if isinstance(v, (int, float)):
                out.append(float(v))
        return out

    searched = [r for r in ok if (r.get("trace") or {}).get("used_search")]
    direct = [r for r in ok if not (r.get("trace") or {}).get("used_search")]

    overall = {k: summarize_latency(traces(ok, k)) for k in STAGE_KEYS}
    # Retrieval sub-stages live inside trace["retrieval"].
    sub: dict[str, Any] = {}
    for key in ("discover_ms", "fetch_ms", "rank_ms"):
        vals = []
        for r in searched:
            v = ((r.get("trace") or {}).get("retrieval") or {}).get(key)
            if isinstance(v, (int, float)):
                vals.append(float(v))
        sub[key] = summarize_latency(vals)

    return {
        "n_runs": len(records),
        "n_errors": len(errored),
        "errors": [{"id": r["id"], "error": r["error"]} for r in errored],
        "n_search_runs": len(searched),
        "n_direct_runs": len(direct),
        "overall": overall,
        "search_path": {k: summarize_latency(traces(searched, k)) for k in STAGE_KEYS},
        "direct_path": {
            k: summarize_latency(traces(direct, k))
            for k in ("routing_ms", "generation_ms", "total_ms")
        },
        "retrieval_substages_search_path": sub,
        "generation_modes": dict(
            Counter((r.get("trace") or {}).get("generation_mode") or "unknown" for r in ok)
        ),
    }
