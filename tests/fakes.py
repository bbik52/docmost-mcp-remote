"""Test doubles shared by unit tests."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx

from docmost_mcp_remote.docmost import CeDocmostClient

Handler = Callable[[httpx.Request], httpx.Response]


def ok(data: Any = None, **kwargs: Any) -> httpx.Response:
    return httpx.Response(200, json={"data": data, "success": True, "status": 200}, **kwargs)


def error(status: int, message: str | list[str]) -> httpx.Response:
    return httpx.Response(status, json={"message": message, "statusCode": status})


class Recorder:
    """A mock Docmost: routes by path and records every request."""

    def __init__(self, routes: dict[str, Handler | httpx.Response] | None = None) -> None:
        self.routes: dict[str, Handler | httpx.Response] = routes or {}
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        route = self.routes.get(request.url.path)
        if route is None:
            return error(404, f"no route for {request.url.path}")
        return route(request) if callable(route) else route

    def body(self, index: int = -1) -> Any:
        return json.loads(self.requests[index].content)

    def client(self, **kwargs: Any) -> CeDocmostClient:
        return CeDocmostClient(
            "https://docs.example.com", transport=httpx.MockTransport(self), **kwargs
        )


def docmost_routes(
    *,
    password: str = "pw",
    token: str = "docmost-token",
    version: str = "0.97.0",
    email: str = "anna@example.com",
) -> dict[str, Handler | httpx.Response]:
    """Routes of a Docmost with one user, for sign-in flows."""

    def login(request: httpx.Request) -> httpx.Response:
        if json.loads(request.content).get("password") != password:
            return error(401, "Email or password does not match")
        return ok(None, headers={"set-cookie": f"authToken={token}; Path=/; HttpOnly"})

    def authed(data: Any) -> Handler:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.headers.get("authorization") != f"Bearer {token}":
                return error(401, "Unauthorized")
            return ok(data)

        return handler

    return {
        "/api/health": httpx.Response(200, json={"status": "ok"}),
        "/api/auth/login": login,
        "/api/version": authed({"currentVersion": version}),
        "/api/users/me": authed(
            {
                "user": {
                    "id": "docmost-user-1",
                    "email": email,
                    "name": "Anna",
                    "role": "member",
                    "workspaceId": "w1",
                }
            }
        ),
    }
