"""Terminal interface for AutoSearch-LLM.

This is a thin presentation layer. All routing, retrieval, caching, timeout,
retry and grounding logic lives in backend/services and is called through
``run_query_pipeline`` - nothing is reimplemented here.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from typing import Any

from dotenv import load_dotenv

from backend.logging_config import configure_logging
from backend.services import config
from backend.services.credentials import resolve_llm_key, resolve_search_key
from backend.services.pipeline import run_query_pipeline

EXIT_WORDS = {"exit", "quit", ":q"}

BEDROCK_HINT = (
    "https://bedrock-runtime.<region>.amazonaws.com/openai/v1"
)


# ---------------------------------------------------------------- config
def check_configuration() -> list[str]:
    """Return human-readable problems with the current configuration.

    Empty list means the CLI can run. Messages name the exact variable to set
    so a misconfiguration never surfaces as a stack trace.
    """
    problems: list[str] = []

    if not resolve_search_key():
        problems.append(
            "SERPER_API_KEY is not set. Get a key at https://serper.dev and put "
            "it in your .env file."
        )

    if not resolve_llm_key():
        problems.append(
            "No LLM credential found. Set AWS_BEARER_TOKEN_BEDROCK (Amazon "
            "Bedrock) or OPENAI_API_KEY in your .env file."
        )
    elif os.getenv("AWS_BEARER_TOKEN_BEDROCK") and not config.base_url_is_set():
        # A Bedrock token sent to the default OpenAI endpoint fails with a
        # confusing 401, so catch it before the first request.
        problems.append(
            "AWS_BEARER_TOKEN_BEDROCK is set but AUTOSEARCH_LLM_BASE_URL is not. "
            f"Set it to {BEDROCK_HINT} and set AUTOSEARCH_LLM_MODEL "
            "(e.g. openai.gpt-oss-120b-1:0)."
        )

    return problems


# ------------------------------------------------------------- rendering
_ROUTING_LABEL = {"search": "web retrieval", "direct": "direct model answer"}

_STATUS_NOTE = {
    "ok": "all sources retrieved",
    "partial": "some sources failed to load",
    "no_results": "no usable sources found",
    "no_useful_results": "sources found but they did not support an answer",
    "failed": "web retrieval unavailable",
}


def format_result(result: dict[str, Any]) -> str:
    """Render a pipeline result for the terminal."""
    lines: list[str] = []
    routing = (result.get("routing_decision") or "").lower()
    lines.append(f"Routing:   {_ROUTING_LABEL.get(routing, routing or 'unknown')}")

    confidence = result.get("confidence")
    if isinstance(confidence, (int, float)):
        lines[-1] += f"  (confidence {confidence:.2f})"

    status = result.get("retrieval_status")
    if status:
        note = _STATUS_NOTE.get(status, status)
        lines.append(f"Retrieval: {status} - {note}")

    sources = result.get("sources") or []
    lines.append(f"Sources:   {len(sources)}")
    for index, url in enumerate(sources, start=1):
        lines.append(f"  [{index}] {url}")

    # Be explicit when the answer is model recall rather than source-backed.
    if result.get("used_search"):
        lines.append(
            "Grounded:  yes - answer generated from the sources above"
            if result.get("grounded")
            else "Grounded:  NO - answered from model knowledge, not the sources above"
        )

    latency = result.get("latency")
    if isinstance(latency, (int, float)):
        lines.append(f"Latency:   {latency:.2f}s")

    lines.append("")
    lines.append("Answer:")
    lines.append((result.get("answer") or "").strip() or "(no answer returned)")
    return "\n".join(lines)


# -------------------------------------------------------------- execution
async def answer_query(query: str) -> dict[str, Any]:
    """Run one query through the existing pipeline."""
    return await run_query_pipeline(
        query,
        openai_api_key=resolve_llm_key(),
        serper_api_key=resolve_search_key(),
    )


def _describe_error(error: BaseException) -> str:
    """Turn provider exceptions into something a terminal user can act on."""
    name = type(error).__name__
    text = str(error)
    if "AuthenticationError" in name or "PermissionDenied" in name:
        return "Authentication failed. Check your Bedrock/OpenAI credential."
    if "RateLimit" in name or "429" in text:
        return "Rate limited or out of quota. Wait and try again."
    if "Timeout" in name:
        return "The LLM provider timed out."
    if "Connection" in name:
        return "Could not reach the LLM provider. Check your network."
    return f"{name}: {text}" if text else name


def run_query(query: str) -> int:
    """Execute one query and print the result. Returns a process exit code."""
    try:
        result = asyncio.run(answer_query(query))
    except KeyboardInterrupt:
        # asyncio.run cancels the pipeline task, which cancels in-flight
        # retrieval work through the existing cleanup path.
        print("\n[cancelled]")
        return 130
    except Exception as error:  # noqa: BLE001 - surfaced to the user, not swallowed
        logging.getLogger("autosearch.cli").debug("query failed", exc_info=True)
        print(f"\nError: {_describe_error(error)}", file=sys.stderr)
        return 1

    print()
    print(format_result(result))
    return 0


def repl() -> int:
    """Interactive prompt. Multiple queries share one process (and one cache)."""
    print("AutoSearch-LLM ready.")
    print("Type a query, or 'exit' to quit.")

    while True:
        try:
            print()
            query = input("Enter query:\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            return 0

        if not query:
            continue
        if query.lower() in EXIT_WORDS:
            print("Bye.")
            return 0

        run_query(query)


# ------------------------------------------------------------------ main
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m autosearch",
        description="Adaptive LLM routing with optional grounded web retrieval.",
    )
    parser.add_argument(
        "query",
        nargs="*",
        help="Run a single query and exit. Omit for an interactive prompt.",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Show pipeline logs (routing, retrieval, cache).",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Validate configuration and exit without calling any API.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    load_dotenv()

    # Quiet by default so the answer is readable; -v surfaces the pipeline logs.
    os.environ.setdefault("AUTOSEARCH_LOG_LEVEL", "INFO" if args.verbose else "WARNING")
    configure_logging()

    problems = check_configuration()
    if problems:
        print("Configuration problems:\n", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print(
            "\nCopy .env.example to .env and fill in the values.", file=sys.stderr
        )
        return 2

    if args.check:
        print("Configuration OK.")
        print(f"  LLM endpoint: {config.provider_summary()}")
        print(f"  Search cache: {'on' if config.search_cache_enabled() else 'off'}")
        return 0

    if args.query:
        return run_query(" ".join(args.query))
    return repl()


if __name__ == "__main__":
    raise SystemExit(main())
