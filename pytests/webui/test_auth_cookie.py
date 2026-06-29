from fastapi import Response
from starlette.requests import Request

from src.webui.app import create_app
from src.webui.core import auth


class _FakeTokenManager:
    def __init__(self, token: str) -> None:
        self.token = token

    def get_token(self) -> str:
        return self.token

    def verify_token(self, token: str) -> bool:
        return token == self.token


def _build_request_with_cookies(cookies: dict[str, str]) -> Request:
    cookie_header = "; ".join(f"{key}={value}" for key, value in cookies.items()).encode("latin-1")
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"cookie", cookie_header)],
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
        }
    )


def test_auth_cookie_name_is_derived_from_access_token_hash() -> None:
    first_name = auth.build_auth_cookie_name("first-token")
    second_name = auth.build_auth_cookie_name("second-token")

    assert first_name.startswith(f"{auth.COOKIE_NAME_PREFIX}_")
    assert second_name.startswith(f"{auth.COOKIE_NAME_PREFIX}_")
    assert first_name != second_name
    assert "first-token" not in first_name
    assert "second-token" not in second_name


def test_auth_cookie_value_reads_only_current_token_cookie(monkeypatch) -> None:
    current_token = "current-token"
    other_token = "other-token"
    monkeypatch.setattr(auth, "get_token_manager", lambda: _FakeTokenManager(current_token))

    request = _build_request_with_cookies(
        {
            auth.LEGACY_COOKIE_NAME: other_token,
            auth.build_auth_cookie_name(other_token): other_token,
        }
    )

    assert auth.get_auth_cookie_value(request) is None
    assert not auth.is_token_valid(request)

    current_cookie_name = auth.build_auth_cookie_name(current_token)
    request = _build_request_with_cookies(
        {
            auth.LEGACY_COOKIE_NAME: other_token,
            auth.build_auth_cookie_name(other_token): other_token,
            current_cookie_name: current_token,
        }
    )

    assert auth.get_auth_cookie_value(request) == current_token
    assert auth.is_token_valid(request)


def test_set_auth_cookie_uses_token_scoped_name_and_clears_legacy_cookie(monkeypatch) -> None:
    token = "current-token"
    monkeypatch.setattr(auth, "_is_secure_environment", lambda: False)

    response = Response()
    auth.set_auth_cookie(response, token)

    set_cookie_headers = [
        value.decode("latin-1")
        for key, value in response.raw_headers
        if key.lower() == b"set-cookie"
    ]

    assert any(header.startswith(f"{auth.build_auth_cookie_name(token)}={token};") for header in set_cookie_headers)
    assert any(header.startswith(f"{auth.LEGACY_COOKIE_NAME}=") and "Max-Age=0" in header for header in set_cookie_headers)


def test_create_app_registers_dashboard_api_routes() -> None:
    app = create_app(enable_static=False)
    routes = {
        (method, route.path)
        for route in app.routes
        for method in getattr(route, "methods", set())
    }

    assert ("GET", "/api/webui/auth/check") in routes
    assert ("POST", "/api/webui/auth/verify") in routes
    assert ("GET", "/api/webui/config/bot") in routes
    assert ("GET", "/api/webui/config/schema/bot") in routes
    assert ("GET", "/api/webui/plugins/config/{plugin_id}/bundle") in routes
    assert ("GET", "/api/webui/plugins/local-changelog/{plugin_id}") in routes
