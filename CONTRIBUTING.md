# Contributing

Thanks for your interest. Issues and pull requests are welcome.

## Ground rules

- **Clean implementation.** Do not copy code, structure or tool descriptions
  from docmost-mcp-oss or from Docmost (AGPL-3.0). Write from the observed
  behavior of the Docmost HTTP API. See
  [ADR 0001](docs/adr/0001-new-repository-from-scratch.md).
- **English** for code, comments, docs, commit messages and pull requests.
- Security-relevant changes need tests. Never log passwords, tokens, page
  content or tool arguments.
- Larger design changes start with an issue or an ADR in `docs/adr/`.

## Setup

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12 or newer.

```sh
uv sync
uv run pytest
```

Before pushing:

```sh
uv run ruff format .
uv run ruff check .
uv run mypy
uv run pytest
```

## Pull requests

- The repository uses git flow. Branch from `develop` as `feature/<topic>`
  (or `bugfix/<topic>`) and open the pull request against `develop`.
  `master` only receives `release/*` and `hotfix/*` merges and holds tagged
  releases.
- One topic per pull request.
- Describe what changed and why; link the roadmap phase or issue.
- CI must be green.
