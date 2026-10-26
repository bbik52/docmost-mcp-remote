# docmost-mcp-remote

**English** · [Русский](https://github.com/bbik52/docmost-mcp-remote/blob/master/README.ru.md)

[![CI](https://github.com/bbik52/docmost-mcp-remote/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/bbik52/docmost-mcp-remote/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/docmost-mcp-remote)](https://pypi.org/project/docmost-mcp-remote/)
[![Python](https://img.shields.io/pypi/pyversions/docmost-mcp-remote)](https://pypi.org/project/docmost-mcp-remote/)
[![Container](https://img.shields.io/badge/ghcr.io-docmost--mcp--remote-blue?logo=docker&logoColor=white)](https://github.com/bbik52/docmost-mcp-remote/pkgs/container/docmost-mcp-remote)
[![Docmost](https://img.shields.io/badge/Docmost%20CE-0.70%2B-6d28d9)](#supported-docmost-versions)
[![License](https://img.shields.io/badge/license-Apache--2.0-green)](https://github.com/bbik52/docmost-mcp-remote/blob/master/LICENSE)

A self-hosted remote [MCP](https://modelcontextprotocol.io) server for
[Docmost](https://docmost.com) Community Edition. Run it next to your Docmost,
put it behind your domain, and let AI clients such as Claude, Claude Code,
Cursor or VS Code read and edit the wiki on behalf of each member, with that
member's own Docmost account and rights.

> Independent community project, not affiliated with or endorsed by Docmost, Inc.
> Docmost is a trademark of Docmost, Inc.; the name is used only to say which
> software this server works with.

<!-- mcp-name: io.github.bbik52/docmost-mcp-remote -->

- **One server, one Docmost, many members.** Each member signs in with their
  own Docmost account in the browser. Everything their AI client does is done
  as them in Docmost.
- **Authorization is mandatory.** OAuth 2.1 for remote connectors and personal
  bearer tokens for scripts. There is no unauthenticated mode.
- **Safe by default.** `read` is the only scope granted without asking.
  Writing, moving to Trash and managing spaces need explicit scopes. Nothing is deleted
  permanently, and the server keeps an encrypted snapshot of a page body
  before every change.
- **Self-hosted.** One container plus Postgres, with a ready `compose.yaml`.

[Quick start](#quick-start) · [Connecting a client](#connecting-a-client) · [Tools](#tools) · [Resources and prompts](#resources-and-prompts) · [Security model](#security-model) · [Configuration](#configuration) · [Upgrading](#upgrading)

## How it works

```mermaid
flowchart LR
    member(["Member"]) -. "signs in once with<br/>their Docmost account" .-> server
    client["AI client<br/>Claude, Cursor, VS Code"] -- "MCP over https<br/>OAuth 2.1 or personal token" --> server["docmost-mcp-remote"]
    server -- "Docmost API,<br/>as that member" --> docmost["Docmost CE"]
    server --- db[("Postgres<br/>sessions, snapshots,<br/>audit log")]
```

The first time a client connects, the member signs in with their Docmost
email and password and picks what the client may do. They can see and revoke
every connected app and token on their account page.

<table>
<tr>
<td width="50%"><img src="https://raw.githubusercontent.com/bbik52/docmost-mcp-remote/master/docs/images/consent.png" alt="The consent page: allow Claude to use Docmost as you, with read, write, delete and admin scopes"></td>
<td width="50%"><img src="https://raw.githubusercontent.com/bbik52/docmost-mcp-remote/master/docs/images/account.png" alt="The account page with connected apps, personal tokens and the form to create a token"></td>
</tr>
<tr>
<td align="center">Choosing what a client may do</td>
<td align="center">Connected apps and personal tokens</td>
</tr>
</table>

## Supported Docmost versions

Docmost Community Edition **0.70.0 or newer**. Older versions are refused at
sign-in. CI runs the integration tests against Docmost 0.70.3, 0.96.0 and
0.97.0; newer releases work in most cases and log a warning until they are
added to the tested range. Docmost users who sign in with SSO only (an
Enterprise feature) cannot use this server: it signs in with email and
password. Labels and backlinks need Docmost 0.90 or newer, and the
`title_only` and `labels` search filters and `list_attachments` need 0.96 or
newer; on older versions these tools answer that Docmost needs an upgrade.

## Tools

| Tool | Scope | What it does |
|---|---|---|
| `whoami` | read | The Docmost account, scopes and Docmost version of this connection, and the link to the account page |
| `list_spaces` | read | Spaces you can access, with your role |
| `get_space` | read | One space: description, visibility, member count, your role |
| `list_pages` | read | Page tree of a space, one level at a time |
| `get_page_tree` | read | Several levels of the page tree in one call, within depth and size limits |
| `check_space_health` | read | Stale, empty and untitled pages, duplicate titles, broken links and top editors of a space |
| `recent_pages` | read | Recently updated pages |
| `get_page` | read | One page as Markdown, or as ProseMirror JSON with all formatting, by id, slug id or Docmost URL |
| `get_page_outline` | read | The headings of a page, to find a section without reading the whole body |
| `get_section` | read | One section of a page, with a hash for `replace_section` |
| `suggest` | read | Quick lookup of pages, people and groups by name |
| `search` | read | Full-text search with snippets; filters by title only, labels or your own pages |
| `list_comments` | read | Comments and replies on a page |
| `list_trash` | read | Pages in the Trash of a space |
| `list_snapshots` | read | Snapshots this server saved before your changes to a page |
| `list_page_history` | read | Versions of a page saved by Docmost, with who changed it |
| `get_page_version` | read | One saved version of a page as Markdown |
| `list_space_members` | read | Users and groups with a role in a space |
| `list_workspace_members` | read | People in the workspace, with their role |
| `list_groups` | read | Groups of the workspace |
| `diff_page` | read | Unified diff between the current body, a saved version or a snapshot |
| `list_backlinks` | read | Pages that link to a page, or that a page links to (Docmost 0.90+) |
| `list_labels` | read | Labels of the workspace or of one page (Docmost 0.90+) |
| `find_pages_by_label` | read | Pages with a label in a space (Docmost 0.90+) |
| `export_page` | read | A page as Markdown or HTML; with children or files, a download link to a zip |
| `export_space` | read | A download link to a zip of a whole space (space admins) |
| `list_attachments` | read | Files uploaded to a page (Docmost 0.96+) |
| `get_attachment` | read | Details of a file with a download link; small text files inline |
| `create_page` | write | New page with a Markdown body, optionally under a parent |
| `update_page` | write | Append, prepend or replace a page body with Markdown; `dry_run` shows a diff |
| `replace_section` | write | Replace one section of a page, refused if it changed since it was read |
| `rename_page` | write | Change a page title |
| `move_page` | write | Move a page within its space, to the start, the end or after a sibling |
| `move_page_to_space` | write | Move a page with its children to another space |
| `duplicate_page` | write | Copy a page with its children, in the same space or into another one |
| `add_comment` | write | Comment on a page or reply to a comment, optionally @-mentioning people, whom Docmost notifies |
| `update_comment` | write | Change the text of one of your own comments |
| `add_labels` | write | Add labels to a page (Docmost 0.90+) |
| `remove_label` | write | Remove a label from a page (Docmost 0.90+) |
| `upload_attachment` | write | Upload a file (base64, up to 10 MB) and add it to the end of the page |
| `replace_page_json` | write | Replace a page body with ProseMirror JSON, checked against the editor schema first; `dry_run` shows a diff |
| `restore_snapshot` | write | Put a page body back to a snapshot |
| `restore_page_version` | write | Put a page body back to a version from its history, formatting included |
| `trash_page` | delete | Move a page to the Trash |
| `restore_page` | delete | Restore a page from the Trash |
| `create_space` | admin | Create a space |
| `update_space` | admin | Change a space's name, slug or description |
| `add_space_members` | admin | Give users (by email) and groups (by name) a role in a space |
| `change_space_member_role` | admin | Change the role of a user or group in a space |

Page bodies, comments and snippets are returned inside a
`<docmost-untrusted-content>` envelope so the model treats them as data.

Before every body change the server saves the current body as a snapshot in
its own database, encrypted, for `SNAPSHOT_RETENTION_DAYS`; if the snapshot
cannot be saved, nothing is written. After the change it reads the page back
and reports an error if Docmost did not apply it (this happens when Docmost
runs with `COLLAB_DISABLE_REDIS`). Snapshots can hold content of pages that
were later deleted in Docmost until they expire.

A change that rewrites the whole body (a replace, a section, a JSON write, a
restore) is refused while someone else is editing the page, that is when
another person saved it in the last minute, because their typing would be
lost. Appending and prepending merge with their edits and are not refused.

## Resources and prompts

Besides tools, which the model picks itself, the server offers resources and
prompts that you pick in your client, where the client supports them (Claude
Desktop and Claude Code do; many clients only support tools).

| Resource | What it holds |
|---|---|
| `docmost://spaces` | The spaces you can access, with your role |
| `docmost://pages/{page}` | One page as Markdown, with its place and link. While you type a title, the client is offered matching pages |

| Prompt | Scope | What it asks for |
|---|---|---|
| `summarize_page` | read | A summary of a page: purpose, key points, what looks outdated |
| `summarize_space` | read | An overview of a space: what it covers, how it is organised, its gaps |
| `answer_from_wiki` | read | An answer only from wiki pages, with links to them |
| `whats_new` | read | What changed in the wiki or in a space in the last days, page by page |
| `draft_page` | write | A draft page on a topic, after checking for existing ones; created once you agree |
| `tidy_page` | write | Better structure and wording of a page without changing its facts; written once you agree |

A prompt only writes the request; the model does the work with the tools the
connection is allowed to use. Resource reads count against
`TOOL_CALLS_PER_MINUTE` and go to the audit log as `read_resource`.

## Security model

Members sign in with their own Docmost account; everything a client does is
done as that member, with their Docmost rights. The server keeps the Docmost
session token encrypted with a key derived from `SECRET_KEY` and does not
store passwords unless `RELOGIN_MODE=stored_password`. Personal tokens are
stored as hashes and shown once. The sign-in page has CSRF protection and
per-IP and per-email rate limits.

The server is its own OAuth 2.1 authorization server, following the MCP
authorization spec: dynamic client registration (limited per IP, redirect
URIs must be https, loopback http or a native app scheme), authorization
code with PKCE (S256 only), exact redirect URI match, tokens bound to this
server's `/mcp` resource, one-hour access tokens and 30-day refresh tokens
that rotate on every use. A reused refresh token or a replayed code revokes
the whole grant. OAuth grants and personal tokens are listed and revoked on
the same account page.

Page content is treated as untrusted data and labelled as such for the model.
Prompt injection in a page can still make a client act within the scopes the
member granted, so grant `write`, `delete` and `admin` only to clients you trust.
Tool calls and resource reads are limited per member and recorded in an
audit log.

Exports of several pages and file downloads are handed out as links to this
server that are valid for ten minutes. A link carries, encrypted, who asked
and what to download, so anyone holding it can download the file until it
expires; the server streams the file from Docmost with that member's session
and stores nothing. Links are kept out of the access log.

See the
[threat model](https://github.com/bbik52/docmost-mcp-remote/blob/master/docs/security-model.md), [SECURITY.md](https://github.com/bbik52/docmost-mcp-remote/blob/master/SECURITY.md) for
how to report a vulnerability and the [design](https://github.com/bbik52/docmost-mcp-remote/blob/master/docs/DESIGN.md).

## Quick start

You need Docker with Compose, a Docmost reachable from the server, and a host
name with https for the server itself, for example `mcp.example.com`.

1. Download the compose file and the settings template:

   ```sh
   mkdir docmost-mcp && cd docmost-mcp
   curl -fsSLO https://raw.githubusercontent.com/bbik52/docmost-mcp-remote/master/compose.yaml
   curl -fsSL -o .env https://raw.githubusercontent.com/bbik52/docmost-mcp-remote/master/.env.example
   ```

2. Edit `.env`: set `PUBLIC_URL` (the https URL of this server),
   `DOCMOST_URL`, a long random `POSTGRES_PASSWORD` and `SECRET_KEY`
   (`openssl rand -hex 32` gives a good value for both). Consider
   `ALLOWED_EMAILS` to limit who can sign in.

3. Start it and check that it is up:

   ```sh
   docker compose up -d
   curl http://127.0.0.1:8000/healthz
   ```

4. Put a reverse proxy with https in front of `127.0.0.1:8000` (see below)
   and open `PUBLIC_URL/login` in a browser to check that you can sign in with
   your Docmost account.

5. Connect a client (see [Connecting a client](#connecting-a-client)).

The server applies its database migrations at startup. Back up the Postgres
volume like you back up Docmost: it holds the encrypted sessions, the
snapshots and the audit log. Losing `SECRET_KEY` signs every member out and
makes the snapshots unreadable.

<details>
<summary>The <code>compose.yaml</code></summary>

```yaml
# docmost-mcp-remote: the server and its Postgres.
# Copy .env.example to .env and fill in the required values first, then put a
# reverse proxy with https in front of port 8000.

services:
  server:
    # "1" follows 1.x releases; set IMAGE_TAG to a full version such as 1.1.0 to pin one.
    image: ghcr.io/bbik52/docmost-mcp-remote:${IMAGE_TAG:-1}
    restart: unless-stopped
    environment:
      PUBLIC_URL: ${PUBLIC_URL:?set PUBLIC_URL to the public https URL of this server}
      DOCMOST_URL: ${DOCMOST_URL:?set DOCMOST_URL to the base URL of your Docmost}
      DOCMOST_ALLOW_INSECURE_HTTP: ${DOCMOST_ALLOW_INSECURE_HTTP:-false}
      DATABASE_URL: postgresql://docmost_mcp:${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD}@postgres:5432/docmost_mcp
      SECRET_KEY: ${SECRET_KEY:?set SECRET_KEY to a random value of at least 32 characters}
      SECRET_KEY_PREVIOUS: ${SECRET_KEY_PREVIOUS:-}
      ALLOWED_EMAILS: ${ALLOWED_EMAILS:-}
      ALLOWED_SPACES: ${ALLOWED_SPACES:-}
      RELOGIN_MODE: ${RELOGIN_MODE:-ask}
      SNAPSHOT_RETENTION_DAYS: ${SNAPSHOT_RETENTION_DAYS:-30}
      AUDIT_RETENTION_DAYS: ${AUDIT_RETENTION_DAYS:-90}
      TOOL_CALLS_PER_MINUTE: ${TOOL_CALLS_PER_MINUTE:-60}
      MAX_PAGE_CHARS: ${MAX_PAGE_CHARS:-60000}
      # The port is published on 127.0.0.1 only, so every client is a local proxy.
      FORWARDED_ALLOW_IPS: ${FORWARDED_ALLOW_IPS:-*}
      LOG_LEVEL: ${LOG_LEVEL:-info}
    ports:
      - "127.0.0.1:8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
    read_only: true
    tmpfs:
      - /tmp
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true

  postgres:
    image: postgres:17-alpine
    restart: unless-stopped
    environment:
      POSTGRES_USER: docmost_mcp
      POSTGRES_DB: docmost_mcp
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD}
    volumes:
      - postgres-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U docmost_mcp -d docmost_mcp"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  postgres-data:
```

</details>

The server is also on PyPI (`pip install docmost-mcp-remote` or
`uvx docmost-mcp-remote`) for setups without containers; it needs Postgres
and the same settings as environment variables.

## Reverse proxy

The server listens on plain http and expects a reverse proxy that terminates
https. Serve it at the root of its own host name; a sub-path is not
supported. The proxy must not buffer responses, because MCP streams them.

Caddy (gets certificates by itself):

```caddyfile
mcp.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

<details>
<summary>nginx</summary>

```nginx
server {
    listen 443 ssl;
    server_name mcp.example.com;
    ssl_certificate     /etc/letsencrypt/live/mcp.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/mcp.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_read_timeout 1h;
    }
}
```

</details>

The server uses `X-Forwarded-For` for its per-IP rate limits. The compose
file publishes the port on 127.0.0.1 only and trusts the header from every
client; if you publish the port elsewhere, set `FORWARDED_ALLOW_IPS` to the
proxy's address.

## Connecting a client

The MCP endpoint is `PUBLIC_URL/mcp`, for example
`https://mcp.example.com/mcp`. Clients that support MCP authorization open a
browser window: sign in with your Docmost email and password and choose what
the client may do. `read` is always granted; tick `write`, `delete` or
`admin` only for clients you trust.

**Claude.ai and Claude Desktop**: Settings, Connectors, Add custom connector,
then enter the endpoint URL. The server must be reachable from the internet
over https for Claude.ai.

**Claude Code**:

```sh
claude mcp add --transport http docmost https://mcp.example.com/mcp
```

Then run `/mcp` in Claude Code to sign in.

**Cursor** (`~/.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "docmost": { "url": "https://mcp.example.com/mcp" }
  }
}
```

**VS Code** (`.vscode/mcp.json`):

```json
{
  "servers": {
    "docmost": { "type": "http", "url": "https://mcp.example.com/mcp" }
  }
}
```

**With a personal token** (scripts and clients without OAuth):

1. Open `PUBLIC_URL/login` and sign in with your Docmost email and password.
2. On the account page, create a personal token with the scopes you need.
3. Configure the client with the endpoint and the header
   `Authorization: Bearer <token>`:

   ```sh
   claude mcp add --transport http docmost https://mcp.example.com/mcp \
     --header "Authorization: Bearer dmr_..."
   ```

Connected apps and tokens are listed and revoked on the account page,
`PUBLIC_URL/account`.

## Administration

The `admin` command runs where the server runs, with the same environment:

```sh
docker compose exec server docmost-mcp-remote admin members
docker compose exec server docmost-mcp-remote admin migrate
docker compose exec server docmost-mcp-remote admin grants anna@example.com
docker compose exec server docmost-mcp-remote admin revoke-grant <grant id>
docker compose exec server docmost-mcp-remote admin revoke-member anna@example.com
docker compose exec server docmost-mcp-remote admin disable-member anna@example.com
docker compose exec server docmost-mcp-remote admin audit --email anna@example.com
```

`revoke-member` revokes every grant of the member and drops their stored
Docmost session; `disable-member` blocks them until `enable-member`. Every
tool call and resource read is recorded in the audit log with the tool, the page or space id
and the outcome, never with content or arguments.

To rotate `SECRET_KEY`: set the old value as `SECRET_KEY_PREVIOUS` and a new
`SECRET_KEY`, restart, run `admin rotate-key`, then remove
`SECRET_KEY_PREVIOUS` and restart again.

## Upgrading

1. Read the [changelog](https://github.com/bbik52/docmost-mcp-remote/blob/master/CHANGELOG.md)
   for "Upgrade notes".
2. Back up the database:

   ```sh
   docker compose exec -T postgres pg_dump -U docmost_mcp -Fc docmost_mcp > docmost-mcp-$(date +%F).dump
   ```

3. Pull the new image and restart:

   ```sh
   docker compose pull && docker compose up -d
   ```

The server upgrades its database schema at startup, in one transaction and
one process at a time, so a failed upgrade leaves the old schema in place.
`docker compose exec server docmost-mcp-remote admin migrate` shows the
schema revision.

The image tag `1` follows 1.x releases; set `IMAGE_TAG` in `.env` to pin a
version. Going back to an older version after its schema was upgraded is not
supported: an older server refuses to start on a newer schema. To roll back,
restore the backup with the old image:

```sh
docker compose stop server
docker compose exec -T postgres pg_restore -U docmost_mcp -d docmost_mcp --clean --if-exists < docmost-mcp-2026-01-31.dump
IMAGE_TAG=1.1.0 docker compose up -d
```

## Configuration

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `PUBLIC_URL` | yes | | Public https URL of this server |
| `DOCMOST_URL` | yes | | Base URL of your Docmost |
| `DOCMOST_ALLOW_INSECURE_HTTP` | no | `false` | Allow an `http://` `DOCMOST_URL` on a trusted private network |
| `DATABASE_URL` | yes | | Postgres URL (`postgresql://user:password@host/db`) |
| `SECRET_KEY` | yes | | At least 32 characters; encrypts stored Docmost sessions and signs cookies |
| `SECRET_KEY_PREVIOUS` | no | | The old key during a rotation |
| `ALLOWED_EMAILS` | no | empty | Comma-separated emails allowed to sign in; empty allows every Docmost user |
| `ALLOWED_SPACES` | no | empty | Comma-separated space slugs or ids members may use through this server; empty allows all |
| `MAX_PAGE_CHARS` | no | `60000` | Longest page body returned; longer bodies are truncated |
| `SNAPSHOT_RETENTION_DAYS` | no | `30` | Days a snapshot of a page body is kept |
| `AUDIT_RETENTION_DAYS` | no | `90` | Days an audit log entry is kept |
| `TOOL_CALLS_PER_MINUTE` | no | `60` | Tool calls and resource reads one member may make per minute, over all their clients |
| `WEB_SESSION_HOURS` | no | `12` | Hours a sign-in to the account page lasts |
| `RELOGIN_MODE` | no | `ask` | `ask`: members sign in again when their Docmost session expires; `stored_password`: the password is kept encrypted and used to sign in again |
| `DOCMOST_TIMEOUT_SECONDS` | no | `15` | Timeout for one request to Docmost |
| `DOCMOST_MAX_RESPONSE_BYTES` | no | `5242880` | Largest Docmost response the server reads |
| `FORWARDED_ALLOW_IPS` | no | `127.0.0.1` | Proxies trusted for `X-Forwarded-For` (`*` in the compose file) |
| `HOST` / `PORT` | no | `0.0.0.0` / `8000` | Listen address |
| `LOG_LEVEL` | no | `info` | `debug`, `info`, `warning` or `error` |
| `IMAGE_TAG` | no | `1` | Image tag used by `compose.yaml` |

## Development

```sh
uv sync
uv run ruff check . && uv run ruff format --check .
uv run mypy
DATABASE_TEST_URL=postgresql://test:test@localhost:5433/test uv run pytest
```

Tests that need Postgres are skipped without `DATABASE_TEST_URL`; for example
`docker run -d -p 5433:5432 -e POSTGRES_USER=test -e POSTGRES_PASSWORD=test postgres:17-alpine`.

Integration tests run against a real Docmost:

```sh
DOCMOST_VERSION=0.97.0 docker compose -f tests/integration/compose.yaml up -d
DOCMOST_TEST_URL=http://localhost:3000 uv run pytest tests/integration
```

To run the compose stack with a local build:

```sh
docker build -t ghcr.io/bbik52/docmost-mcp-remote:dev .
IMAGE_TAG=dev docker compose up -d
```

See [CONTRIBUTING.md](https://github.com/bbik52/docmost-mcp-remote/blob/master/CONTRIBUTING.md) and the [roadmap](https://github.com/bbik52/docmost-mcp-remote/blob/master/docs/ROADMAP.md).

## License

[Apache License 2.0](https://github.com/bbik52/docmost-mcp-remote/blob/master/LICENSE). The license does not cover the project
name: forks are welcome under another name. This project is an independent
implementation and is not affiliated with Docmost. It was inspired by
[docmost-mcp-oss](https://github.com/abelsr/docmost-mcp-oss).
