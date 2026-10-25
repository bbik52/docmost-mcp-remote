"""``docmost-mcp-remote admin``: manage members, grants and keys from a shell.

Run it where the server runs, with the same environment, for example
``docker compose exec server docmost-mcp-remote admin members``.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from collections.abc import Sequence
from datetime import datetime

from pydantic import ValidationError

from docmost_mcp_remote.config import Settings
from docmost_mcp_remote.crypto import Cipher
from docmost_mcp_remote.db.admin_store import AdminStore, AuditStore
from docmost_mcp_remote.db.engine import create_engine, migrate


def _time(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if value else "-"


def _table(rows: list[list[str]], header: list[str]) -> str:
    widths = [max(len(row[i]) for row in [header, *rows]) for i in range(len(header))]
    lines = [
        "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True))
        for row in [header, *rows]
    ]
    return "\n".join(line.rstrip() for line in lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="docmost-mcp-remote admin")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("members", help="list members")
    grants = commands.add_parser("grants", help="list the active grants of a member")
    grants.add_argument("email")
    revoke = commands.add_parser("revoke-grant", help="revoke one grant and its tokens")
    revoke.add_argument("grant_id")
    revoke_member = commands.add_parser(
        "revoke-member", help="revoke every grant of a member and drop their Docmost session"
    )
    revoke_member.add_argument("email")
    disable = commands.add_parser("disable-member", help="block a member from this server")
    disable.add_argument("email")
    enable = commands.add_parser("enable-member", help="unblock a member")
    enable.add_argument("email")
    audit = commands.add_parser("audit", help="show recent tool calls")
    audit.add_argument("--email")
    audit.add_argument("--limit", type=int, default=50)
    commands.add_parser(
        "rotate-key",
        help="re-encrypt stored data with SECRET_KEY (set the old key as SECRET_KEY_PREVIOUS)",
    )
    return parser


async def _run(settings: Settings, args: argparse.Namespace) -> int:
    database_url = settings.database_url.get_secret_value()
    await migrate(database_url)
    engine = create_engine(database_url)
    store = AdminStore(engine)
    try:
        if args.command == "members":
            rows = [
                [
                    member.email,
                    member.name or "",
                    _time(member.last_login_at),
                    str(member.active_grants),
                    "disabled" if member.disabled else "active",
                ]
                for member in await store.members()
            ]
            print(_table(rows, ["EMAIL", "NAME", "LAST SIGN-IN", "GRANTS", "STATUS"]))
            return 0
        if args.command == "audit":
            entries = await AuditStore(engine).entries(email=args.email, limit=args.limit)
            rows = [
                [
                    _time(entry.created_at),
                    entry.email or "-",
                    entry.tool,
                    entry.page_id or entry.space_id or "",
                    entry.outcome,
                    f"{entry.duration_ms} ms",
                ]
                for entry in entries
            ]
            print(_table(rows, ["TIME", "MEMBER", "TOOL", "PAGE/SPACE", "OUTCOME", "TOOK"]))
            return 0
        if args.command == "revoke-grant":
            try:
                grant_id = uuid.UUID(args.grant_id)
            except ValueError:
                print("Not a grant id.", file=sys.stderr)
                return 1
            if not await store.revoke_grant(grant_id):
                print("No active grant with that id.", file=sys.stderr)
                return 1
            print(f"Revoked grant {grant_id}.")
            return 0
        if args.command == "rotate-key":
            if not settings.secret_key_previous:
                print("Set SECRET_KEY_PREVIOUS to the old key first.", file=sys.stderr)
                return 1
            cipher = Cipher(
                settings.secret_key.get_secret_value(),
                settings.secret_key_previous.get_secret_value(),
            )
            sessions, snapshots = await store.rotate_key(cipher)
            print(
                f"Re-encrypted {sessions} sessions and {snapshots} snapshots. "
                "SECRET_KEY_PREVIOUS can now be removed."
            )
            return 0

        member_id = await store.member_id(args.email)
        if member_id is None:
            print("No member with that email.", file=sys.stderr)
            return 1
        if args.command == "grants":
            rows = [
                [
                    str(grant.id),
                    grant.kind,
                    grant.name,
                    grant.scopes,
                    _time(grant.created_at),
                    _time(grant.last_used_at),
                ]
                for grant in await store.grants(member_id)
            ]
            print(_table(rows, ["ID", "KIND", "NAME", "SCOPES", "CREATED", "LAST USED"]))
        elif args.command == "revoke-member":
            count = await store.revoke_member(member_id)
            print(f"Revoked {count} grants and the Docmost session of {args.email}.")
        elif args.command == "disable-member":
            await store.set_disabled(member_id, True)
            print(f"Disabled {args.email}. Their tokens stop working at once.")
        elif args.command == "enable-member":
            await store.set_disabled(member_id, False)
            print(f"Enabled {args.email}.")
        return 0
    finally:
        await engine.dispose()


def main(argv: Sequence[str]) -> int:
    args = _parser().parse_args(argv)
    try:
        settings = Settings()
    except ValidationError as exc:
        print(f"Invalid configuration:\n{exc}", file=sys.stderr)
        return 2
    return asyncio.run(_run(settings, args))
