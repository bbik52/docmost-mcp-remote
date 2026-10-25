# Roadmap to v1.0.0

This is the plan from an empty repository to the v1.0.0 release. It follows
[DESIGN.md](DESIGN.md) and the ADRs in [adr/](adr/). The repository uses git
flow: each phase is built on a `feature/*` branch and ends with a pull request
to `develop` that meets the phase's done criteria. A phase is only started
after the previous one is merged. Releases are merged from `develop` to
`master` through a `release/*` branch and tagged on `master`.

Versions: there are no pre-releases. Phases 1–7 accumulate on `develop`; the
first published version is `1.0.0`, cut at the end of phase 8.

| # | Phase | Result |
|---|---|---|
| 1 | Repository skeleton and CI | Installable package, container, compose, green CI |
| 2 | Docmost client and version check | Typed REST client for Docmost CE ≥ 0.70.0, integration tests against real Docmost |
| 3 | Members, Postgres and bearer tokens | Members sign in with their Docmost account, get a personal bearer token |
| 4 | Read tools | First useful server: read spaces, pages, comments, search |
| 5 | OAuth 2.1 | Works as a remote connector in Claude.ai and other OAuth MCP clients |
| 6 | Write tools | Create/update pages and comments, Snapshots, read-back, Trash |
| 7 | Security hardening | Rate limits, audit log, revocation, Admin CLI, threat review |
| 8 | Release `1.0.0` | Docs, image, PyPI, MCP Registry |

---

## Phase 1. Repository skeleton and CI

Scope:
- `pyproject.toml` (Python ≥ 3.12, `uv`, `hatchling`), package `docmost_mcp_remote` in `src/`.
- FastMCP server with a `/healthz` route and no tools; a console script
  `docmost-mcp-remote`.
- Settings from environment variables, validated at startup: `PUBLIC_URL`
  must be https, `DOCMOST_URL` must be https unless
  `DOCMOST_ALLOW_INSECURE_HTTP=true` (logs a warning).
- `Dockerfile` (non-root, slim base, pinned by `uv.lock`), `compose.yaml`
  (server + Postgres, named volume, `${VAR:?...}` for required values),
  `.env.example`.
- `LICENSE` (Apache 2.0 since ADR 0006), `README.md`, `SECURITY.md`, `CONTRIBUTING.md`.
- CI on GitHub Actions: `ruff check`, `ruff format --check`, `mypy`, `pytest`,
  `pip-audit` on the locked dependencies, Docker build. Dependabot for pip,
  Actions and Docker.
- Design docs and ADRs moved into `docs/`.

Done when:
- CI is green on the PR.
- `docker compose up` with a filled `.env` starts the server and `/healthz`
  answers `200`.
- Unit tests cover the settings validation (https rules, required values).

## Phase 2. Docmost client and version check

Scope:
- `DocmostBackend` interface (the seam for a later EE backend) and a CE
  implementation over `httpx`: login, current user, spaces, pages
  (info, tree, recent, children), search, comments, page create/update,
  move to Trash, restore.
- Version check: below 0.70.0 is refused; newer than the tested matrix logs
  a warning. Docmost reports its version only to signed-in users, so the
  server checks reachability at startup and the version at sign-in
  (see `docs/docmost-api-notes.md`).
- Typed errors: auth expired, forbidden, not found, Docmost unavailable,
  unsupported version. Timeouts and response size limits on every call.
- Integration test harness: Docmost + Postgres + Redis in Docker, a seeded
  workspace and user. CI runs it against the latest Docmost and the previous
  minor release.
- Verify the open points from DESIGN.md: how quickly `pages/info` reflects a
  `pages/update` (debounce), what a write looks like with
  `COLLAB_DISABLE_REDIS`, and how session expiry is reported.

Done when:
- Integration tests pass against both Docmost versions in CI.
- The verified behavior is written down in `docs/docmost-api-notes.md`
  (own words, no copied code).
- No code from docmost-mcp-oss or Docmost is in the repository.

## Phase 3. Members, Postgres and bearer tokens

Scope:
- Postgres schema with migrations (Alembic), applied at startup: members,
  Docmost sessions (encrypted), grants with scopes, tokens (hashed). Later
  phases add their own tables (snapshots, audit log) in new migrations.
- Encryption of Docmost tokens with a key from `SECRET_KEY` (envelope with key
  id, supports rotation via `SECRET_KEY_PREVIOUS`).
- Login page: Member enters Docmost email and password, the server logs in to
  Docmost, checks the Docmost version, stores only the encrypted Docmost
  token. CSRF protection, generic
  errors, no password in logs, rate limit per IP and per email.
- Optional email allowlist (`ALLOWED_EMAILS`).
- Account page: create, list and revoke personal bearer tokens with scopes
  (`read` by default). Tokens shown once, stored hashed.
