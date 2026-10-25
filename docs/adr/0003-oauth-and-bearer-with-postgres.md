# 0003. OAuth 2.1 and bearer tokens, state in Postgres

## Status
Accepted

## Context
Remote MCP clients such as Claude.ai connectors only support the OAuth flow from the MCP specification. Scripts and Claude Code are simpler with static tokens. State (clients, tokens, encrypted sessions) must survive restarts.

## Decision
Support both: OAuth 2.1 (authorization code with PKCE, dynamic client registration, refresh tokens) and personal bearer tokens issued to a Member. Both produce the same Grant with Scopes. State lives in Postgres.

## Consequences
- More attack surface than bearer-only; OAuth must follow the spec strictly (exact redirect URI match, PKCE required, audience binding, short-lived access tokens).
- Postgres is a required dependency of every deployment; the compose file ships with one.
- Bearer tokens are stored hashed, shown once, revocable.
