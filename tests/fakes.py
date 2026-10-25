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
