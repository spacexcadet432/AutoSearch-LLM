import math
import re
from dataclasses import dataclass
from typing import Iterable, List, Tuple
from urllib.parse import urlparse


def _normalize_terms(text: str) -> List[str]:
    # Cheap tokenization for short queries.
    text = text.lower()
    # keep alphanumerics only
    toks = re.findall(r"[a-z0-9]+", text)
    # remove very short tokens that create noise
    toks = [t for t in toks if len(t) >= 3]
    return toks


def _term_freq(text: str, terms: List[str]) -> List[int]:
    # Count term occurrences with a safe regex word boundary approximation.
    # (Good enough for portfolio signal.)
    text_l = text.lower()
    freqs = []
    for t in terms:
        freqs.append(len(re.findall(rf"\b{re.escape(t)}\b", text_l)))
    return freqs


def domain_of(url: str) -> str:
    try:
        return (urlparse(url).netloc or "").lower()
    except Exception:
        return ""


@dataclass
class CandidateChunk:
    url: str
    title: str | None
    chunk_text: str
    chunk_index: int
    snippet: str | None


def score_chunks(query: str, chunks: Iterable[CandidateChunk]) -> List[Tuple[float, CandidateChunk]]:
    terms = _normalize_terms(query)
    if not terms:
        return [(0.0, c) for c in chunks]

    scored: List[Tuple[float, CandidateChunk]] = []
    for c in chunks:
        # Base lexical relevance on chunk content.
        freqs = _term_freq(c.chunk_text, terms)
        tf_score = sum(min(3, f) for f in freqs)  # saturate high repetition

        # Boost for partial title/snippet matches.
        title_snip = " ".join([t for t in [c.title or "", c.snippet or ""] if t]).lower()
        title_boost = 0.0
        if title_snip:
            title_term_hits = sum(1 for t in terms if t in title_snip)
            title_boost = 0.15 * title_term_hits

        # Length normalization: avoid huge chunks winning by brute-force.
        chunk_len = max(1, len(c.chunk_text))
        length_penalty = 1.0 / math.sqrt(chunk_len / 800.0)

        score = (tf_score + title_boost) * length_penalty
        scored.append((score, c))

    scored.sort(key=lambda x: x[0], reverse=True)
    return scored


def select_top_chunks(
    scored: List[Tuple[float, CandidateChunk]],
    *,
    top_m: int = 12,
    max_chunks_per_domain: int = 2,
) -> List[CandidateChunk]:
    selected: List[CandidateChunk] = []
    per_domain: dict[str, int] = {}

    for score, c in scored:
        d = domain_of(c.url)
        if per_domain.get(d, 0) >= max_chunks_per_domain:
            continue
        selected.append(c)
        per_domain[d] = per_domain.get(d, 0) + 1
        if len(selected) >= top_m:
            break

    return selected

