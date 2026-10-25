# 0002. Each Member acts under their own Docmost account

## Status
Accepted

## Context
Options: one shared service account, or each Member's own account. A shared account gives everyone the same rights and hides the real author in the Docmost audit trail.

## Decision
One server serves one Docmost and many Members. A Member signs in on the server's login page with their Docmost email and password; the server stores only the Docmost token, encrypted. The password is not stored by default. An Admin flag can switch to an encrypted stored password for automatic relogin (see Relogin mode in the glossary).

## Consequences
- Rights and authorship in Docmost are correct without extra work.
- The server sees passwords at login, so the login page needs CSRF protection, rate limiting and no password logging.
- Docmost SSO users are not supported in v1 (SSO is an EE feature).
- Docmost URL is fixed in server config, so there is no SSRF through user-supplied URLs.
