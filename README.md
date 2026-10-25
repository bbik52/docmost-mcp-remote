# docmost-mcp-remote

A remote [MCP](https://modelcontextprotocol.io) server for
[Docmost](https://docmost.com) Community Edition. Run it next to your Docmost,
put it behind your domain, and let AI clients such as Claude, Claude Code or
Cursor read and edit the wiki on behalf of each member, with that member's own
Docmost rights.

> **Status: pre-alpha.** The repository currently holds the project skeleton.
> No tools are available yet. See the [roadmap](docs/ROADMAP.md) for what comes
> next and when.

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
startup. The exact tested versions will be listed here once integration tests
are in place.

## Security model

Page content is treated as untrusted data and labelled as such for the model.
Prompt injection in a page can still make a client act within the scopes the
member granted, so grant `write` and `delete` only to clients you trust. See
[SECURITY.md](SECURITY.md) for how to report a vulnerability and
[docs/DESIGN.md](docs/DESIGN.md) for the design.

## Running it (development preview)

```sh
cp .env.example .env   # fill in PUBLIC_URL, DOCMOST_URL and POSTGRES_PASSWORD
docker compose up --build
curl http://localhost:8000/healthz
```

In production the server must sit behind a reverse proxy that terminates
https. `PUBLIC_URL` must be an https URL; plain http is only accepted for
`localhost`.

### Configuration

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `PUBLIC_URL` | yes | | Public https URL of this server |
| `DOCMOST_URL` | yes | | Base URL of your Docmost |
| `DOCMOST_ALLOW_INSECURE_HTTP` | no | `false` | Allow an `http://` `DOCMOST_URL` on a trusted private network |
| `DATABASE_URL` | no (yet) | | Postgres URL; becomes required with member sign-in |
| `HOST` / `PORT` | no | `0.0.0.0` / `8000` | Listen address |
| `LOG_LEVEL` | no | `info` | `debug`, `info`, `warning` or `error` |

## Development

```sh
uv sync
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE). This project is an independent implementation and is not
affiliated with Docmost. It was inspired by
[docmost-mcp-oss](https://github.com/abelsr/docmost-mcp-oss).
