from fastapi.responses import HTMLResponse
from starlette.responses import Response

from app.render import header_text

SAFE_HEADERS = {"x-toast-message", "x-sort"}


def _clean_headers(headers):
    if not headers:
        return headers
    cleaned = dict(headers)
    for key in list(cleaned):
        if key.lower() in SAFE_HEADERS:
            cleaned[key] = header_text(cleaned[key])
    return cleaned


class SafeResponse(Response):
    def init_headers(self, headers=None):
        super().init_headers(_clean_headers(headers))


class SafeHTMLResponse(HTMLResponse):
    def init_headers(self, headers=None):
        super().init_headers(_clean_headers(headers))
