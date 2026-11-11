# OAuth callback allowlist

`OAUTH_REDIRECT_ALLOWLIST` is optional and empty by default. Use it to limit
the callback addresses OAuth clients may register. A client chooses its own
name, so a familiar name on the consent page does not prove who operates it.

```dotenv
# Default: keep registration open to supported redirect URIs.
OAUTH_REDIRECT_ALLOWLIST=
```

With a non-empty list, non-loopback callbacks must match a listed URI exactly,
including the path and query. There are no domain rules, prefixes or wildcards.
HTTP loopback callbacks (`localhost`, `127.0.0.1` and `[::1]`, on any port)
remain allowed without an entry. Custom app schemes need an exact entry when
the list is enabled. User info (`user@host`) and fragments are refused.

## Common clients

Checked on 2026-11-11 against the linked vendor documentation and metadata.
These are callback references, not a compatibility certification for every
client version. The application that runs the MCP client determines the
callback, rather than the language model selected in that application.

| Client | Callback URI | What to add when enabling the allowlist |
|---|---|---|
| Claude web and Claude Desktop remote connectors | `https://claude.ai/api/mcp/auth_callback`; `https://claude.com/api/mcp/auth_callback` is a previously documented compatibility address | Add the Claude callbacks you use. The current [published metadata](https://claude.ai/oauth/mcp-oauth-client-metadata) lists the `claude.ai` address; [Databricks' Claude connector setup](https://docs.databricks.com/aws/en/ai-gateway/coding-agent-claude-desktop#connect-mcp-tools-with-your-claude-account) lists both addresses. |
| ChatGPT | `https://chatgpt.com/connector/oauth/{callback_id}` or `https://chatgpt.com/connector_platform_oauth_redirect` | Copy the exact production URI from the MCP server's management page. Do not paste `{callback_id}` literally. The stable address applies to issuer-bound responses and older connections; see [OpenAI's redirect rules](https://developers.openai.com/plugins/build/auth#redirect-url). |
| Cursor desktop, web and agents | `https://www.cursor.com/agents/mcp/oauth/callback` and `http://localhost:8787/callback` | Add the HTTPS address. Loopback is already allowed. Desktop dynamic registration includes both addresses and can use the web callback; see [Cursor's redirect rules](https://cursor.com/docs/mcp#static-redirect-url). |
| GitHub Copilot in VS Code | `https://vscode.dev/redirect` and `http://127.0.0.1:33418` | Add `https://vscode.dev/redirect`. Loopback is already allowed; see [VS Code's OAuth guidance](https://code.visualstudio.com/api/extension-guides/ai/mcp#authorization). |
| Claude Code | `http://localhost:<port>/callback` | No entry for the default local flow. The port is chosen at login or fixed with `--callback-port`; see [Claude Code's callback guidance](https://code.claude.com/docs/en/mcp#use-a-fixed-oauth-callback-port). |
| Codex CLI | `http://127.0.0.1:<port>/callback`, optionally with a server-specific callback ID appended | No entry for the default local flow. A custom remote callback needs its exact URI; see [Codex's callback rules](https://learn.chatgpt.com/docs/extend/mcp). |
| Gemini CLI | `http://localhost:<port>/oauth/callback` | No entry for the default local flow. A custom `oauth.redirectUri` outside loopback needs its exact URI; see [Gemini CLI's OAuth configuration](https://geminicli.com/docs/tools/mcp-server/). |

## Example for several clients

This example allows Claude remote connectors, Cursor and VS Code, plus the
default local callbacks of the CLI clients above. Enable only the clients
your deployment needs; listing a callback grants no Docmost access by itself.
Members still sign in and approve scopes.

```dotenv
# Optional: replace the empty value with this single line.
OAUTH_REDIRECT_ALLOWLIST=https://claude.ai/api/mcp/auth_callback,https://claude.com/api/mcp/auth_callback,https://www.cursor.com/agents/mcp/oauth/callback,https://vscode.dev/redirect
```

For ChatGPT, append the exact URI shown for your connection. Use
`https://chatgpt.com/connector_platform_oauth_redirect` only if that is the URI
shown; otherwise append the complete callback-ID-specific URI. Do not allow
the whole `chatgpt.com` domain or use a `*` placeholder.

## Apply and troubleshoot

1. Choose the clients your users need and set the comma-separated list in `.env`.
2. Recreate the server to apply the environment change:
   `docker compose up -d --force-recreate server`.
3. Connect each intended client again. All URIs it registers must be allowed,
   even if it only uses one of them during the current login.

If registration answers `invalid_redirect_uri`, inspect the client's
`redirect_uris` registration field or the `redirect_uri` parameter on its
authorization request. Compare it with the vendor's documentation and your
exact entries. Do not copy the rest of an authorization URL into the list or
share authorization codes, tokens or the `state` value.

Existing clients are filtered against the list when loaded, so their removed
callback addresses cannot start a new authorization. This setting does not
revoke existing grants, access tokens or refresh tokens, and is not a switch
to disable local clients. Revoke unwanted connections on the account page or
through the admin commands.

Clients using a personal token in an `Authorization: Bearer` header do not use
an OAuth callback and are not affected by this setting.
