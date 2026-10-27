# Releasing

Releases are cut from `develop` with git flow and published by
[`.github/workflows/release.yml`](../.github/workflows/release.yml) when a tag
`vX.Y.Z` is pushed. The workflow publishes:

1. the package to PyPI (trusted publishing, no token),
2. the image to `ghcr.io/bbik52/docmost-mcp-remote` for linux/amd64 and
   linux/arm64, tagged `X.Y.Z`, `X.Y`, `X` and `latest`,
3. a GitHub release with the changelog entry and the built package,
4. the entry `io.github.bbik52/docmost-mcp-remote` in the official
   [MCP Registry](https://registry.modelcontextprotocol.io), from
   `server.json`.

Release artifacts are not signed yet (ADR 0006).

## One-time setup

- **PyPI**: on <https://pypi.org/manage/account/publishing/> add a pending
  trusted publisher: project `docmost-mcp-remote`, owner `bbik52`,
  repository `docmost-mcp-remote`, workflow `release.yml`, environment
  `pypi`.
- **GitHub environment**: Settings, Environments, `pypi`. Limit it to tags
  `v*` and, if you like, require your approval before each PyPI upload.
- **Image visibility**: the package `ghcr.io/bbik52/docmost-mcp-remote`
  is public, like the repository. It must stay public: the registry reads
  the image to check its label.
- **Repository**: description and topics `mcp`, `mcp-server`, `docmost`,
  `model-context-protocol`, `oauth`, `wiki`, `self-hosted`; branch protection
  as described in DESIGN.md, "Contributions and project security".
- **Glama**: claim the server on <https://glama.ai/mcp/servers> with the
  GitHub account named in `glama.json`. In its admin Dockerfile settings use
  the build steps
  `["uv pip install --python /usr/local/bin/python --break-system-packages ."]`
  and the CMD arguments
  `["python", "-m", "docmost_mcp_remote", "--tool-catalog"]`, with no
  environment variables. Glama's image links a uv-managed Python to
  `/usr/local/bin/python`; it has no `pip`, is marked as externally managed,
  and `uv pip --system` may pick another interpreter, hence the explicit
  `--python` and the flag. Glama
  also refuses a command containing `mcp-remote`, mistaking it for the npm
  proxy of that name. The catalog mode lists the tools without Docmost or a
  database.

## Cutting a release

1. Branch `release/X.Y.Z` from `develop`. Check that the READMEs (both
   languages), `docs/` and the configuration examples describe what the
   release changes, and fix them first.
2. Set the version in `pyproject.toml` and in `server.json` (`version`, the
   PyPI package `version` and the image tag in the OCI `identifier`), then
   run `uv lock`.
3. If the release adds migrations, check that `tests/test_migrations.py`
   passes and add "Upgrade notes" to the changelog when a migration is slow
   or needs the Admin to do something.
4. In `CHANGELOG.md`, rename `## [Unreleased]` to `## [X.Y.Z] - YYYY-MM-DD`
   and add a new empty `## [Unreleased]` above it.
5. `uv run pytest tests/test_release_metadata.py` checks that these files
   agree.
6. Open a pull request from `release/X.Y.Z` to `master`. When CI is green,
   merge it with a merge commit.
7. Tag the merge commit and push the tag:

   ```sh
   git checkout master && git pull
   git tag -a vX.Y.Z -m "X.Y.Z"
   git push origin vX.Y.Z
   ```

8. Watch the Release workflow. It refuses a tag that does not match the
   project version, is not on `master` or has no changelog entry.
9. Merge `master` back into `develop`.
10. On Glama, open the server's admin Dockerfile page, press Deploy, wait for
    the test to pass, then Make Release, so Glama lists the new version.

`release.yml` only runs on tags, so a mistake in it shows up at release
time. When changing it, check that every action reference exists (a pinned
commit or an existing tag).

A failed job can be re-run from the Actions page; PyPI, ghcr.io and the
registry do not accept the same version twice with different content, so a
broken release is fixed with a new patch version, not by moving the tag.
