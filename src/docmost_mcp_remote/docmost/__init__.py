"""Access to a Docmost instance over its HTTP API."""

from docmost_mcp_remote.docmost.backend import DocmostBackend, DocmostClient
from docmost_mcp_remote.docmost.ce import CeDocmostClient
from docmost_mcp_remote.docmost.errors import (
    DocmostAuthError,
    DocmostBadRequestError,
    DocmostError,
    DocmostForbiddenError,
    DocmostNotFoundError,
    DocmostResponseTooLargeError,
    DocmostUnavailableError,
    UnsupportedDocmostVersionError,
)

__all__ = [
    "CeDocmostClient",
    "DocmostAuthError",
    "DocmostBackend",
    "DocmostBadRequestError",
    "DocmostClient",
    "DocmostError",
    "DocmostForbiddenError",
    "DocmostNotFoundError",
    "DocmostResponseTooLargeError",
    "DocmostUnavailableError",
    "UnsupportedDocmostVersionError",
]
