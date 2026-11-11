# Project instructions

Read `CONTRIBUTING.md` before making changes.

## Credit for external contributions

The maintainer wants human contributors to receive visible GitHub credit when
their fork changes are incorporated, including in the repository Contributors
list when requested.

- Distinguish the PR author, primary Git author, commit co-authors, profile
  contributions and the repository Contributors list. They are not equivalent.
- On GitHub.com, a `Co-authored-by` trailer credits a co-author but does not
  reliably place them in the repository Contributors list. Do not promise that
  it will. Repository contributor statistics depend on the default branch
  (`master` here); merging only into `develop` is not sufficient.
- When the maintainer authorizes primary-author attribution for an imported
  contribution, use that contributor's verified GitHub-linked email or their
  GitHub noreply address. Preserve source provenance (`cherry-pick -x`) and
  appropriate co-author trailers. Do not silently change author identities.
- Verify GitHub resolves the imported commit's author to the intended account.
  Keep primary authorship and co-author trailers intact when choosing a merge
  strategy; a squash can replace the primary author. Contributor statistics
  may take time to update after the commit reaches the default branch.
- For an authorized rewrite of a published PR branch, check for remote changes,
  verify the file tree is unchanged when only attribution is being corrected,
  and push with `--force-with-lease` against the observed remote commit.
