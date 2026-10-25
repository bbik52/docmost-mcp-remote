# 0004. Scopes, safe defaults, no permanent delete

## Status
Accepted

## Context
Page content can carry prompt injection, and a model can make mistakes. The audit showed that destructive-hint annotations do not protect anything, that body replacement is unrecoverable, and that no confirmation exists.

## Decision
- Grants carry scopes `read`, `write`, `delete`; default is `read`.
- v1 tools: reading and writing pages and comments. `delete` only moves to Trash and restores. Permanent deletion is never offered.
- Before overwriting a page body the server saves a Snapshot.
- Admin can restrict Members to a list of spaces.
- Page content is returned to the model wrapped and labelled as untrusted data.

## Consequences
- Prompt injection can still change pages within the granted scope; the design limits the damage, it does not remove the risk. This is stated in the README.
- Snapshots need storage and a retention policy.
