# Changelog

All notable changes to this project are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[semantic versioning](https://semver.org/). A release that needs attention
when upgrading lists it under "Upgrade notes".

## [Unreleased]

## [1.0.2] - 2026-10-25

### Changed

- README: badges, a diagram of how the server fits between AI clients and
  Docmost, and screenshots of the consent and account pages.
- Dependabot opens its pull requests against `develop`; the CI and release
  workflows use `actions/checkout` v7.
- SECURITY.md states the supported versions without naming a release number.
- README.ru.md is now a full translation of README.md, and both link to
  each other at the top.

## [1.0.1] - 2026-10-25

### Fixed

- Sign-in failed with an internal error when Docmost did not report its
  version. Docmost's version endpoint answers with an empty body when its own
  request to the GitHub API fails, for example when rate limited; the server
  now logs a warning and treats the version as unknown.
- The release workflow could not publish to the MCP Registry because an
  action reference did not resolve; 1.0.0 is therefore not in the registry.

## [1.0.0] - 2026-10-25

First release.

### Added

- Remote MCP server (streamable HTTP at `/mcp`) for Docmost Community Edition
  0.70.0 or newer.
- Per-member sign-in with the member's own Docmost account; every tool call
  runs as that member with their Docmost rights. Optional `ALLOWED_EMAILS`
  and `ALLOWED_SPACES` limits.
- OAuth 2.1 authorization server following the MCP authorization spec:
  dynamic client registration, PKCE (S256), consent page with `read`,
  `write` and `delete` scopes, resource-bound tokens, rotating refresh tokens
  with reuse detection. Personal bearer tokens for scripts. Grants and tokens
  are listed and revoked on the account page.
- Read tools: `whoami`, `list_spaces`, `list_pages`, `recent_pages`,
  `get_page` (Markdown), `search`, `list_comments`, `list_trash`,
  `list_snapshots`. Page content is returned inside an untrusted-content
  envelope.
- Write tools: `create_page`, `update_page` (append, prepend, replace),
  `rename_page`, `move_page`, `add_comment`, `restore_snapshot`; delete-scope
  tools `trash_page` and `restore_page`. No permanent delete.
- Encrypted snapshot of a page body before every change, kept for
  `SNAPSHOT_RETENTION_DAYS`; read-back after every write to catch changes
  Docmost did not apply.
- Per-member rate limit (`TOOL_CALLS_PER_MINUTE`) and an audit log of tool
  calls without content (`AUDIT_RETENTION_DAYS`).
- `admin` command line: list members and grants, revoke grants or members,
  disable members, read the audit log, rotate `SECRET_KEY`.
- Database schema migrations applied at startup under a lock; an older
  server refuses to start on a schema upgraded by a newer one.
- Container image for linux/amd64 and linux/arm64, `compose.yaml` with
  Postgres, and a PyPI package.
