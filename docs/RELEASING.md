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
- **Image visibility**: a new ghcr.io package is private. After the first
  release pushed the image, open the package settings and make it public,
  then re-run the failed `mcp-registry` job: the registry checks the image
  label and needs to read the image.
- **Repository**: description and topics `mcp`, `mcp-server`, `docmost`,
  `model-context-protocol`, `oauth`, `wiki`, `self-hosted`; branch protection
  as described in DESIGN.md, "Contributions and project security".

## Cutting a release

1. Branch `release/X.Y.Z` from `develop`.
2. Set the version in `pyproject.toml` and in `server.json` (`version`, the
   PyPI package `version` and the image tag in the OCI `identifier`), then
   run `uv lock`.
3. In `CHANGELOG.md`, rename `## [Unreleased]` to `## [X.Y.Z] - YYYY-MM-DD`
   and add a new empty `## [Unreleased]` above it.
4. `uv run pytest tests/test_release_metadata.py` checks that these files
   agree.
5. Open a pull request from `release/X.Y.Z` to `master`. When CI is green,
   merge it with a merge commit.
6. Tag the merge commit and push the tag:

   ```sh
   git checkout master && git pull
   git tag -a vX.Y.Z -m "X.Y.Z"
   git push origin vX.Y.Z
   ```

7. Watch the Release workflow. It refuses a tag that does not match the
   project version, is not on `master` or has no changelog entry.
8. Merge `master` back into `develop`.

A failed job can be re-run from the Actions page; PyPI, ghcr.io and the
registry do not accept the same version twice with different content, so a
broken release is fixed with a new patch version, not by moving the tag.
