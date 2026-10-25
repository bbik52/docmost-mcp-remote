# 0001. New repository, written from scratch; docmost-mcp-oss as a reference only

## Status
Accepted. Replaces the earlier decision to fork and rework.

## Context
`abelsr/docmost-mcp-oss` (Python, FastMCP, MIT) solves the CE-specific parts: the internal Docmost REST API and, in older Docmost versions, page body editing through a Yjs WebSocket. It is built for one local user over stdio, and its HTTP mode has no authentication. The project is small (0 stars, 1 maintainer), so large upstream changes are unlikely to be merged.

Since Docmost v0.70.0 the body can be updated through `POST /api/pages/update`, so the most specific part of the original (the Yjs client and the temporary page) is not needed. What remains of value is a plain REST client and a list of tools, both of which this project has to redesign for multiple users, scopes and OAuth.

## Decision
- A new repository `docmost-mcp-remote` with its own history, on branch `master`.
- The code is written from scratch. The original is used only to learn which Docmost endpoints exist and how they behave. Ideas, endpoint lists and observed behavior are not protected; code, structure and tool descriptions are not copied.
- If any code or text from the original is copied after all, the MIT notice and the copyright line of Abel Santillan Rodriguez are kept for that part (a `NOTICE` file). The project license is MIT, so the two are compatible.
- Credit in the README ("inspired by docmost-mcp-oss") is a courtesy, not an obligation.
- Nothing is copied from the Docmost repository (AGPL-3.0, and its `ee` directories are under a separate license). We talk to Docmost over HTTP only.
- The audit findings are reported to the original author as issues, independent of this decision.

## Consequences
- Clean license position and a clean history; no inherited stdio-first architecture.
- Slower start: the REST client and the tools are written again.
- The clean-implementation rule must be followed in practice: write from the Docmost API behavior and docs, not from the original's source open next to the editor.
