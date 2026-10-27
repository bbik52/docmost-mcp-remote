# Security model

This document describes what the server protects, from whom, and how. It is
the threat review of phase 7 of the [roadmap](ROADMAP.md). Report
vulnerabilities as described in [SECURITY.md](../SECURITY.md).

## Assets

| Asset | Where it lives | Protection |
|---|---|---|
| Docmost session tokens of members | `docmost_sessions` | AES-256-GCM with a key derived from `SECRET_KEY`, bound to the member id |
| Docmost passwords (only with `RELOGIN_MODE=stored_password`) | `docmost_sessions` | Same as session tokens; not stored at all by default |
| Personal tokens, OAuth access and refresh tokens, authorization codes | `tokens`, `oauth_codes` | Only SHA-256 hashes are stored; tokens are shown once; personal tokens expire after 90 days unless the member picks another lifetime |
| Page content | Docmost; copies in `snapshots` | Snapshots are encrypted like sessions, private to the member, deleted after `SNAPSHOT_RETENTION_DAYS` |
| Files sent to an upload link | `upload_files` | Encrypted like snapshots, bound to the link; the content is dropped once the file is in Docmost, and everything is deleted when the link expires (`UPLOAD_RETENTION_MINUTES`) |
| Who did what | `audit_log` | Tool, page or space id, outcome, duration; never content or arguments; deleted after `AUDIT_RETENTION_DAYS` |
| Web sessions of the account and consent pages | Browser cookie | Signed (itsdangerous), `HttpOnly`, `SameSite=Lax`, `__Host-` prefix and `Secure` over https; "Sign out everywhere" ends every session of the member on the server (`members.web_sessions_after`) |

## Actors

- **Member**: a Docmost user who signed in on this server. Acts in Docmost
  with their own rights; can grant clients `read`, `write` and `delete`.
- **Admin**: runs the server; has the environment (`SECRET_KEY`) and the
  database, and the `admin` command line.
- **MCP client**: an AI application holding a grant. Trusted as far as the
  member trusted it, but it reads untrusted page content.
- **Attacker on the internet**: can reach the public URL, register OAuth
  clients and try to sign in.
- **Author of page content**: anyone who can write in Docmost. Their text
  reaches the model and may contain instructions (prompt injection).

## Trust boundaries

1. Internet to the reverse proxy: https, terminated by the Admin's proxy.
2. Proxy to the server: plain http on a private network or loopback;
   `FORWARDED_ALLOW_IPS` decides whose `X-Forwarded-For` is believed; the
   proxy overwrites the header, and the server warns at startup about `*`.
3. Server to Docmost: https (http only with `DOCMOST_ALLOW_INSECURE_HTTP`).
   Every call carries the member's own Docmost token.
4. Server to Postgres: credentials from the environment.
5. Docmost content to the model: wrapped and labelled as untrusted data.

## Threats and mitigations

