# Changelog

All notable changes to this project are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[semantic versioning](https://semver.org/). A release that needs attention
when upgrading lists it under "Upgrade notes".

## [Unreleased]

### Added

- `whoami` returns `account_url`, the page where a member sees and revokes
  connected apps and tokens.
- `get_space`: details of one space, with its member count and your role.
- `duplicate_page`: copy a page with its child pages, in the same space or
  into another space.
- `move_page_to_space`: move a page with its child pages to another space.
- `update_comment`: change the text of one of your own comments; the
  previous text is returned.
- `get_page_outline`, `get_section` and `replace_section`: read and change
  one section of a long page. `replace_section` takes the section's hash
  from `get_section` and refuses to write if the section changed since, and
  warns when Docmost's Markdown conversion also changed text elsewhere.
- `update_page` and `replace_section` take `dry_run` to show the change as a
  diff without writing it.
- `list_page_history`, `get_page_version` and `diff_page`: the versions
  Docmost saves of a page, read as Markdown, and a diff between the current
  body, a version and a snapshot. Versions are stored by Docmost as
  ProseMirror JSON; the server converts them to Markdown laid out like
  Docmost's own.
- `list_backlinks`, `list_labels`, `find_pages_by_label`, `add_labels` and
  `remove_label` (Docmost 0.90 or newer).
- `search` takes `title_only` and `labels` (Docmost 0.96 or newer) and
  `created_by_me`.
- Links to pages of the same Docmost in Markdown written by the server are
  stored as internal links, so Docmost counts them as backlinks.
- `suggest`: quick lookup of pages, people and groups by name, as Docmost's
  search box does.
- `get_page_tree`: several levels of a page tree in one call, limited by
  depth and page count; branches not read are listed to continue from.
- `list_space_members`, `list_workspace_members` and `list_groups`.
- A new `admin` scope, never granted unless ticked, for `create_space`,
  `update_space`, `add_space_members` (users by email, groups by name) and
  `change_space_member_role`. Docmost still checks the member's own rights.
  With `ALLOWED_SPACES` set, only spaces in that list can be created or
  renamed to. Removing members and deleting spaces are not offered.
- Tools that need a newer Docmost than the connected one say so instead of
  failing with a Docmost error.

### Changed

- README: a note near the top that the project is independent from
  Docmost, Inc. and that Docmost is their trademark.

### Fixed

- The account and consent pages leave space between the scopes box and the
  button below it.

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