- Relogin mode: `RELOGIN_MODE=ask` (default) marks the session expired and
  asks the Member to sign in again; `RELOGIN_MODE=stored_password` keeps an
  encrypted password and logs in again automatically.
- MCP endpoint requires a valid token; there is no unauthenticated mode.

Done when:
- A Member can sign in, create a token, and an MCP client with that token
  connects; without a token, or with a revoked one, it gets `401`.
- Tests cover: wrong password, allowlist refusal, CSRF failure, token revoke,
  key rotation, expired Docmost session in both relogin modes.

## Phase 4. Read tools

Scope:
- Tools (scope `read`): list spaces, list/tree pages in a space, get a page
  (Markdown), recent pages, search, list comments of a page.
- Page content and comments returned wrapped and labelled as untrusted data.
- Limits per call: page size, number of items, request budget for overview
  calls; truncation is reported to the model.
- Admin space restriction (`ALLOWED_SPACES`) applied to every tool.
- Tool descriptions and annotations (`readOnlyHint`) written from scratch.

Done when:
- Every tool has unit tests and an integration test against real Docmost.
- A Member using Claude Code with a bearer token can browse and search their
  Docmost, and sees only what their Docmost account can see.

## Phase 5. OAuth 2.1

Scope:
- Authorization server per the MCP authorization spec: protected resource
  metadata, authorization server metadata, dynamic client registration with
  abuse limits, authorization code with PKCE (S256 only), exact redirect URI
  match, resource/audience binding, short-lived access tokens, refresh token
  rotation with reuse detection.
- Consent screen that shows the client and the requested scopes; `read` is
  preselected, `write` and `delete` must be ticked.
- OAuth grants and bearer tokens share one Grant model and one revoke list.

Done when:
- Claude.ai (custom connector) and at least one other OAuth MCP client
  connect through the browser flow.
- Tests cover PKCE missing/wrong, redirect URI mismatch, wrong audience,
  expired access token, refresh reuse, revoked grant.

## Phase 6. Write tools

Scope:
- Tools (scope `write`): create page (with Markdown body), update page body
  (`append` / `prepend` / `replace`), rename/move page, add comments and
  replies. Resolving comments is an Enterprise feature in Docmost and is out
  of scope.
- Tools (scope `delete`): move page to Trash, restore from Trash. No
  permanent delete.
- Snapshot before every body write, in the server's Postgres; if the Snapshot
  fails, the write is not done. `SNAPSHOT_RETENTION_DAYS` (default 30) with a
  scheduled cleanup. Tools to list and restore Snapshots (restore takes a new
  Snapshot first).
- Read-back after every write with bounded polling; the tool call fails if
  the body did not change (covers the `COLLAB_DISABLE_REDIS` no-op).
- Tool descriptions prefer `append`/`prepend` and warn that `replace` drops
  comment marks.

Done when:
- Integration tests cover every write tool, the Snapshot-then-write order,
  restore, the read-back failure path and Trash/restore.
- Scope checks: a `read` grant cannot call any write or delete tool.

## Phase 7. Security hardening

Scope:
- Per-Member rate limits and response size limits.
- Audit log of tool calls (who, tool, page id, result; no content, no
  arguments) with retention.
- Admin CLI: list Members and grants, revoke any grant or token, revoke all
  sessions of a Member, rotate the encryption key.
- Logging review: no passwords, tokens, page content or tool arguments.
- Container: read-only root filesystem in compose, dropped capabilities,
  healthcheck.
- Threat model in `docs/security-model.md`; review against the audit findings
  and the extra risks in DESIGN.md; fix what the review finds.

Done when:
- Every item in DESIGN.md "Findings" and "Extra risks" is marked done with a
  link to the code or test, or explicitly deferred with a reason.
- Log-redaction tests pass; rate limit tests pass.

## Phase 8. Release `1.0.0`

Scope:
- README: what it is, supported Docmost versions, security model, copy-paste
  `compose.yaml`, reverse-proxy section, client setup (Claude.ai, Claude Code,
  Cursor), configuration reference.
- Release workflow on tag: multi-arch image to `ghcr.io`, package to PyPI via
  trusted publishing, GitHub release with changelog. Signing the image and
  DCO sign-offs are deferred (ADR 0006). Steps in `docs/RELEASING.md`.
- `server.json` and `mcp-name:` line; publish to the official MCP Registry as
  `io.github.bbik52/docmost-mcp-remote`.
- GitHub topics and description; `README.ru.md`.
- Issues with the audit findings reported to docmost-mcp-oss (ADR 0001).

Done when:
- A fresh user can follow the README from zero to a working connector.
- `1.0.0` is on ghcr.io, PyPI and the MCP Registry.
- The discoverability checklist in DESIGN.md is verified against each
  directory's current docs.

## Out of scope for v1

EE backend, Docmost SSO users, hosted multi-tenant service, permanent delete,
attachments upload, Swarm/Traefik as a supported setup.
