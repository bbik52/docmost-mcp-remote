from __future__ import annotations

import base64
import hashlib
import re
import secrets
from collections.abc import Iterator
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import anyio
import httpx
import pytest
from fastmcp import Client
from fastmcp.client.auth import OAuth
from mcp.shared.auth import AuthorizationCodeResult
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncEngine

from docmost_mcp_remote.db.oauth_store import OAuthStore
from docmost_mcp_remote.db.schema import oauth_clients
from docmost_mcp_remote.db.store import Store, now
from docmost_mcp_remote.oauth import DocmostOAuthProvider, redirect_uri_allowed
from tests.conftest import make_settings
from tests.fakes import Recorder, docmost_routes
from tests.harness import RunningServer

CSRF = re.compile(r'name="csrf" value="([^"]+)"')
REDIRECT = "http://127.0.0.1:9999/callback"
MCP_HEADERS = {"accept": "application/json, text/event-stream"}


def pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge.decode().rstrip("=")


def query(url: str) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}


class Flow:
    """Drives the browser side and the client side of the OAuth flow."""

    def __init__(self, server: RunningServer) -> None:
        self.server = server
        self.public = server.public_url
        self.resource = f"{self.public}/mcp"
        self.http = httpx.Client(base_url=server.url, follow_redirects=False)
        self.browser = httpx.Client(base_url=server.url, follow_redirects=False)

    def close(self) -> None:
        self.http.close()
        self.browser.close()

    def register(self, **metadata: Any) -> httpx.Response:
        body = {
            "client_name": "Test Client",
            "redirect_uris": [REDIRECT],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            **metadata,
        }
        return self.http.post("/register", json=body)

    def client_id(self) -> str:
        response = self.register()
        assert response.status_code == 201, response.text
        return str(response.json()["client_id"])

    def authorize(self, client_id: str, challenge: str, **params: str) -> httpx.Response:
        values = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "xyz",
            "scope": "read write",
            "resource": self.resource,
            **params,
        }
        return self.http.get("/authorize", params={k: v for k, v in values.items() if v})

    def sign_in(self, email: str = "anna@example.com", password: str = "pw") -> None:
        page = self.browser.get("/login")
        csrf = CSRF.search(page.text)
        assert csrf
        signed_in = self.browser.post(
            "/login", data={"csrf": csrf.group(1), "email": email, "password": password}
        )
        assert signed_in.status_code == 303

    def consent_path(self, client_id: str, challenge: str, **params: str) -> str:
        response = self.authorize(client_id, challenge, **params)
        assert response.status_code == 302, response.text
        location = response.headers["location"]
        assert location.startswith(f"{self.public}/oauth/consent?request=")
        return location.removeprefix(self.public)

    def answer(self, path: str, action: str = "approve", scopes: tuple[str, ...] = ()) -> str:
        page = self.browser.get(path)
        assert page.status_code == 200, page.text
        csrf = CSRF.search(page.text)
        assert csrf
        response = self.browser.post(
            "/oauth/consent",
            data={
                "csrf": csrf.group(1),
                "request": query(path)["request"],
                "action": action,
                "scope": list(scopes),
            },
        )
        assert response.status_code == 303, response.text
        return response.headers["location"]

    def code(self, client_id: str, scopes: tuple[str, ...] = ()) -> tuple[str, str]:
        verifier, challenge = pkce()
        location = self.answer(self.consent_path(client_id, challenge), scopes=scopes)
        assert location.startswith(REDIRECT)
        values = query(location)
        assert values["state"] == "xyz"
        return values["code"], verifier

    def exchange(self, client_id: str, code: str, verifier: str, **extra: str) -> httpx.Response:
        return self.http.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT,
                "client_id": client_id,
                "code_verifier": verifier,
                "resource": self.resource,
                **extra,
            },
        )

    def tokens(self, client_id: str, scopes: tuple[str, ...] = ()) -> dict[str, Any]:
        code, verifier = self.code(client_id, scopes)
        response = self.exchange(client_id, code, verifier)
        assert response.status_code == 200, response.text
        return dict(response.json())

    def refresh(self, client_id: str, refresh_token: str, **extra: str) -> httpx.Response:
        return self.http.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
                **extra,
            },
        )

    def authorized(self, token: str) -> bool:
        """Whether /mcp accepts the token (the request itself may still be refused)."""
        response = self.http.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={**MCP_HEADERS, "authorization": f"Bearer {token}"},
        )
        return response.status_code != 401


def refused(response: httpx.Response) -> bool:
    """A refused grant: invalid_grant, sent with 401 as the MCP spec asks."""
    return response.status_code == 401 and response.json()["error"] == "invalid_grant"


@pytest.fixture
def server(engine: AsyncEngine) -> Iterator[RunningServer]:
    with RunningServer(Recorder(docmost_routes()).client()) as running:
        yield running


