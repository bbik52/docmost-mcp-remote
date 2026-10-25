# Security policy

## Supported versions

Until 1.0.0 only the latest release and `master` receive security fixes.
After 1.0.0 the latest minor release is supported.

## Reporting a vulnerability

Please do **not** open a public issue for security problems.

Report privately through
[GitHub security advisories](https://github.com/bbik52/docmost-mcp-remote/security/advisories/new).
Include the version or commit, your deployment setup (without secrets), the
steps to reproduce and the impact you expect.

You can expect an acknowledgement within 7 days. We will keep you informed
while we work on a fix and credit you in the advisory unless you prefer
otherwise.

## Scope

In scope: this server's code, its container image, its default `compose.yaml`
and its documentation.

Out of scope: vulnerabilities in Docmost itself (report them to the Docmost
project), in MCP clients, or in a reverse proxy you put in front of the server.

## Security model in short

- Authorization is mandatory; there is no unauthenticated mode.
- Each member acts in Docmost with their own account and rights.
- The server stores Docmost session tokens encrypted and personal tokens
  hashed. Passwords are not stored unless the Admin enables automatic relogin.
- Page content is untrusted data. Prompt injection can still cause actions
  within the scopes a member granted; scopes, snapshots and Trash-only delete
  limit the damage.
- Logs never contain passwords, tokens, page content or tool arguments.

Details are in [docs/DESIGN.md](docs/DESIGN.md).
