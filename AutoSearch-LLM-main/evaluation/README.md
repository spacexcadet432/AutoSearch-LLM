# AutoSearch-LLM — Phase 1 Evaluation

Purpose: make the existing system **measurable** before changing it. This harness does not
alter routing, retrieval or generation behaviour — it runs the real implementation and records
what it actually does.

## Running it

One command runs everything:

```bash
python -m evaluation.run_evaluation
```

Outputs land in `evaluation/results/`:

| File | Contents |
|---|---|
| `results.json` | Full machine-readable metrics **plus every raw per-case record** |
| `results.md` | Human-readable summary tables |

Useful variants:

```bash
python -m evaluation.run_evaluation --verify-only          # check credentials, run nothing
python -m evaluation.run_evaluation --stages router        # router only (no Serper needed)
python -m evaluation.run_evaluation --stages retrieval,latency
python -m evaluation.run_evaluation --router-repeats 5 --latency-repeats 5
python -m evaluation.run_evaluation --provider xai --model grok-4-fast
python -m evaluation.selftest                              # verify metric maths, no network
```

### Credentials

Read from `.env` at the repo root (already gitignored) or the ambient environment.
**Keys are never printed, logged, or written into any results file.**

```
SERPER_API_KEY=...
# and one LLM key, matching your provider:
OPENAI_API_KEY=...     # --provider openai
XAI_API_KEY=...        # --provider xai
GROQ_API_KEY=...       # --provider groq
```

`--provider auto` (the default) picks the first provider it finds a key for.

The harness runs a **preflight** against both APIs before doing any work. If either
credential fails it prints the exact error and exits with code 2 — it never falls back to a
different provider or emits partial numbers silently.

### Provider configuration

The application is provider-agnostic through one small module, `backend/services/llm.py`,
driven by two optional environment variables:

| Variable | Default | Effect |
|---|---|---|
| `AUTOSEARCH_LLM_BASE_URL` | unset | Any OpenAI-compatible base URL |
| `AUTOSEARCH_LLM_MODEL` | `gpt-4o-mini` | Chat model id |

With neither set, behaviour is byte-for-byte the original OpenAI configuration.

## Dataset

`evaluation/dataset.json` — 44 hand-written, hand-labelled queries. Version-controlled so
runs are comparable over time.

```jsonc
{
  "version": "1.0",
  "labelling_criterion": { ... },   // the rule used to assign every label
  "categories": { "<name>": { "expected_route": ..., "why": ... } },
  "cases": [
    {
      "id": "trap-06",
      "query": "Who is the CEO of Twitter?",
      "category": "routing_traps",
      "expected_route": "search",          // "search" | "direct" | "either"
      "rationale": "why this label",
      "retrieval_eval": true,              // include in the retrieval stage
      "retrieval_keywords": ["twitter", "x", "ceo"]
    }
  ]
}
```

### Labelling criterion

> Does answering this correctly require information the model cannot reliably hold in its weights?

- **`search`** — the answer depends on information that is newer than any plausible training
  cutoff, or volatile enough that a memorised answer is likely stale (live prices, current
  officeholders, standings, latest versions, ongoing events, weather).
- **`direct`** — stable knowledge (settled history, definitions, science, maths) or pure
  reasoning/generation (code, arithmetic, rewriting) where retrieval adds cost but no correctness.
- **`either`** — informed engineers would reasonably disagree. **Excluded from accuracy** and
  reported separately, so borderline cases cannot silently inflate or deflate the headline number.

The label follows the volatility of the **answer**, never temporal keywords in the **query**.

### Categories and why each exists

| Category | n | Expected | Why it is in the set |
|---|---|---|---|
| `time_sensitive_explicit` | 8 | search | Obvious live-data needs. The floor: a failure here is a severe defect, not a tuning issue. |
| `timeless_factual` | 8 | direct | Stable facts. Measures **unnecessary retrieval** — the system's main cost and latency driver. |
| `reasoning_or_generation` | 7 | direct | Code/maths/rewriting with no external fact to fetch. Different failure mode: retrieval here also pollutes the generation context. |
| `ambiguous_borderline` | 6 | either | Genuinely defensible both ways. Isolates borderline cases and exposes over/under-retrieval **bias**. |
| `retrieval_useful` | 7 | search | Needs search *and* has a well-covered web footprint — the input set for retrieval quality. |
| `routing_traps` | 8 | mixed | Breaks keyword-matching routers. Two opposite traps: settled facts containing years or "current"/"newest" (→ direct), and volatile answers containing no temporal word at all (→ search). |

## Metrics

### 1. Routing

Calls the production router, `backend/services/routing.py::classify_temporal_need`, directly.
Each query runs `--router-repeats` times (default 3); the **majority decision** is scored and
disagreement across repeats is reported as a stability rate.