@pytest.fixture
def flow(server: RunningServer) -> Iterator[Flow]:
    flow = Flow(server)
    flow.sign_in()
    try:
        yield flow
    finally:
        flow.close()


# Discovery and registration


def test_metadata(flow: Flow) -> None:
    resource = flow.http.get("/.well-known/oauth-protected-resource/mcp").json()
    assert resource["resource"] == flow.resource
    assert resource["authorization_servers"] == [f"{flow.public}/"]
    server = flow.http.get("/.well-known/oauth-authorization-server").json()
    assert server["code_challenge_methods_supported"] == ["S256"]
    assert server["registration_endpoint"] == f"{flow.public}/register"
    assert set(server["scopes_supported"]) == {"read", "write", "delete"}


def test_unauthorized_mcp_points_to_metadata(flow: Flow) -> None:
    response = flow.http.post("/mcp", json={}, headers=MCP_HEADERS)
    assert response.status_code == 401
    assert "oauth-protected-resource" in response.headers["www-authenticate"]


@pytest.mark.parametrize(
    ("uri", "allowed"),
    [
        ("https://claude.ai/api/mcp/auth_callback", True),
        ("http://127.0.0.1:33418/callback", True),
        ("http://localhost:8080/cb", True),
        ("http://[::1]:8080/cb", True),
        ("cursor://anysphere.cursor-mcp/oauth/callback", True),
        ("http://evil.example.com/cb", False),
        ("https://claude.ai/cb#fragment", False),
        ("javascript:alert(1)", False),
        ("data:text/html,hi", False),
    ],
)
def test_redirect_uri_rules(uri: str, allowed: bool) -> None:
    assert redirect_uri_allowed(uri) is allowed


def test_registration_refuses_bad_redirects(flow: Flow) -> None:
    for uris in (
        ["http://evil.example.com/cb"],
        ["javascript:alert(1)"],
        [f"http://127.0.0.1:{port}/cb" for port in range(9000, 9011)],
    ):
        response = flow.register(redirect_uris=uris)
        assert response.status_code == 400, uris
        assert response.json()["error"] == "invalid_redirect_uri"


def test_registration_refuses_unknown_scopes(flow: Flow) -> None:
    response = flow.register(scope="read admin")
    assert response.status_code == 400


def test_registration_rate_limit(flow: Flow) -> None:
    statuses = [flow.register().status_code for _ in range(11)]
    assert statuses[:10] == [201] * 10
    assert statuses[10] == 429


# Authorization and consent


class BrowserlessOAuth(OAuth):
    """The MCP SDK's OAuth client, with the browser step done by ``Flow``."""

    def __init__(self, flow: Flow) -> None:
        super().__init__(mcp_url=flow.resource, scopes=["read", "write"], client_name="SDK")
        self._flow = flow
        self._authorization_url = ""

    async def redirect_handler(self, authorization_url: str) -> None:
        self._authorization_url = authorization_url

    async def callback_handler(self) -> AuthorizationCodeResult:
        def browse() -> dict[str, str]:
            path = self._authorization_url.removeprefix(self._flow.public)
            consent = self._flow.browser.get(path).headers["location"]
            location = self._flow.answer(consent.removeprefix(self._flow.public), scopes=("write",))
            return query(location)

        values = await anyio.to_thread.run_sync(browse)
        return AuthorizationCodeResult(code=values["code"], state=values.get("state"))


@pytest.mark.filterwarnings("ignore:Using in-memory token storage")
async def test_sdk_client_flow(flow: Flow) -> None:
    async with Client(flow.resource, auth=BrowserlessOAuth(flow)) as client:
        result = await client.call_tool("whoami", {})
    assert result.structured_content is not None
    assert result.structured_content["scopes"] == ["read", "write"]


def test_full_flow(flow: Flow, server: RunningServer) -> None:
    client_id = flow.client_id()
    tokens = flow.tokens(client_id, scopes=("write",))
    assert tokens["token_type"] == "Bearer"
    assert tokens["expires_in"] == 3600
    assert tokens["scope"] == "read write"

    whoami = server.call(tokens["access_token"], "whoami")
    assert whoami["email"] == "anna@example.com"
    assert whoami["scopes"] == ["read", "write"]

    account = flow.browser.get("/account").text
    assert "Test Client" in account
    assert "OAuth app" in account


def test_consent_requires_sign_in(server: RunningServer) -> None:
    flow = Flow(server)
    try:
        _, challenge = pkce()
        path = flow.consent_path(flow.client_id(), challenge)
        response = flow.browser.get(path)
        assert response.status_code == 303
        assert response.headers["location"].startswith("/login?next=%2Foauth%2Fconsent")
    finally:
        flow.close()


