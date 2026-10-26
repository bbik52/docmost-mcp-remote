# Docmost CE API notes

What this server relies on, observed against running Docmost releases
0.70.3, 0.96.0 and 0.97.0 (2026-10-25). Written from observed HTTP
behavior; the integration tests in `tests/integration/` check it on every
CI run. Nothing here is copied from Docmost or from other clients.

## Transport

- Every endpoint is `POST /api/<path>` with a JSON body, also for reads.
  A `GET` on most paths returns the web app's HTML, so the client checks the
  content type before parsing.
- Success: `{"data": <payload>, "success": true, "status": 200}`. Some calls
  (`pages/delete`, `pages/move`) answer without `data`.
- Errors: `{"message": <string or list of strings>, "statusCode": <n>}`.
- `GET /api/health` is public and reports database and Redis status. It is
  the only call the server makes without a member's session.

## Authentication

- `POST /api/auth/login` with `{"email", "password"}` sets an `authToken`
  cookie (a JWT, valid about 90 days) and returns no token in the body.
- The same token is accepted as `Authorization: Bearer <token>`. The server
  uses the header and never keeps a cookie jar.
- Wrong password and unknown email both answer `401` with the same message.
- Sign-in is rate limited by Docmost to about 10 requests per minute
  (`x-ratelimit-*-auth` headers). The server must not retry sign-ins.
- An invalid or expired token answers `401 Unauthorized` on every endpoint.

## Version

- `POST /api/version` returns `{"currentVersion": "0.97.0", ...}` and
  **requires a session**. There is no public version endpoint.
- Consequence: the server cannot check the version at startup. It checks
  reachability (`/api/health`) at startup and the version at each Member
  sign-in; sign-in to a Docmost older than 0.70.0 is refused.

## Pagination

- List endpoints take `limit` (1–100; larger values answer `400`) and an
  opaque `cursor`. Answers carry `meta.nextCursor` and `meta.hasNextPage`.
  `cursor: null` is accepted.
- `search` returns `items` without `meta`.

## Markdown export by version

- Before 0.97, `pages/info` with `format: "markdown"` writes a table's
  header row as an empty row followed by the header cells as a body row, so
  a body sent back to Docmost changes its tables. `replace_section` reports
  this as text changed outside the section.

## Pages

- `pages/info` with `{"pageId", "format": "markdown"}` returns the body as a
  Markdown string in `content` (without the title). Without `format` the body
  is ProseMirror JSON. `pageId` also accepts the short `slugId`.
- `pages/create` takes `spaceId`, `title`, optional `parentPageId`, and an
  optional body as `content` + `format: "markdown"`.
- `pages/update` with `content`, `operation` (`append`, `prepend`,
  `replace`) and `format: "markdown"` changes the body; with `title` it
  renames. The change was visible to `pages/info` within about 0.1 s.
- `replace` drops the whole previous body.
- **Silent no-op:** with `COLLAB_DISABLE_REDIS=true` on the Docmost side, a
  body update answers `200` and changes nothing. Title updates still work.
  The server therefore reads the page back after every body write.
- `pages/sidebar-pages` lists root pages of a space, or the children of
  `pageId`. Items have `hasChildren` and `position`.
- `pages/breadcrumbs` returns the path from the root to the page.
- `pages/recent` lists recently updated pages, optionally in one space.
- `pages/move` needs `parentPageId` (or `null` for root) and a `position`:
  a fractional-index key, 5–12 characters, validated by Docmost
  (`Invalid move position` otherwise). Existing keys look like `a01bz` or
  `a17AT`: an integer part whose first letter encodes its length (`a` = two
  characters), a base-62 fraction, and siblings sorted by plain byte order.
  The server builds keys between neighbours itself
  (`docmost/positions.py`).
- `pages/duplicate` with `pageId` copies the page and its child pages next
  to the original and prefixes the copy's title with "Copy of "; with
  `spaceId` of another space it copies them to the end of that space's top
  level under the same title. Both answer with the new top page and
  `childPageIds`. Labels and attachments are copied, comments are not.
- `pages/move-to-space` with `pageId` and `spaceId` moves the page and the
  child pages the member can access to the top level of the other space; the
  same space answers `400 Page is already in this space`.

## Page history

- Docmost saves a version of a page in the background, about a minute after
  the last edit of a page younger than five minutes and about five minutes
  after it for older pages, and only when the body changed.
- `pages/history` with `pageId` lists versions, newest first, with
  `lastUpdatedBy` and `contributors`, without bodies.
- `pages/history/info` with `historyId` returns one version with its body as
  ProseMirror JSON only; there is no Markdown option. The server converts it
  (`doc_to_markdown`) and checks in the integration tests that the result
  matches Docmost's own Markdown for common content.
- `pages/info` with `format: "json"` returns the current body as
  ProseMirror JSON, which lets the server diff it against a version with
  the same conversion on both sides.

## Spaces

- `spaces/info` with `spaceId` returns the space with `memberCount` and the
  member's `membership.role`.

## Trash

- `pages/delete` with only `pageId` moves the page to Trash. The endpoint
  also has a permanent-delete option; this server never sends it.
- `pages/trash` lists trashed pages of a space; `pages/restore` restores one.
- A trashed page is still returned by `pages/info`, with `deletedAt` set,
  and drops out of `pages/sidebar-pages`.

## Comments

- `comments` lists the comments of a page (`pageId`), replies included, with
  `parentCommentId` on replies.
- `comments/create` takes `pageId`, optional `parentCommentId`, and
  `content` as a **JSON string** of a ProseMirror document; plain text is
  refused with `400`.
- `comments/info` with `commentId` returns one comment with its `pageId`,
  `spaceId` and `creatorId`.
- `comments/update` with `commentId` and `content` (a JSON string, as for
  create) changes a comment; Docmost answers `403 You can only edit your own
  comments` for comments of other people. `comments/delete` deletes
  permanently, so the server does not use it.
- `comments/resolve` answers `403 This feature requires a valid license.`
  on CE. Resolving comments is an Enterprise feature and is out of scope.

## Permissions

- A page or space the member cannot access answers `404` (`Space permissions
  not found`), not `403`. The server reports both as "not found" so it does
  not reveal whether something exists.
- `search` silently leaves out pages the member cannot see.
