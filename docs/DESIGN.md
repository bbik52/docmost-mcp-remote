# Design: Docmost MCP server (working title)

## Goal
Open-source MCP server for the internet, behind a domain with authorization. Anyone can run it in Docker and connect their own Docmost CE. A backend seam leaves room for the official EE API later.

## Decisions so far
| Topic | Decision |
|---|---|
| Path | New repository, written from scratch; docmost-mcp-oss is a reference only (ADR 0001) |
| License | Apache 2.0, contributions under the same license, no CLA; DCO and release signing deferred (ADR 0006) |
| Tenancy | 1 server = 1 Docmost = many Members (ADR 0002) |
| Docmost identity | Each Member's own account; no password stored by default |
| Client auth | OAuth 2.1 + personal bearer tokens (ADR 0003) |
| Sign-in access | Any Docmost user, optional email allowlist |
| State | Postgres |
| Docmost session expiry | Admin flag: re-login (default) or encrypted stored password |
| Edition | CE only in v1; backend interface leaves a seam for EE |
| Compatibility | Docmost version matrix; CI runs integration tests against real Docmost (oldest supported, previous, latest); reachability check at startup, version check at sign-in (Docmost reports its version only to signed-in users) |
| Tools v1 | Read + write pages and comments; delete only to Trash (ADR 0004) |
| Transport | Behind reverse proxy, https public URL mandatory; http Docmost URL only with explicit flag |

## Findings from the audit of the original, and how this design answers them
Status as of phase 7; the threats are reviewed in [security-model.md](security-model.md).

| # | Finding | Answer | Status |
|---|---|---|---|
| 1 | HTTP mode without auth | Auth is mandatory; no unauthenticated mode exists | Done: `oauth.py`, `tests/test_server.py` |
| 2 | Prompt injection | Scopes, untrusted-data wrapping, Trash instead of delete | Done: `tools/untrusted.py`, `tools/write.py`; residual risk in security-model.md |
| 3 | Irreversible overwrite | Snapshot before replace | Done: snapshot before every body write, `tests/test_write_tools.py` |
| 4 | Password in client config | Client config holds no Docmost password; login happens in the browser | Done: `web/routes.py`, OAuth consent |
| 5 | No URL scheme check | https required, http only via explicit flag with a warning | Done: `config.py`, `tests/test_config.py` |
| 6 | Cookie login breaks body update | Server owns the Docmost token handling; covered by integration tests | Done: bearer header only, `tests/integration/` |
| 7 | Temp page left in trash | Find a way without temp pages, or clean up and hide them | Not applicable: no temp pages (`pages/update` with Markdown) |
| 8 | Heavy overview calls | Page limits and request budget per call | Done: list limits, `MAX_PAGE_CHARS`, `TOOL_CALLS_PER_MINUTE` |
| 9 | No SECURITY.md | Add one | Done: `SECURITY.md` |
| 10 | WebSocket without size limit | Set a limit | Not applicable: no WebSocket client; HTTP responses are size-limited |

## Extra risks from my own review (not in the pasted audit)
| Risk | Status |
|---|---|
| OAuth: exact redirect URI match, PKCE required, resource/audience binding, short access tokens, refresh token rotation, abuse limits on dynamic client registration | Done: `oauth.py`, `tests/test_oauth.py` |
| Login page as a password endpoint: CSRF, rate limits per IP and per email, generic errors | Done: `web/routes.py`, `tests/test_web.py`. A per-email limit acts as the lockout |
| Encryption of stored Docmost tokens with a key outside git, with rotation | Done: `crypto.py`, `admin rotate-key` |
| Logs without passwords, tokens, page content or tool arguments | Done: `tests/test_guard.py` |
| Response size limits and per-Member rate limits | Done: `docmost/ce.py`, `guard.py` |
| Container: non-root, read-only filesystem, pinned dependencies, signed image built in CI, Dependabot, `pip-audit` | Done except the signed image: the image is built in CI (phase 8), signing is deferred (ADR 0006) |
| Revocation by Members and by the Admin | Done: account page, `admin revoke-grant`, `revoke-member`, `disable-member` |
| Audit log of tool calls without content | Done: `guard.py`, `audit_log` table, `admin audit` |
| Licensing: clean implementation, nothing copied | Done: no copied code; `NOTICE` holds only the project's own notice |
| Snapshots visible to the Admin | Deferred: the Admin has the database and the key; there is no admin command for snapshots in v1 |

## Contributions and project security
The license is Apache 2.0 (ADR 0006). As the project gains users and contributors:

