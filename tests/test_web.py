from __future__ import annotations

import re
from collections.abc import Iterator

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.testclient import TestClient

from docmost_mcp_remote.server import create_app
from docmost_mcp_remote.web.routes import safe_next
from tests.conftest import make_settings
from tests.fakes import Recorder, docmost_routes

CSRF = re.compile(r'name="csrf" value="([^"]+)"')


@pytest.fixture
def web(engine: AsyncEngine) -> Iterator[TestClient]:
    settings = make_settings(public_url="http://localhost:8000")
    app = create_app(settings, Recorder(docmost_routes()).client())
    with TestClient(app, base_url="http://localhost:8000") as client:
        yield client


def csrf_of(html: str) -> str:
    match = CSRF.search(html)
    assert match, "no CSRF field in page"
    return match.group(1)


def sign_in(client: TestClient, password: str = "pw", email: str = "anna@example.com") -> str:
    page = client.get("/login")
    response = client.post(
        "/login",
        data={"csrf": csrf_of(page.text), "email": email, "password": password, "next": "/account"},
        follow_redirects=False,
    )
    return str(response.status_code)


def test_login_page_headers(web: TestClient) -> None:
    response = web.get("/login")
    assert response.status_code == 200
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "no-store"
    assert "dmr_login" in response.cookies


def test_csrf_is_required(web: TestClient) -> None:
    web.get("/login")
    response = web.post(
        "/login", data={"csrf": "forged", "email": "anna@example.com", "password": "pw"}
    )
    assert response.status_code == 400
    assert "expired" in response.text


def test_wrong_password(web: TestClient) -> None:
    assert sign_in(web, password="wrong") == "401"


def test_sign_in_and_tokens(web: TestClient) -> None:
    assert sign_in(web) == "303"

    account = web.get("/account")
    assert account.status_code == 200
    assert "anna@example.com" in account.text
    csrf = csrf_of(account.text)

    created = web.post(
        "/account/tokens",
        data={"csrf": csrf, "name": "laptop", "scope": ["write", "superuser"]},
    )
    assert created.status_code == 200
    token = re.search(r"dmr_[A-Za-z0-9_-]+", created.text)
    assert token
    assert "read, write" in created.text
    assert "superuser" not in created.text

    # Shown once: a reload shows only the hint.
    again = web.get("/account")
    assert token.group(0) not in again.text
    assert token.group(0)[:10] in again.text

    grant_id = re.search(r"/account/grants/([0-9a-f-]+)/revoke", again.text)
    assert grant_id
    revoked = web.post(
        f"/account/grants/{grant_id.group(1)}/revoke", data={"csrf": csrf}, follow_redirects=False
    )
    assert revoked.status_code == 303
    assert "No tokens or connected apps yet" in web.get("/account").text


def test_account_forms_need_csrf(web: TestClient) -> None:
    sign_in(web)
    response = web.post("/account/tokens", data={"csrf": "forged", "name": "x"})
    assert response.status_code == 400
    assert "dmr_" not in response.text.replace("dmr_session", "")


def test_account_requires_sign_in(web: TestClient) -> None:
    response = web.get("/account", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")


def test_logout(web: TestClient) -> None:
    sign_in(web)
    csrf = csrf_of(web.get("/account").text)
    web.post("/logout", data={"csrf": csrf})
    assert web.get("/account", follow_redirects=False).status_code == 303


def test_sign_in_rate_limit(web: TestClient) -> None:
    statuses = [sign_in(web, password="wrong") for _ in range(6)]
    assert statuses[:5] == ["401"] * 5
    assert statuses[5] == "429"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("/account", "/account"),
        ("/oauth/authorize?x=1", "/oauth/authorize?x=1"),
        ("https://evil.example.com", "/account"),
        ("//evil.example.com", "/account"),
        ("/\\evil.example.com", "/account"),
        ("", "/account"),
        (None, "/account"),
    ],
)
def test_safe_next(value: str | None, expected: str) -> None:
    assert safe_next(value) == expected