| Threat | Mitigation | Where |
|---|---|---|
| Use of the MCP endpoint without authorization | Every request needs a valid token; there is no unauthenticated mode | `oauth.py` `load_access_token`, `tests/test_server.py` |
| Brute force of Docmost passwords through the sign-in page | 20 attempts per 10 minutes per IP, 5 per 15 minutes per email, generic error, CSRF token | `web/routes.py`, `tests/test_web.py` |
| Cross-site request forgery on account and consent forms | Per-session CSRF token checked on every POST; `SameSite=Lax` | `web/routes.py`, `tests/test_web.py`, `tests/test_oauth.py` |
| Clickjacking of the consent page | `frame-ancestors 'none'`, `X-Frame-Options: DENY` | `web/routes.py` |
| Stolen authorization code | PKCE with S256 only, single use, 5 minutes, bound to client and redirect URI; replay revokes the grant | `oauth.py`, `tests/test_oauth.py` |
| Open redirect or code theft through redirect URIs | Exact match against registered URIs; only https, loopback http or private-use schemes; no fragments | `oauth.py` `redirect_uri_allowed` |
| Token for this server replayed elsewhere, or another server's token here | Tokens bound to `PUBLIC_URL/mcp` (RFC 8707); other resources refused | `oauth.py`, `tests/test_oauth.py` |
| Stolen refresh token | Rotation on every use; reuse revokes the whole grant | `oauth.py`, `tests/test_oauth.py` |
| Abuse of dynamic client registration | 10 registrations per IP per hour, 10 redirect URIs, at most 1000 clients without a grant (the oldest stale ones make room for new ones), unused clients deleted after an hour | `oauth.py`, `db/oauth_store.py` |
| Phishing through a client name on the consent page | The page shows the redirect host and the account; `write` and `delete` are never preselected | `web/templates/consent.html` |
| Database leak | Sessions, passwords and snapshots are encrypted with a key that is not in the database; tokens are hashed | `crypto.py`, `db/snapshot_store.py` |
| Key compromise | Rotation with `SECRET_KEY_PREVIOUS` and `admin rotate-key` | `admin.py`, `tests/test_admin.py` |
| Prompt injection in page content | Content wrapped as untrusted data; titles and names outside the wrapper lose hidden and control characters and are cut at 300 characters, and the notice names them; scopes default to `read`; write tools take a snapshot first; delete only to Trash; space management only with the separate `admin` scope, and no removal of members or spaces; changes that widen who can read a page (moving or copying it to another space) and other risky changes ask the person through MCP elicitation, and fail closed when asking fails | `tools/untrusted.py`, `docmost/models.py`, `tools/write.py` |
| Irreversible overwrite | Snapshot before every body write; the write is not done if the snapshot fails; `restore_snapshot` | `tools/write.py`, `tests/test_write_tools.py` |
| Docmost accepting a write and dropping it | Read-back after every write; the call fails and names the snapshot | `tools/write.py` |
| A runaway agent hammering Docmost | `TOOL_CALLS_PER_MINUTE` per member over all clients; page and list size limits | `guard.py`, `tests/test_guard.py` |
| A download link reaching someone else | Links are encrypted and authenticated with the server key, name one member and one file, expire after ten minutes, and are served with `Content-Disposition: attachment`, `Content-Security-Policy: sandbox` and `no-store`; files are streamed, not stored | `web/downloads.py`, `tests/test_file_tools.py` |
| An upload link reaching someone else | A link is 256 random bits, stored only as a hash, names one member and one page, expires after `UPLOAD_RETENTION_MINUTES` and takes at most `UPLOAD_MAX_MB` and 50 files; files reach Docmost only when Done is pressed, after a snapshot, and the page keeps the busy-page guard; the page's script is same-origin only under a strict CSP | `web/uploads.py`, `tests/test_upload_links.py` |
| Large Docmost responses exhausting memory | Responses are read with a size limit (`DOCMOST_MAX_RESPONSE_BYTES`) and a timeout | `docmost/ce.py` |
| Secrets or content in logs | Logs carry ids only; a test checks that passwords, tokens, emails and page content do not appear | `tests/test_guard.py` |
| Admin space restriction bypassed | `ALLOWED_SPACES` is checked in every tool before it changes anything, including writes and restores from Trash; outside spaces answer like missing ones | `tools/spaces.py`, `tests/test_write_tools.py` |
| A member who should lose access | Members revoke grants on the account page, which also ends the download and upload links the grant made; the Admin can revoke grants, all grants of a member, or disable a member; removing an email from `ALLOWED_EMAILS` stops that member's tokens, web session and links at once | `web/routes.py`, `admin.py` |
| Container escape or tampering | Non-root user, read-only root filesystem, all capabilities dropped, `no-new-privileges` | `Dockerfile`, `compose.yaml` |
| Vulnerable dependencies | Locked dependencies, `pip-audit` in CI, Dependabot | `.github/workflows/ci.yml`, `.github/dependabot.yml` |

## Residual risks

- **Prompt injection** cannot be prevented by a server. A client with
  `write` or `delete` can be talked into changing or trashing pages the member
  can edit. Snapshots and the Trash make this recoverable, not impossible.
- **The Admin is trusted.** With `SECRET_KEY` and the database the Admin can
  decrypt sessions and snapshots and act as any member in Docmost.
- **Snapshots keep content** of pages that were later deleted or whose access
  was removed, until the retention period ends. Protect the database and its
  backups like Docmost's own.
- **Download links are bearer links.** Whoever has one can download that one
  file as the member until it expires, ten minutes after it was made, or
  the grant that made it is revoked. The
  server keeps links out of its access log; a reverse proxy in front of it may
  still log them.
- **Upload links are bearer links too.** Whoever has one can add files to
  that one page, as the member, until the link expires, Done is pressed or
  the grant that made it is revoked.
- **Rate limits are kept in memory** and reset on restart; run one server
  instance per Docmost.
- **The reverse proxy is outside this project.** A proxy that forwards plain
  http, or passes on an `X-Forwarded-For` sent by the client, weakens the
  sign-in and registration rate limits. The documented setups overwrite it.
- **OAuth client secrets** of confidential clients are stored as registered;
  most MCP clients are public clients without a secret and rely on PKCE.

## Operator checklist

- Serve `PUBLIC_URL` over https only, and publish port 8000 on loopback or a
  private network.
- Generate `SECRET_KEY` with `openssl rand -hex 32`; keep it out of git and
  backups of the database.
- Set `ALLOWED_EMAILS` if only some Docmost users should use the server, and
  `ALLOWED_SPACES` to keep AI clients away from sensitive spaces.
- Back up Postgres; it holds snapshots of page content.
- Review `docker compose exec server docmost-mcp-remote admin audit` from time
  to time.
