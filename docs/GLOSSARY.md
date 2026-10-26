# Glossary

**Docmost** — the wiki application the server works with. Always one instance per deployment.

**CE / EE** — Docmost Community Edition (no official API) and Enterprise Edition (official API with API keys). Only CE is in scope for v1.

**MCP server** — this project: a network service that lets AI clients work with a Docmost through the Model Context Protocol.

**MCP client** — an AI application (Claude, Cursor, a script) that connects to the MCP server on behalf of one person.

**Member** — a person who has an account in the Docmost and uses the MCP server through an MCP client. Everything a Member does through the server is done as that Member in Docmost, with exactly their rights.

**Admin** — the person who deploys the MCP server and sets its policy (allowlist, default scopes, relogin mode).

**Allowlist** — optional list of Member emails that are allowed to sign in. Empty means every Docmost user may sign in.

**Grant** — the permission a Member gives one MCP client to act for them, limited by Scopes.

**Scope** — a class of operations a Grant allows: `read`, `write`, `delete`, `admin`. A new Grant is `read` only.

**Page content** — text of Docmost pages. Always treated as untrusted data, never as instructions for the model.

**Trash** — Docmost's recoverable deleted state. The server never deletes permanently.

**Snapshot** — copy of a page body taken by the server before it overwrites that body.

**Relogin mode** — Admin setting for what happens when a Member's Docmost session expires: ask the Member to sign in again (default), or use an encrypted stored password.
