# 0005. Python, FastMCP and uv

## Status
Accepted

## Context
The server needs a mature MCP implementation with streamable HTTP transport
and hooks for OAuth, a typed HTTP client for Docmost, and a reproducible
dependency set for a security-sensitive service.

## Decision
- Python 3.12 or newer.
- The standalone `fastmcp` package (major version 4) for the MCP server and
  its HTTP application, served by `uvicorn`.
- `pydantic-settings` for configuration; every value comes from the
  environment and is validated at startup.
- `uv` with a committed `uv.lock` for dependency management; the container
  image and CI install from the lock file only.
- `ruff` for lint and formatting, `mypy --strict` for types, `pytest` for
  tests, `pip-audit` on the locked runtime dependencies in CI.

## Consequences
- FastMCP moves fast; the dependency is pinned to one major version and
  updated through Dependabot with CI as the gate.
- Contributors need `uv` installed.