def test_consent_page(flow: Flow) -> None:
    _, challenge = pkce()
    path = flow.consent_path(flow.client_id(), challenge, scope="read write delete")
    page = flow.browser.get(path)
    assert "Allow Test Client" in page.text
    assert "127.0.0.1:9999" in page.text
    assert 'value="write"' in page.text
    assert 'value="delete"' in page.text
    assert "checked disabled" in page.text
    # write and delete are never preselected
    assert 'value="write" checked' not in page.text
    csp = page.headers["content-security-policy"]
    assert "form-action 'self' http://127.0.0.1:9999;" in csp
    assert "frame-ancestors 'none'" in csp


def test_unticked_scopes_are_not_granted(flow: Flow) -> None:
    client_id = flow.client_id()
    tokens = flow.tokens(client_id)
    assert tokens["scope"] == "read"


def test_scopes_not_requested_cannot_be_ticked(flow: Flow) -> None:
    client_id = flow.client_id()
    verifier, challenge = pkce()
    path = flow.consent_path(client_id, challenge, scope="read")
    code = query(flow.answer(path, scopes=("write", "delete")))["code"]
    assert flow.exchange(client_id, code, verifier).json()["scope"] == "read"


def test_deny(flow: Flow) -> None:
    _, challenge = pkce()
    location = flow.answer(flow.consent_path(flow.client_id(), challenge), action="deny")
    assert query(location) == {"error": "access_denied", "state": "xyz"}


def test_consent_is_single_use(flow: Flow) -> None:
    _, challenge = pkce()
    path = flow.consent_path(flow.client_id(), challenge)
    csrf = CSRF.search(flow.browser.get(path).text)
    assert csrf
    data = {"csrf": csrf.group(1), "request": query(path)["request"], "action": "approve"}
    assert flow.browser.post("/oauth/consent", data=data).status_code == 303
    again = flow.browser.post("/oauth/consent", data=data)
    assert again.status_code == 400
    assert "expired" in again.text


def test_consent_csrf(flow: Flow) -> None:
    _, challenge = pkce()
    path = flow.consent_path(flow.client_id(), challenge)
    response = flow.browser.post(
        "/oauth/consent",
        data={"csrf": "forged", "request": query(path)["request"], "action": "approve"},
    )
    assert response.status_code == 400


def test_unknown_request(flow: Flow) -> None:
    response = flow.browser.get("/oauth/consent?request=dmr_nothing")
    assert response.status_code == 400
    assert "expired" in response.text


def test_pkce_required(flow: Flow) -> None:
    client_id = flow.client_id()
    for params in ({"code_challenge": ""}, {"code_challenge_method": "plain"}):
        response = flow.authorize(client_id, "c" * 43, **params)
        assert response.status_code == 302
        assert query(response.headers["location"])["error"] == "invalid_request"


def test_wrong_code_verifier(flow: Flow) -> None:
    client_id = flow.client_id()
    code, verifier = flow.code(client_id)
    assert refused(flow.exchange(client_id, code, "x" * 50))
    assert flow.exchange(client_id, code, verifier).status_code == 200


def test_unregistered_redirect_uri(flow: Flow) -> None:
    client_id = flow.client_id()
    _, challenge = pkce()
    response = flow.authorize(client_id, challenge, redirect_uri="http://127.0.0.1:9999/other")
    # Never redirect to an unregistered URI.
    assert response.status_code == 400


def test_redirect_uri_mismatch_at_token(flow: Flow) -> None:
    client_id = flow.client_id()
    code, verifier = flow.code(client_id)
    response = flow.exchange(client_id, code, verifier, redirect_uri="http://127.0.0.1:9999/x")
    assert response.status_code == 400


def test_code_of_another_client(flow: Flow) -> None:
    owner, other = flow.client_id(), flow.client_id()
    code, verifier = flow.code(owner)
    assert refused(flow.exchange(other, code, verifier))


def test_wrong_resource_is_refused(flow: Flow) -> None:
    _, challenge = pkce()
    response = flow.authorize(flow.client_id(), challenge, resource="https://other.example/mcp")
    assert response.status_code == 302
    assert query(response.headers["location"])["error"] == "invalid_target"


def test_code_replay_revokes_grant(flow: Flow) -> None:
    client_id = flow.client_id()
    code, verifier = flow.code(client_id)
    first = flow.exchange(client_id, code, verifier)
    assert first.status_code == 200
    access = first.json()["access_token"]
    assert flow.authorized(access)

    assert refused(flow.exchange(client_id, code, verifier))
    assert not flow.authorized(access)


# Refresh, revocation, verification


