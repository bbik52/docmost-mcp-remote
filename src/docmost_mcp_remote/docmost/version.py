"""Docmost version parsing and the supported range."""

from __future__ import annotations

import re
from typing import NamedTuple

from docmost_mcp_remote.docmost.errors import UnsupportedDocmostVersionError

_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")


class Version(NamedTuple):
    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


def parse_version(text: str) -> Version:
    """Parse ``0.97.0``, ``v0.97.0`` or ``0.97.0-beta.1`` (the suffix is ignored)."""
    match = _VERSION_RE.match(text.strip())
    if match is None:
        raise ValueError(f"not a Docmost version: {text!r}")
    major, minor, patch = (int(part) for part in match.groups())
    return Version(major, minor, patch)


#: Oldest release without a published security advisory that the endpoints this
#: server calls expose: 0.71.0 fixed javascript: URLs in attachment nodes of page
#: JSON (CVE-2026-34212), 0.80.1 restricted attachments pulled into page exports
#: by a forged attachment id (CVE-2026-48073).
MIN_SUPPORTED = Version(0, 80, 1)
#: Newest release the integration tests run against.
MAX_TESTED = Version(0, 97, 0)


class VersionCheck(NamedTuple):
    #: None when Docmost did not report its version.
    version: Version | None
    tested: bool


def check_version(text: str) -> VersionCheck:
    """Refuse versions below the minimum; report whether the version was tested.

    Docmost's version endpoint answers with an empty body when its own request
    to the GitHub API fails (for example when rate limited), so a missing
    version is reported as unknown instead of refusing the member.
    """
    if not text.strip():
        return VersionCheck(version=None, tested=False)
    version = parse_version(text)
    if version < MIN_SUPPORTED:
        raise UnsupportedDocmostVersionError(
            f"Docmost {version} is not supported; version {MIN_SUPPORTED} or newer is required"
        )
    return VersionCheck(version=version, tested=version <= MAX_TESTED)