- **Accuracy** — over `search`/`direct` cases only (`either` excluded)
- **Confusion matrix** on the `search` class:
  - *unnecessary retrieval* — searched when it should not have (false positive; wasted cost/latency)
  - *missed retrieval* — answered directly when it should have searched (false negative; stale answers)
- **Precision / recall / F1** for `search`
- **Per-category accuracy and search-rate**
- **Ambiguous search-rate** — over/under-retrieval bias
- **Determinism** — decision stability across identical repeated calls at `temperature=0`
- **Confidence** — mean on correct vs incorrect decisions (is confidence informative?)

### 2. Retrieval

Runs `backend/services/search.py::retrieve_sources` with the **same parameters the production
pipeline uses** (`max_pages=3, top_m=3, deadline_ms=3500`) over the `retrieval_eval` subset.

- **Retrieval success rate** — fraction returning ≥1 source
- **Failure taxonomy** — `search_provider_error`, `no_search_results`, `no_fetchable_urls`,
  `no_extractable_content`
- **Per-page fetch outcomes** — `extracted`, `snippet_fallback`, `thin_content`, `fetch_error`,
  `deadline_exceeded`
- **Source diversity** — distinct sources and distinct domains per query
- **Topical keyword proxy** — see the honesty note below
- **Ranking behaviour** — rank-1 hit rate vs overall chunk hit rate. If ranking adds value,
  rank-1 should score *above* the average chunk.
- **Stage latency** — discovery / fetch+extract / ranking

### 3. Latency

Runs the full `run_query_pipeline` **sequentially** (concurrency would corrupt per-stage
timings) over a deterministic, path-balanced subset, `--latency-repeats` times each.

Reports mean / median / p95 / min / max / stdev for routing, retrieval, generation and total,
split by **search path** vs **direct path**, plus retrieval sub-stages.

## Methodology and honesty notes

**Nothing is mocked or simulated.** Every number in `results.md` comes from a real call to the
real pipeline against live third-party APIs.

**Failed cases are never hidden.** Errors are recorded per case, counted, excluded from rates
(rather than being scored as correct), listed in `results.json` under `<stage>.errors`, and
surfaced as `WARNING` lines on stdout and a `## Warnings` section in `results.md`.

**Metric arithmetic is independently verified.** `evaluation/metrics.py` is pure — no I/O, no
network — and `evaluation/selftest.py` feeds it hand-built records with hand-computed expected
values (62 assertions). This validates the measurement code only and **produces no baseline
numbers**; it must never be reported as evaluation results.

## Limitations

These are real constraints on how far the numbers can be trusted.

1. **No ground-truth relevance judgements — so no true precision/recall for retrieval.**
   We have no human-labelled set of "the correct sources" for each query. The **topical keyword
   proxy** only checks whether a topical anchor term appears in a retrieved chunk. A page can
   contain the anchor and still be useless; a genuinely relevant page may phrase things
   differently. Treat it as a coarse *on-topic* signal, **not** a relevance metric. It is
   reported under a `topical_keyword_proxy` key precisely so it cannot be mistaken for precision.

2. **Routing labels are single-annotator.** One person applied the criterion. The `either`
   category exists to quarantine the cases most exposed to this, but the `search`/`direct`
   labels still encode one reasonable reading, not a consensus.

3. **Latency is noisy and not portable.** It is dominated by two external services (the LLM
   provider and Serper) plus local network conditions. Absolute values are **not comparable**
   across machines, networks, times of day, or providers. Only within-run comparisons between
   stages are meaningful. Re-run before/after any Phase 2 change rather than comparing to a
   number recorded here.

4. **p95 on small samples is indicative only.** Default settings produce ~24 latency runs.
   Every latency summary carries `n` and a `p95_reliable` flag (`true` only at n ≥ 20); p95
   values from smaller samples are marked with `*` in `results.md`.

5. **The live web changes underneath the dataset.** Retrieval results are not reproducible
   byte-for-byte: Serper rankings and page content shift daily. Retrieval *rates* are stable
   enough to compare; individual URLs are not.

6. **Time-sensitive labels have a shelf life.** Cases like "the newest element added to the
   periodic table" are labelled `direct` because the answer has been static for years. If that
   changes, the label must change. The dataset is versioned (`version`, `created`) for this reason.

7. **Answer quality is not evaluated.** This phase measures *routing correctness*, *retrieval
   behaviour* and *latency*. It does not measure whether the final answer is factually correct,
   well-grounded, or free of hallucination. That needs a separate method (human grading or an
   LLM judge with its own validation) and is deliberately out of scope for Phase 1.

8. **Cost is not measured.** Token usage and per-query spend are not recorded.