- **Contributing.** `CONTRIBUTING.md` explains the build, the tests (unit,
  Postgres and real Docmost), git flow and how to open a pull request.
  Contributions are accepted under Apache 2.0 section 5; there is no CLA.
  A DCO (`Signed-off-by`) check is deferred and can be added later.
- **Vulnerability reports.** `SECURITY.md` points to private GitHub security
  advisories; [security-model.md](security-model.md) holds the threat model.
- **Review.** Every change goes through a pull request with green CI. Changes
  to authentication, OAuth, tokens, cryptography, the consent and sign-in
  pages or the write path (`oauth.py`, `auth.py`, `crypto.py`, `web/`,
  `tools/write.py`, `db/`) need a review by a second maintainer once there is
  one.
- **Branch protection.** `master` and `develop` accept changes only through
  pull requests with the CI checks passing; nobody pushes directly. Release
  tags are created from `master` only.
- **Publishing rights.** PyPI uses trusted publishing from the release
  workflow, so no long-lived token exists; ghcr.io is written only by that
  workflow. Few people hold admin rights on the repository.
- **Supply chain.** Locked dependencies, Dependabot, `pip-audit` in CI.
  Signed release artifacts are deferred (ADR 0006).
- **Community files.** A code of conduct and issue and pull request templates
  are added when outside contributions start.
- **The name.** The license gives no rights to the name `docmost-mcp-remote`
  (Apache 2.0 section 6). Forks are welcome but should use another name so
  users can tell them apart; the README says so. "Docmost" is a name of the
  Docmost project; this project only describes compatibility with it.

## Database migrations
The server's own Postgres schema is managed with Alembic
(`src/docmost_mcp_remote/db/migrations/`).

- **Applied at startup.** The server, and every `admin` command, upgrades the
  schema to the newest revision before it serves anything. Admins do nothing
  extra on upgrade; `admin migrate` does the same step on its own and shows
  the revision.
- **One migrator at a time.** The upgrade runs in one transaction under a
  Postgres advisory lock, so several replicas or a replica and an `admin`
  command starting together wait for each other, and a failed migration
  leaves the schema as it was.
- **No silent downgrade.** A server that finds a revision it does not know
  (the database was upgraded by a newer version) refuses to start instead
  of running against a schema it does not understand.
- **Forward only in production.** Migrations have `downgrade()` functions for
  development and tests, but going back to an older version means restoring
  the backup taken before the upgrade. The README asks for a backup before
  every upgrade.
- **Rules for changes.** Every schema change ships a migration in the same
  pull request (`tests/test_migrations.py` fails when `schema.py` and the
  migrations disagree). A released migration is never edited; fixes go into
  a new one. Migrations keep existing data: a renamed or reshaped column is
  copied over in the migration, not dropped. A test upgrades from every
  revision to the newest one with data in place. A release whose
  migrations take long or need care says so in the changelog under
  "Upgrade notes".
- **Within a major version** the schema only grows in ways the previous
  minor release can survive for the few seconds of a rolling restart (new
  tables, new nullable columns). Changes that would break a running older
  version wait for a major release.

## Open questions
1. ~~Snapshot storage and retention.~~ Resolved, see "Snapshots" below.
2. ~~How to update page bodies in CE without the temp-page trick.~~ Resolved, see "Page body updates" below.
3. ~~Language of the docs.~~ Resolved: English-first (README.md, SECURITY.md, docs/, error messages, login page). A Russian translation (README.ru.md) is added later, once the English text is stable.
4. ~~Project name and repository.~~ Resolved: `docmost-mcp-remote` (GitHub `bbik52/docmost-mcp-remote`, PyPI `docmost-mcp-remote`; both names were free on 2026-10-25, GitHub only checked for public repos). The repository is new (not a fork), so its default branch is `master`.
5. ~~Deploy details.~~ Resolved: a universal open-source approach, no Swarm in the project. The repo ships a plain `compose.yaml` (server + Postgres, named volume for Postgres, secrets from `.env`, required variables written as `${VAR:?...}`) and a short README section on putting it behind any reverse proxy with https. The image is published to `ghcr.io` from GitHub Actions. Swarm or Traefik examples, if wanted, live in `docs/examples/` and are not part of the supported setup. Your own Swarm stack is a private deployment and stays outside the repository.

## Page body updates (checked against Docmost source)
Checked: Docmost master 0.97.0 (clone of 2026-10-25), and the original `docmost-mcp-oss` at `f4f9538`.