def test_refresh_rotates(flow: Flow) -> None:
    client_id = flow.client_id()
    tokens = flow.tokens(client_id, scopes=("write",))
    refreshed = flow.refresh(client_id, tokens["refresh_token"])
    assert refreshed.status_code == 200, refreshed.text
    new = refreshed.json()
    assert new["refresh_token"] != tokens["refresh_token"]
    assert new["scope"] == "read write"
    assert flow.authorized(new["access_token"])


def test_refresh_can_narrow_scopes(flow: Flow, server: RunningServer) -> None:
    client_id = flow.client_id()
    tokens = flow.tokens(client_id, scopes=("write",))
    narrowed = flow.refresh(client_id, tokens["refresh_token"], scope="read")
    assert narrowed.json()["scope"] == "read"
    assert server.call(narrowed.json()["access_token"], "whoami")["scopes"] == ["read"]
    wider = flow.refresh(client_id, narrowed.json()["refresh_token"], scope="read write")
    assert wider.status_code == 400


def test_refresh_reuse_revokes_grant(flow: Flow) -> None:
    client_id = flow.client_id()
    tokens = flow.tokens(client_id)
    new = flow.refresh(client_id, tokens["refresh_token"]).json()

    assert refused(flow.refresh(client_id, tokens["refresh_token"]))
    assert not flow.authorized(new["access_token"])
    assert refused(flow.refresh(client_id, new["refresh_token"]))


def test_refresh_token_is_not_an_access_token(flow: Flow) -> None:
    tokens = flow.tokens(flow.client_id())
    assert not flow.authorized(tokens["refresh_token"])


def test_refresh_by_another_client(flow: Flow) -> None:
    owner, other = flow.client_id(), flow.client_id()
    tokens = flow.tokens(owner)
    assert refused(flow.refresh(other, tokens["refresh_token"]))


def test_revoke_endpoint(flow: Flow) -> None:
    client_id = flow.client_id()
    tokens = flow.tokens(client_id)
    # The MCP SDK's revocation form needs client_secret, even empty for public clients.
    response = flow.http.post(
        "/revoke",
        data={"token": tokens["access_token"], "client_id": client_id, "client_secret": ""},
    )
    assert response.status_code == 200, response.text
    assert not flow.authorized(tokens["access_token"])
    assert refused(flow.refresh(client_id, tokens["refresh_token"]))


def test_revoke_from_account_page(flow: Flow) -> None:
    tokens = flow.tokens(flow.client_id())
    page = flow.browser.get("/account").text
    grant = re.search(r"/account/grants/([0-9a-f-]+)/revoke", page)
    csrf = CSRF.search(page)
    assert grant
    assert csrf
    flow.browser.post(f"/account/grants/{grant.group(1)}/revoke", data={"csrf": csrf.group(1)})
    assert not flow.authorized(tokens["access_token"])


async def _member_grant(engine: AsyncEngine) -> Any:
    store = Store(engine)
    member = await store.upsert_member("user-1", "anna@example.com", "Anna")
    grant_id, _ = await store.create_personal_token(member.id, "x", frozenset({"read"}))
    return grant_id


async def test_token_for_another_resource_is_refused(engine: AsyncEngine) -> None:
    settings = make_settings()
    oauth = OAuthStore(engine)
    provider = DocmostOAuthProvider(settings, Store(engine), oauth)
    grant_id = await _member_grant(engine)
    hour = timedelta(hours=1)
    for resource, accepted in (
        ("https://mcp.example.com/mcp", True),
        ("https://mcp.example.com/mcp/", True),
        ("https://other.example.com/mcp", False),
        (None, False),
    ):
        issued = await oauth.issue_tokens(
            grant_id, scopes=None, resource=resource, access_ttl=hour, refresh_ttl=hour
        )
        verified = await provider.load_access_token(issued.access_token)
        assert (verified is not None) is accepted, resource


async def test_expired_access_token(engine: AsyncEngine) -> None:
    oauth = OAuthStore(engine)
    provider = DocmostOAuthProvider(make_settings(), Store(engine), oauth)
    grant_id = await _member_grant(engine)
    issued = await oauth.issue_tokens(
        grant_id,
        scopes=None,
        resource="https://mcp.example.com/mcp",
        access_ttl=timedelta(seconds=-1),
        refresh_ttl=timedelta(days=1),
    )
    assert await provider.load_access_token(issued.access_token) is None


async def test_cleanup_removes_unused_clients(engine: AsyncEngine) -> None:
    oauth = OAuthStore(engine)
    await oauth.save_client("old", "{}")
    await oauth.save_client("new", "{}")
    async with engine.begin() as connection:
        await connection.execute(
            update(oauth_clients)
            .where(oauth_clients.c.client_id == "old")
            .values(created_at=now() - timedelta(days=2))
        )
    await oauth.cleanup()
    async with engine.connect() as connection:
        left = (await connection.execute(text("SELECT client_id FROM oauth_clients"))).scalars()
        assert list(left) == ["new"]
