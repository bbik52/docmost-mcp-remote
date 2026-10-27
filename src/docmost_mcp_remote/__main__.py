"""Command line entry point: ``docmost-mcp-remote`` serves, ``... admin`` manages."""

from __future__ import annotations

import copy
import logging
import sys
from typing import Any

import uvicorn
from pydantic import ValidationError
from uvicorn.config import LOGGING_CONFIG

from docmost_mcp_remote import __version__
from docmost_mcp_remote.config import Settings
from docmost_mcp_remote.server import create_app

logger = logging.getLogger("docmost_mcp_remote")


def uvicorn_log_config() -> dict[str, Any]:
    """Uvicorn's logging, with download links redacted from the access log."""
    config = copy.deepcopy(LOGGING_CONFIG)
    config.setdefault("filters", {})["redact_downloads"] = {
        "()": "docmost_mcp_remote.web.downloads.RedactDownloadLinks"
    }
    config["handlers"]["access"]["filters"] = ["redact_downloads"]
    return config


def main() -> None:
    if sys.argv[1:2] == ["admin"]:
        from docmost_mcp_remote import admin

        raise SystemExit(admin.main(sys.argv[2:]))
    if sys.argv[1:2] == ["--version"]:
        print(__version__)
        return
    if sys.argv[1:2] == ["--tool-catalog"]:
        # Over stdio, for MCP directories: lists everything, runs nothing.
        from docmost_mcp_remote.server import create_catalog_server

        create_catalog_server().run(transport="stdio", show_banner=False)
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
    if settings.forwarded_allow_ips.strip() == "*":
        logger.warning(
            "FORWARDED_ALLOW_IPS=* lets clients choose the address used for rate limits; "
            "set it to the address of your reverse proxy"
        )
    if settings.docmost_url_is_insecure:
        logger.warning("DOCMOST_URL uses http: Docmost credentials and tokens travel unencrypted")

    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        log_config=uvicorn_log_config(),
        proxy_headers=True,
        forwarded_allow_ips=settings.forwarded_allow_ips,
        server_header=False,
    )


if __name__ == "__main__":
    main()
