# docmost-mcp-remote

A remote [MCP](https://modelcontextprotocol.io) server for
[Docmost](https://docmost.com) Community Edition. Run it next to your Docmost,
put it behind your domain, and let AI clients such as Claude, Claude Code or
Cursor read and edit the wiki on behalf of each member, with that member's own
Docmost rights.

> **Status: pre-alpha.** Members can connect OAuth clients or personal tokens
> and read and edit their Docmost through the tools below. Security hardening
> and the 1.0.0 release are next; see the [roadmap](docs/ROADMAP.md).

## Tools

| Tool | Scope | What it does |
|---|---|---|
| `whoami` | read | The Docmost account, scopes and Docmost version of this connection |
| `list_spaces` | read | Spaces you can access, with your role |
| `list_pages` | read | Page tree of a space, one level at a time |
| `recent_pages` | read | Recently updated pages |
| `get_page` | read | One page as Markdown, by id, slug id or Docmost URL |
| `search` | read | Full-text search with snippets |
| `list_comments` | read | Comments and replies on a page |
| `list_trash` | read | Pages in the Trash of a space |
| `list_snapshots` | read | Snapshots this server saved before your changes to a page |
| `create_page` | write | New page with a Markdown body, optionally under a parent |
| `update_page` | write | Append, prepend or replace a page body with Markdown |
| `rename_page` | write | Change a page title |
| `move_page` | write | Move a page within its space, to the start, the end or after a sibling |
| `add_comment` | write | Comment on a page or reply to a comment |
| `restore_snapshot` | write | Put a page body back to a snapshot |
| `trash_page` | delete | Move a page to the Trash |
| `restore_page` | delete | Restore a page from the Trash |

Page bodies, comments and snippets are returned inside a
`<docmost-untrusted-content>` envelope so the model treats them as data.

Before every body change the server saves the current body as a snapshot in
its own database, encrypted, for `SNAPSHOT_RETENTION_DAYS`; if the snapshot
cannot be saved, nothing is written. After the change it reads the page back
and reports an error if Docmost did not apply it (this happens when Docmost
runs with `COLLAB_DISABLE_REDIS`). Snapshots can hold content of pages that
were later deleted in Docmost until they expire. Pages are never deleted
permanently.

## What it will do

- **One server, one Docmost, many members.** Each member signs in with their
  own Docmost account in the browser. Everything they do through an AI client
  is done as them in Docmost.
- **Authorization is mandatory.** OAuth 2.1 for remote connectors and personal
  bearer tokens for scripts. There is no unauthenticated mode.
- **Safe by default.** New grants are read-only. Writing and moving to Trash
  need explicit scopes. The server never deletes permanently and keeps a
  snapshot of a page body before it overwrites it.
- **Self-hosted.** A plain `compose.yaml` with the server and Postgres.

## Supported Docmost versions

Docmost Community Edition **0.70.0 or newer**. Older versions are refused at
sign-in. CI runs the integration tests against Docmost 0.70.3, 0.96.0 and
0.97.0; newer releases work in most cases and log a warning until they are
added to the tested range.

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
member granted, so grant `write` and `delete` only to clients you trust. See
[SECURITY.md](SECURITY.md) for how to report a vulnerability and
[docs/DESIGN.md](docs/DESIGN.md) for the design.

## Running it (development preview)

```sh
cp .env.example .env   # fill in PUBLIC_URL, DOCMOST_URL, POSTGRES_PASSWORD, SECRET_KEY
docker compose up --build -d
curl http://localhost:8000/healthz
```

The server applies its database migrations at startup. In production it
must sit behind a reverse proxy that terminates https. `PUBLIC_URL` must be
an https URL; plain http is only accepted for `localhost`.

### Connecting a client

**With OAuth** (Claude.ai and Claude Desktop connectors, Claude Code, Cursor,
VS Code and other clients that support MCP authorization): add a remote MCP
server with the URL `PUBLIC_URL/mcp`, for example
`https://mcp.example.com/mcp`. The client opens a browser window; sign in with
your Docmost email and password and choose what the client may do. `read` is
always granted; tick `write` or `delete` only for clients you trust.

```sh
claude mcp add --transport http docmost https://mcp.example.com/mcp
```

**With a personal token** (scripts and clients without OAuth):

1. Open `PUBLIC_URL/login` and sign in with your Docmost email and password.
2. On the account page, create a personal token with the scopes you need.
3. Configure the client with the MCP endpoint `PUBLIC_URL/mcp` and the header
   `Authorization: Bearer <token>`:

   ```sh
   claude mcp add --transport http docmost https://mcp.example.com/mcp \
     --header "Authorization: Bearer dmr_..."
   ```

Connected apps and tokens can be revoked on the account page.

### Configuration

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
| `RELOGIN_MODE` | no | `ask` | `ask`: members sign in again when their Docmost session expires; `stored_password`: the password is kept encrypted and used to sign in again |
| `DOCMOST_TIMEOUT_SECONDS` | no | `15` | Timeout for one request to Docmost |
| `DOCMOST_MAX_RESPONSE_BYTES` | no | `5242880` | Largest Docmost response the server reads |
| `FORWARDED_ALLOW_IPS` | no | `127.0.0.1` | Proxies trusted for `X-Forwarded-For` (`*` in the compose file) |
| `HOST` / `PORT` | no | `0.0.0.0` / `8000` | Listen address |
| `LOG_LEVEL` | no | `info` | `debug`, `info`, `warning` or `error` |

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

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE). This project is an independent implementation and is not
affiliated with Docmost. It was inspired by
[docmost-mcp-oss](https://github.com/abelsr/docmost-mcp-oss).
