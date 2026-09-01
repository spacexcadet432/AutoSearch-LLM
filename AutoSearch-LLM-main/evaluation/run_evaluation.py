"""AutoSearch-LLM Phase 1 evaluation harness.

Runs the *existing* routing / retrieval / generation implementation against a
version-controlled dataset and writes reproducible metrics to evaluation/results/.

Usage:
    python -m evaluation.run_evaluation                     # all stages
    python -m evaluation.run_evaluation --stages router     # router only
    python -m evaluation.run_evaluation --verify-only       # credential preflight

Design notes:
  * Nothing is mocked. Every number comes from a real call to the real pipeline.
  * Failed cases are recorded as errors and reported; they are never dropped
    and never counted as correct.
  * API keys are read from the environment / .env only. They are never printed,
    logged or written to results files.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Make the repository root importable when run as a script.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

from evaluation.metrics import (  # noqa: E402
    compute_latency_metrics,
    compute_retrieval_metrics,
    compute_router_metrics,
)

load_dotenv(REPO_ROOT / ".env")

AWS_REGION = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"

# Known OpenAI-compatible providers. The application itself stays
# provider-agnostic; this only selects a base URL.
#
# Note on Bedrock: its OpenAI-compatible endpoint serves ONLY the
# `openai.gpt-oss-*` models. Every other Bedrock model (Nova, Claude, Llama)
# 404s there and is reachable only via the native Converse API, which this
# harness does not use.
PROVIDERS: dict[str, dict[str, str]] = {
    "openai": {
        "base_url": "",
        "key_envs": "OPENAI_API_KEY",
        "default_model": "gpt-4o-mini",
    },
    "bedrock": {
        "base_url": f"https://bedrock-runtime.{AWS_REGION}.amazonaws.com/openai/v1",
        "key_envs": "AWS_BEARER_TOKEN_BEDROCK",
        "default_model": "openai.gpt-oss-120b-1:0",
    },
}

DEFAULT_DATASET = REPO_ROOT / "evaluation" / "dataset.json"
DEFAULT_OUT_DIR = REPO_ROOT / "evaluation" / "results"


class EvaluationError(RuntimeError):
    """Fatal harness error: report exactly and stop, never substitute."""


# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------
def resolve_llm_key(provider: str) -> str:
    names = [n for n in PROVIDERS[provider]["key_envs"].split(",") if n]
    for name in names:
        value = (os.getenv(name) or "").strip()
        if value:
            return value
    raise EvaluationError(
        f"No API key found for provider '{provider}'. "
        f"Set one of: {', '.join(names)} (in .env or the environment)."
    )


def configure_provider(provider: str, model: str | None) -> None:
    """Point the backend at the chosen OpenAI-compatible endpoint."""
    base_url = PROVIDERS[provider]["base_url"]
    if base_url:
        os.environ["AUTOSEARCH_LLM_BASE_URL"] = base_url
    else:
        os.environ.pop("AUTOSEARCH_LLM_BASE_URL", None)
    chosen = model or PROVIDERS[provider].get("default_model")
    if chosen:
        os.environ["AUTOSEARCH_LLM_MODEL"] = chosen


async def _probe_llm(provider: str, llm_key: str, info: dict[str, Any]) -> None:
    """Minimal live chat completion. Raises with the exact provider failure."""
    from backend.services.llm import build_client, chat_model

    try:
        client = build_client(llm_key)
        started = time.perf_counter()
        resp = await client.chat.completions.create(
            model=chat_model(),
            messages=[{"role": "user", "content": "Reply with the single word: OK"}],
            temperature=0,
            max_tokens=8,
        )
        info["llm_ok"] = True
        info["llm_probe_ms"] = round((time.perf_counter() - started) * 1000, 1)
        info["llm_probe_reply"] = (resp.choices[0].message.content or "").strip()[:40]
    except Exception as error:
        raise EvaluationError(
            f"LLM preflight FAILED for provider '{provider}' "
            f"(model={chat_model()}): {type(error).__name__}: {error}"
        ) from error


async def preflight(
    provider: str,
    llm_key: str,
    serper_key: str,
    need_serper: bool,
    need_llm: bool = True,
) -> dict[str, Any]:
    """Live check of the credentials the selected stages actually require."""
    import httpx

    from backend.services.llm import provider_label

    info: dict[str, Any] = {"provider": provider, "llm_endpoint": provider_label()}

    # The retrieval stage makes no LLM calls, so it needs no LLM credential.
    if need_llm:
        await _probe_llm(provider, llm_key, info)
    else:
        info["llm_ok"] = None

    # --- Serper ---
    if need_serper:
        try:
            async with httpx.AsyncClient(timeout=20.0) as http:
                started = time.perf_counter()
                r = await http.post(
                    "https://google.serper.dev/search",
                    json={"q": "connectivity probe", "num": 1},
                    headers={"X-API-KEY": serper_key, "Content-Type": "application/json"},
                )
            if r.status_code != 200:
                raise EvaluationError(
                    f"Serper preflight FAILED: HTTP {r.status_code}: {r.text[:200]}"
                )
            info["serper_ok"] = True
            info["serper_probe_ms"] = round((time.perf_counter() - started) * 1000, 1)
            info["serper_organic_results"] = len(r.json().get("organic", []) or [])
        except EvaluationError:
            raise
        except Exception as error:
            raise EvaluationError(
                f"Serper preflight FAILED: {type(error).__name__}: {error}"
            ) from error
    else:
        info["serper_ok"] = None

    return info


# --------------------------------------------------------------------------
# stage 1: router
# --------------------------------------------------------------------------
async def run_router_stage(
    cases: list[dict[str, Any]], llm_key: str, repeats: int, concurrency: int
) -> list[dict[str, Any]]:
    from backend.services.routing import classify_temporal_need

    sem = asyncio.Semaphore(concurrency)

    async def one(case: dict[str, Any]) -> dict[str, Any]:
        decisions: list[str] = []
        confidences: list[float] = []
        latencies: list[float] = []
        error: str | None = None

        async with sem:
            for _ in range(repeats):
                try:
                    started = time.perf_counter()
                    needs_search, confidence = await classify_temporal_need(
                        case["query"], llm_key
                    )
                    latencies.append(round((time.perf_counter() - started) * 1000, 1))
                    decisions.append("search" if needs_search else "direct")
                    confidences.append(float(confidence))
                except Exception as exc:  # recorded, never silently ignored
                    error = f"{type(exc).__name__}: {exc}"
                    break

        predicted = None
        if decisions:
            # Majority vote across repeats; ties resolve to the first decision.
            counts = Counter(decisions)
            top = counts.most_common()
            predicted = (
                top[0][0]
                if len(top) == 1 or top[0][1] > top[1][1]
                else decisions[0]
            )

        return {
            "id": case["id"],
            "query": case["query"],
            "category": case["category"],
            "expected_route": case["expected_route"],
            "predicted_route": predicted,
            "confidence": round(sum(confidences) / len(confidences), 3) if confidences else None,
            "repeat_decisions": decisions,
            "repeat_confidences": confidences,
            "latency_ms": latencies,
            "error": error,
        }

    print(f"[router] {len(cases)} queries x {repeats} repeats "
          f"({len(cases) * repeats} calls, concurrency={concurrency})")
    return await asyncio.gather(*(one(c) for c in cases))


# --------------------------------------------------------------------------
# stage 2: retrieval
# --------------------------------------------------------------------------
async def run_retrieval_stage(
    cases: list[dict[str, Any]], serper_key: str, concurrency: int
) -> list[dict[str, Any]]:
    from backend.services.search import retrieve_sources

    sem = asyncio.Semaphore(concurrency)

    async def one(case: dict[str, Any]) -> dict[str, Any]:
        stats: dict[str, Any] = {}
        error: str | None = None
        sources: list[dict[str, Any]] = []
        elapsed = None
        async with sem:
            try:
                started = time.perf_counter()
                # Same parameters the production pipeline uses.
                sources = await retrieve_sources(
                    case["query"],
                    serper_api_key=serper_key,
                    max_pages=3,
                    top_m=3,
                    deadline_ms=3500,
                    stats=stats,
                )
                elapsed = round((time.perf_counter() - started) * 1000, 1)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"

        return {
            "id": case["id"],
            "query": case["query"],
            "category": case["category"],
            "keywords": case.get("retrieval_keywords") or [],
            "sources": [
                {
                    "url": s.get("url"),
                    "title": s.get("title"),
                    "snippet": s.get("snippet"),
                    "chunk_index": s.get("chunk_index"),
                    "chunk_text": (s.get("chunk_text") or "")[:600],
                }
                for s in sources
            ],
            "stats": stats,
            "latency_ms": elapsed,
            "error": error,
        }

    print(f"[retrieval] {len(cases)} queries (concurrency={concurrency})")
    return await asyncio.gather(*(one(c) for c in cases))


# --------------------------------------------------------------------------
# stage 3: end-to-end latency
# --------------------------------------------------------------------------
def select_latency_cases(cases: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    """Deterministic, path-balanced subset: half search-path, half direct-path."""
    search = [c for c in cases if c["expected_route"] == "search"]
    direct = [c for c in cases if c["expected_route"] == "direct"]
    half = max(1, n // 2)
    return search[:half] + direct[: n - half]


async def run_latency_stage(
    cases: list[dict[str, Any]], llm_key: str, serper_key: str, repeats: int
) -> list[dict[str, Any]]:
    """Run the full pipeline SEQUENTIALLY - concurrency would corrupt stage timings."""
    from backend.services.pipeline import run_query_pipeline

    records: list[dict[str, Any]] = []
    total = len(cases) * repeats
    print(f"[latency] {len(cases)} queries x {repeats} repeats = {total} sequential runs")

    for repeat in range(1, repeats + 1):
        for case in cases:
            trace: dict[str, Any] = {}
            error: str | None = None
            answer_len = None
            try:
                result = await run_query_pipeline(
                    case["query"],
                    openai_api_key=llm_key,
                    serper_api_key=serper_key,
                    trace=trace,
                )
                answer_len = len(result.get("answer") or "")
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"

            records.append({
                "id": case["id"],
                "query": case["query"],
                "category": case["category"],
                "expected_route": case["expected_route"],
                "repeat": repeat,
                "trace": trace,
                "answer_chars": answer_len,
                "error": error,
            })
            print(f"  run {len(records)}/{total} {case['id']}"
                  f" {'ERROR' if error else str(trace.get('total_ms')) + 'ms'}")
    return records


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------
def render_markdown(payload: dict[str, Any]) -> str:
    meta = payload["metadata"]
    lines: list[str] = [
        "# AutoSearch-LLM - Phase 1 Baseline Results",
        "",
        "> Generated by `python -m evaluation.run_evaluation`. All numbers are measured, not estimated.",
        "",
        "## Run metadata",
        "",
        f"- **Timestamp (UTC):** {meta['timestamp_utc']}",
        f"- **LLM endpoint / model:** `{meta['llm_endpoint']}`",
        f"- **Dataset:** v{meta['dataset_version']} ({meta['dataset_cases']} cases)",
        f"- **Stages run:** {', '.join(meta['stages'])}",
        f"- **Router repeats/query:** {meta['router_repeats']}",
        f"- **Python:** {meta['python']} on {meta['platform']}",
        "",
    ]

    router = payload.get("router_metrics")
    if router:
        cm = router["confusion_matrix"]
        lines += [
            "## 1. Routing",
            "",
            f"- **Accuracy: {_pct(router['accuracy'])}** "
            f"({router['correct']}/{router['n_scored']} decisively-labelled cases)",
            f"- Excluded as ambiguous (`either`): {router['n_excluded_ambiguous']}",
            f"- Errored calls: {router['n_errors']}",
            "",
            "| Outcome | Count |",
            "|---|---|",
            f"| Correct `search` (true positive) | {cm['correct_search']} |",
            f"| Correct `direct` (true negative) | {cm['correct_direct']} |",
            f"| **Unnecessary retrieval** (searched when it should not) | {cm['unnecessary_retrieval']} |",
            f"| **Missed retrieval** (answered directly when it should have searched) | {cm['missed_retrieval']} |",
            "",
            f"- Unnecessary-retrieval rate: **{_pct(router['unnecessary_retrieval_rate'])}** of `direct` cases",
            f"- Missed-retrieval rate: **{_pct(router['missed_retrieval_rate'])}** of `search` cases",
            f"- `search` precision / recall / F1: "
            f"{_pct(router['search_precision'])} / {_pct(router['search_recall'])} / {_pct(router['search_f1'])}",
            f"- Ambiguous-case search rate (bias indicator): {_pct(router['ambiguous_search_rate'])}",
            "",
            "### Per-category",
            "",
            "| Category | Scored | Accuracy | Search rate |",
            "|---|---|---|---|",
        ]
        for cat, row in router["by_category"].items():
            lines.append(
                f"| {cat} | {row['n_scored']} | {_pct(row['accuracy'])} | {_pct(row['search_rate'])} |"
            )
        det = router["determinism"]
        lines += [
            "",
            f"**Determinism:** {det['n_unstable']}/{det['n_repeated_cases']} queries returned "
            f"different decisions across identical repeated calls "
            f"(stability {_pct(det['stability_rate'])}).",
            "",
        ]
        if router["all_failures"]:
            lines += ["### Routing failures", "",
                      "| ID | Category | Query | Expected | Predicted | Conf |", "|---|---|---|---|---|---|"]
            for f in router["all_failures"]:
                lines.append(
                    f"| {f['id']} | {f['category']} | {f['query'][:70]} | "
                    f"{f['expected']} | {f['predicted']} | {f['confidence']} |"
                )
            lines.append("")

    retrieval = payload.get("retrieval_metrics")
    if retrieval:
        kw = retrieval["topical_keyword_proxy"]
        lines += [
            "## 2. Retrieval",
            "",
            f"- Queries evaluated: {retrieval['n_queries']} (errors: {retrieval['n_errors']})",
            f"- **Retrieval success rate (returned >=1 source): {_pct(retrieval['retrieval_success_rate'])}**",
            f"- Returned nothing: {retrieval['n_returned_nothing']}",
            f"- Sources per query: mean {retrieval['sources_per_query']['mean']}, "
            f"min {retrieval['sources_per_query']['min']}, max {retrieval['sources_per_query']['max']}",
            f"- Distinct domains per query: mean {retrieval['domains_per_query']['mean']} "
            f"({retrieval['single_domain_queries']} queries returned a single domain)",
            "",
            "**Topical keyword proxy** (weak relevance signal - keyword presence, not human judgement):",
            "",
            f"- Query-level hit rate: {_pct(kw['query_level_hit_rate'])}",
            f"- Chunk-level hit rate: {_pct(kw['chunk_level_hit_rate'])} over {kw['n_chunks_scored']} chunks",
            f"- Rank-1 hit rate: {_pct(kw['rank1_hit_rate'])} "
            "(compare with chunk-level to judge whether ranking helps)",
            "",
            f"- Failure reasons: `{retrieval['failure_reasons'] or 'none'}`",
            f"- Page fetch outcomes: `{retrieval['page_fetch_outcomes']}`",
            "",
            "| Retrieval stage | n | mean | median | p95 |",
            "|---|---|---|---|---|",
        ]
        lines.append(_lat_row("end-to-end retrieval", retrieval["latency"]))
        for key, label in (("discover_ms", "serper discovery"),
                           ("fetch_ms", "fetch + extract"),
                           ("rank_ms", "ranking")):
            lines.append(_lat_row(label, retrieval["stage_latency"][key]))
        lines.append("")

    latency = payload.get("latency_metrics")
    if latency:
        lines += [
            "## 3. End-to-end latency",
            "",
            f"- Sequential runs: {latency['n_runs']} "
            f"({latency['n_search_runs']} search-path, {latency['n_direct_runs']} direct-path, "
            f"{latency['n_errors']} errors)",
            f"- Generation modes observed: `{latency['generation_modes']}`",
            "",
            "### Search path (routing -> retrieval -> grounded generation)",
            "",
            "| Stage | n | mean | median | p95 |",
            "|---|---|---|---|---|",
        ]
        for key in ("routing_ms", "retrieval_ms", "generation_ms", "total_ms"):
            lines.append(_lat_row(key.replace("_ms", ""), latency["search_path"][key]))
        lines += ["", "Retrieval sub-stages (search path only):", "",
                  "| Sub-stage | n | mean | median | p95 |", "|---|---|---|---|---|"]
        for key in ("discover_ms", "fetch_ms", "rank_ms"):
            lines.append(_lat_row(key.replace("_ms", ""),
                                  latency["retrieval_substages_search_path"][key]))
        lines += ["", "### Direct path (routing -> direct generation)", "",
                  "| Stage | n | mean | median | p95 |", "|---|---|---|---|---|"]
        for key in ("routing_ms", "generation_ms", "total_ms"):
            lines.append(_lat_row(key.replace("_ms", ""), latency["direct_path"][key]))
        lines.append("")

    warnings = payload.get("warnings") or []
    if warnings:
        lines += ["## Warnings", ""] + [f"- {w}" for w in warnings] + [""]

    lines += [
        "## Reading these numbers",
        "",
        "- p95 values flagged `p95_reliable: false` in `results.json` come from fewer than "
        "20 samples and are indicative only.",
        "- Latency depends on live third-party APIs (the LLM provider and Serper) and on "
        "network conditions; absolute values are not comparable across machines or runs.",
        "- The keyword proxy is not precision/recall. See `evaluation/README.md`.",
        "",
    ]
    return "\n".join(lines)


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _lat_row(label: str, s: dict[str, Any]) -> str:
    if not s or not s.get("n"):
        return f"| {label} | 0 | n/a | n/a | n/a |"
    star = "" if s.get("p95_reliable") else "*"
    return (f"| {label} | {s['n']} | {s['mean_ms']} ms | {s['median_ms']} ms | "
            f"{s['p95_ms']} ms{star} |")


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
async def main_async(args: argparse.Namespace) -> int:
    dataset = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    cases = dataset["cases"]

    stages = [s.strip() for s in args.stages.split(",") if s.strip()]
    for stage in stages:
        if stage not in ("router", "retrieval", "latency"):
            raise EvaluationError(f"Unknown stage '{stage}'")

    provider = args.provider
    if provider == "auto":
        for name in ("bedrock", "openai"):
            try:
                resolve_llm_key(name)
                provider = name
                break
            except EvaluationError:
                continue
        if provider == "auto":
            raise EvaluationError(
                "No LLM API key found. Set AWS_BEARER_TOKEN_BEDROCK "
                "or OPENAI_API_KEY in .env."
            )

    configure_provider(provider, args.model)
    need_llm = bool({"router", "latency"} & set(stages))
    llm_key = resolve_llm_key(provider) if need_llm else ""
    serper_key = (os.getenv("SERPER_API_KEY") or "").strip()
    need_serper = bool({"retrieval", "latency"} & set(stages))
    if need_serper and not serper_key:
        raise EvaluationError("SERPER_API_KEY is required for the retrieval/latency stages.")

    from backend.services.llm import chat_model, provider_label

    print(f"provider={provider}  endpoint={provider_label()}")
    print("running credential preflight...")
    probe = await preflight(provider, llm_key, serper_key, need_serper, need_llm)
    llm_status = (
        f"OK ({probe['llm_probe_ms']} ms)" if probe.get("llm_ok")
        else "skipped (no LLM-dependent stage selected)"
    )
    print(f"  LLM {llm_status}, Serper {'OK' if probe.get('serper_ok') else 'skipped'}")
    if args.verify_only:
        print("verify-only: credentials valid, exiting without running the evaluation.")
        return 0

    started_at = datetime.now(timezone.utc)
    wall_start = time.perf_counter()
    payload: dict[str, Any] = {
        "metadata": {
            "timestamp_utc": started_at.isoformat(timespec="seconds"),
            "provider": provider,
            "llm_endpoint": provider_label(),
            "model": chat_model(),
            "dataset_version": dataset["version"],
            "dataset_cases": len(cases),
            "stages": stages,
            "router_repeats": args.router_repeats if "router" in stages else 0,
            "latency_repeats": args.latency_repeats if "latency" in stages else 0,
            "concurrency": args.concurrency,
            "python": platform.python_version(),
            "platform": platform.system(),
            "llm_exercised": need_llm,
            "preflight": probe,
        },
        "warnings": [],
    }

    if "router" in stages:
        records = await run_router_stage(cases, llm_key, args.router_repeats, args.concurrency)
        payload["router_metrics"] = compute_router_metrics(records)
        payload["router_records"] = records

    if "retrieval" in stages:
        subset = [c for c in cases if c.get("retrieval_eval")]
        records = await run_retrieval_stage(subset, serper_key, args.concurrency)
        payload["retrieval_metrics"] = compute_retrieval_metrics(records)
        payload["retrieval_records"] = records

    if "latency" in stages:
        subset = select_latency_cases(cases, args.latency_queries)
        records = await run_latency_stage(subset, llm_key, serper_key, args.latency_repeats)
        payload["latency_metrics"] = compute_latency_metrics(records)
        payload["latency_records"] = records

    payload["metadata"]["wall_clock_s"] = round(time.perf_counter() - wall_start, 1)

    # Surface anything that would otherwise be quietly hidden.
    warnings: list[str] = []
    for key, label in (("router_metrics", "router"), ("retrieval_metrics", "retrieval"),
                       ("latency_metrics", "latency")):
        m = payload.get(key)
        if m and m.get("n_errors"):
            warnings.append(
                f"{label} stage had {m['n_errors']} errored case(s); they are excluded "
                f"from rates and listed under `{key}.errors`."
            )
    rm = payload.get("router_metrics")
    if rm and rm["determinism"]["n_unstable"]:
        warnings.append(
            f"Router returned inconsistent decisions on "
            f"{rm['determinism']['n_unstable']} query/queries across identical repeated calls."
        )
    lm = payload.get("latency_metrics")
    if lm and lm["n_runs"] < 20:
        warnings.append(
            f"Latency sample is small (n={lm['n_runs']}); p95 is indicative only."
        )
    payload["warnings"] = warnings

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = f"_{args.tag}" if args.tag else ""
    json_path = out_dir / f"results{suffix}.json"
    md_path = out_dir / f"results{suffix}.md"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(render_markdown(payload), encoding="utf-8")

    print(f"\nwrote {json_path}")
    print(f"wrote {md_path}")
    for w in warnings:
        print(f"WARNING: {w}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="AutoSearch-LLM Phase 1 evaluation")
    p.add_argument("--dataset", default=str(DEFAULT_DATASET))
    p.add_argument("--out", default=str(DEFAULT_OUT_DIR))
    p.add_argument("--tag", default="", help="Suffix for output filenames")
    p.add_argument("--stages", default="router,retrieval,latency")
    p.add_argument("--provider", default="auto", choices=["auto", "openai", "bedrock"])
    p.add_argument("--model", default=os.getenv("AUTOSEARCH_LLM_MODEL") or None)
    p.add_argument("--router-repeats", type=int, default=3)
    p.add_argument("--latency-queries", type=int, default=8)
    p.add_argument("--latency-repeats", type=int, default=3)
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--verify-only", action="store_true")
    return p


def main() -> int:
    args = build_parser().parse_args()
    try:
        return asyncio.run(main_async(args))
    except EvaluationError as error:
        print(f"\nFATAL: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
