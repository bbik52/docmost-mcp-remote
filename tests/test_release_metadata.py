"""The files the release workflow publishes agree with each other."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
SERVER_NAME = "io.github.bbik52/docmost-mcp-remote"
IMAGE = "ghcr.io/bbik52/docmost-mcp-remote"


def project_version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    version: str = data["project"]["version"]
    return version


@pytest.fixture
def server() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((ROOT / "server.json").read_text())
    return data


def test_server_json_matches_project(server: dict[str, Any]) -> None:
    version = project_version()
    assert server["name"] == SERVER_NAME
    assert server["version"] == version
    assert len(server["description"]) <= 100
    packages = {package["registryType"]: package for package in server["packages"]}
    assert packages["pypi"]["identifier"] == "docmost-mcp-remote"
    assert packages["pypi"]["version"] == version
    assert packages["oci"]["identifier"] == f"{IMAGE}:{version}"


def test_package_readme_names_the_server() -> None:
    # The registry checks that the PyPI description contains this line.
    readme = (ROOT / "README.md").read_text()
    assert re.search(rf"mcp-name: {re.escape(SERVER_NAME)}(\s|-->)", readme)


def test_image_names_the_server() -> None:
    # The registry checks this label on the image.
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert f'io.modelcontextprotocol.server.name="{SERVER_NAME}"' in dockerfile


def test_readme_shows_the_shipped_compose_file() -> None:
    readme = (ROOT / "README.md").read_text()
    blocks = re.findall(r"```yaml\n(.*?)```", readme, re.DOTALL)
    assert (ROOT / "compose.yaml").read_text() in blocks


def test_changelog_lists_the_version() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text()
    version = project_version()
    assert f"## [{version}]" in changelog or "## [Unreleased]" in changelog
