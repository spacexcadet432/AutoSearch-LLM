"""Explicit error taxonomy for the retrieval path.

The point of these types is to let the code distinguish *expected* external
failures (a page 404s, a provider rate-limits us) from *unexpected* programming
errors (AttributeError, TypeError). Expected failures degrade gracefully;
unexpected ones are logged loudly with a traceback so bugs stay visible instead
of being silently reported as "fetch_error".
"""

from __future__ import annotations


class RetrievalError(RuntimeError):
    """Base class for retrieval-path failures."""


class SearchProviderError(RetrievalError):
    """The search provider (Serper) could not be used.

    ``retryable`` marks transient conditions (timeout, connection reset, 429,
    5xx). Authentication and malformed-request failures are NOT retryable and
    must fail fast rather than burn quota.
    """

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


class PageFetchError(RetrievalError):
    """A single candidate page could not be fetched or used.

    One of these must never fail the whole request: other sources continue.
    """


class ContentTooLargeError(PageFetchError):
    """Download exceeded the configured byte cap and was aborted mid-stream."""


class UnsupportedContentTypeError(PageFetchError):
    """Response was not HTML/text (e.g. a PDF, image or archive)."""
