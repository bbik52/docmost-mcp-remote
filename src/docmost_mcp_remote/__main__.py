"""Command line entry point: ``docmost-mcp-remote`` serves, ``... admin`` manages."""

from __future__ import annotations

import logging
import sys

import uvicorn
from pydantic import ValidationError

from docmost_mcp_remote import __version__
from docmost_mcp_remote.config import Settings
from docmost_mcp_remote.server import create_app

logger = logging.getLogger("docmost_mcp_remote")


def main() -> None:
    if sys.argv[1:2] == ["admin"]:
        from docmost_mcp_remote import admin

        raise SystemExit(admin.main(sys.argv[2:]))
    if sys.argv[1:2] == ["--version"]:
        print(__version__)
        return
    try:
        settings = Settings()
    except ValidationError as exc:
        print(f"Invalid configuration:\n{exc}", file=sys.stderr)
        raise SystemExit(2) from None

    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Request lines of the HTTP client add noise and are not needed to operate the server.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logger.info("Starting docmost-mcp-remote %s", __version__)
    if settings.docmost_url_is_insecure:
        logger.warning("DOCMOST_URL uses http: Docmost credentials and tokens travel unencrypted")

    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        proxy_headers=True,
        forwarded_allow_ips=settings.forwarded_allow_ips,
        server_header=False,
    )


if __name__ == "__main__":
    main()
