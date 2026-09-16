"""Eine ``Request``-Attrappe für die Unit-Tests der Dependencies.

Seit die Anmeldung auch aus einem HttpOnly-Cookie kommen kann, brauchen
``get_token_data`` und ``get_org_context`` die Anfrage selbst — für das
Cookie, für die Methode und für den CSRF-Kopf. In einem Unit-Test gibt es
keine echte; ein Starlette-``Request`` lässt sich aber aus einem nackten
ASGI-Scope bauen, und mehr als Header, Cookies und Methode liest der
Code nicht."""
from starlette.requests import Request


def fake_request(
    method: str = "GET",
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
) -> Request:
    roh: list[tuple[bytes, bytes]] = [
        (k.lower().encode(), v.encode()) for k, v in (headers or {}).items()
    ]
    if cookies:
        keks = "; ".join(f"{k}={v}" for k, v in cookies.items())
        roh.append((b"cookie", keks.encode()))
    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": roh,
        }
    )
