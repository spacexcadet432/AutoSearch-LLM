import re
from typing import List


def _normalize_newlines(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_text(
    text: str,
    *,
    max_chars: int = 1800,
    overlap_paragraphs: int = 1,
    min_chunk_chars: int = 300,
) -> List[str]:
    """
    Split into chunks using paragraph boundaries.
    Keeps chunks under max_chars, with tiny overlap to reduce context loss.
    """
    text = _normalize_newlines(text)
    if not text:
        return []

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        return []

    chunks: List[str] = []
    cur: List[str] = []
    cur_len = 0

    def flush():
        nonlocal cur, cur_len
        chunk = "\n\n".join(cur).strip()
        if len(chunk) >= min_chunk_chars:
            chunks.append(chunk)
        cur = []
        cur_len = 0

    for i, para in enumerate(paragraphs):
        if cur_len + len(para) + 2 > max_chars and cur:
            flush()
            if overlap_paragraphs > 0:
                # Re-seed with last few paragraphs from previous chunk.
                cur = paragraphs[max(0, i - overlap_paragraphs) : i]
                cur_len = sum(len(x) for x in cur) + max(0, len(cur) - 1) * 2

        cur.append(para)
        cur_len += len(para) + 2

    if cur:
        flush()

    return chunks

