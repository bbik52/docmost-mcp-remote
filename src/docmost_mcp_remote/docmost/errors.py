"""Errors raised by the Docmost client.

Messages are safe to show to a member: they never contain tokens, passwords
or page content.
"""

from __future__ import annotations


class DocmostError(Exception):
    """Base class for every error the Docmost client raises."""


class DocmostUnavailableError(DocmostError):
    """Docmost could not be reached, timed out, or answered with a server error."""


class DocmostAuthError(DocmostError):
    """The Docmost credentials or session token were rejected (HTTP 401)."""


class DocmostForbiddenError(DocmostError):
    """The member may not do this in Docmost, or it needs an Enterprise license (HTTP 403)."""


class DocmostNotFoundError(DocmostError):
    """The object does not exist, or the member cannot see it (HTTP 404)."""


class DocmostBadRequestError(DocmostError):
    """Docmost refused the request as invalid (HTTP 400 or 422)."""


class DocmostResponseTooLargeError(DocmostError):
    """The response exceeded the configured size limit and was not read."""


class UnsupportedDocmostVersionError(DocmostError):
    """The Docmost version is older than the minimum this server supports."""