- Since Docmost **v0.70.0** (commit `18b57815`, 2026-02-12) `POST /api/pages/update` accepts `content` plus `operation` (`append` / `prepend` / `replace`) and `format` (`json` / `markdown` / `html`). The server converts the content to a ProseMirror document and applies it to the live Yjs document through the collaboration handler. No WebSocket client and no temporary page are needed.
- `POST /api/pages/create` also takes `content` and `format`, so a new page can be created with a body in one call.
- Neither endpoint is behind an EE license check. The controller only checks that the user can edit the page.
- The original's workaround (uploading a `.md` file to a temporary page, reading its Yjs document, deleting the page) predates v0.70.0 and is not needed on newer versions. The same temporary page is what causes audit finding 7.

Decision: use `/api/pages/update` with `format=markdown` as the only write path. Drop the Yjs WebSocket client, and with it finding 10 (WebSocket size limit) and finding 6 (collab auth by cookie).

Consequences:
- **Minimum supported Docmost is 0.70.0.** Older versions are refused by the version check at sign-in.
- **Silent no-op risk.** If Docmost is run with `COLLAB_DISABLE_REDIS` set, the collaboration gateway has no Redis sync extension and `handleYjsEvent` returns without doing anything, while the endpoint still answers 200. The server must read the page back after a write and fail the tool call if the body did not change. This check also applies after the Snapshot is taken.
- Writes are applied with a delay: Hocuspocus persists with a debounce of 10 s (max 45 s). A read right after a write goes through `pages/info`, which reads from the database, so the read-back should poll for a bounded time or read through the Yjs state. To verify with an integration test.
- `replace` deletes and re-inserts the whole fragment. Comment marks on replaced text are lost, and a Member who has the page open sees it change. Prefer `append`/`prepend` where the tool allows it, and say so in the tool description.
- Snapshots can use the existing page history in Docmost (`/api/pages/history`) if a history entry is created for the write, otherwise the server stores its own copy. To verify.

## Snapshots
Docmost's own page history cannot serve as the backup: the history job is queued after a save with a delay and a job id equal to the page id, so it records the page after the edit, not before it (`persistence.extension.ts`, `enqueuePageHistory`).

Decision:
- Before every `replace` (and every `append`/`prepend`), the server reads the page and stores its body as a Snapshot in the server's own Postgres, together with page id, Member, time and the tool call that caused the write.
- Retention is `SNAPSHOT_RETENTION_DAYS`, default 30. A scheduled job deletes older rows.
- A Snapshot is visible to the Member who made the write, and to the Admin. A restore tool needs scope `write` and goes through the same write path, so it takes a new Snapshot of the current body first.
- If the Snapshot cannot be saved, the write is not done.

Consequences:
- The server's database holds copies of page content. It must be protected like Docmost's own database: backups, access control, encryption at rest where the host provides it.
- Page content older than the retention period that was deleted in Docmost remains in the Snapshot table until the job removes it. Stated in the README.

## Distribution (variant A: self-hosted only)
Decision: v1 is a self-hosted server that each Admin runs on their own domain. No hosted multi-tenant service. Multi-tenancy is a possible later ADR; it would bring SSRF protection for user-supplied Docmost URLs, tenant isolation, a privacy policy and operations duties, none of which v1 needs.

Discoverability checklist (verified against each directory's docs in October 2026; see [RELEASING.md](RELEASING.md)):
- Official MCP Registry: `server.json` with `$schema` `https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json`, name `io.github.bbik52/docmost-mcp-remote`, a description of at most 100 characters, a PyPI package and an OCI package. Ownership is checked by an `mcp-name:` line in the PyPI README and by the `io.modelcontextprotocol.server.name` label on the image; both are in place and covered by `tests/test_release_metadata.py`. The release workflow publishes with `mcp-publisher` and GitHub OIDC. A `remotes` entry is not used: there is no single public URL, every Admin runs their own.
- GitHub topics: `mcp`, `mcp-server`, `docmost`, `model-context-protocol`, `oauth`, `wiki`, `self-hosted`; a one-sentence description with "Docmost" and "remote MCP server".
- Publish the package to PyPI (trusted publishing) and the image to `ghcr.io` (public) from GitHub Actions.
- README starts with what it is, the supported Docmost versions, a security model section and a copy-paste `compose.yaml` (a test keeps the README copy equal to the file).
- Directories that index GitHub (Glama and similar) pick the repo up from README and topics; word order in the repository name is not a documented factor.
- The Anthropic connector directory is not a target for self-hosted setups (it expects one public URL operated by the developer).

Name confirmed: `docmost-mcp-remote` stays (checked alternative `mcp-server-docmost`, rejected: loses the "remote" distinction and the shared `docmost-mcp*` search prefix).
