"""Streaming stdlib transport; never forwards provider API credentials."""
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


def validate_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None):
            raise ValueError
        parsed.port
    except (ValueError, TypeError):
        raise ValueError("A usable HTTP(S) media URL is required.") from None
    return value


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class StreamingTransport:
    def open(self, url: str, timeout: float):
        validate_url(url)
        request = Request(url, headers={"User-Agent": "BinFinder/0.1",
                                        "Accept-Encoding": "identity"})
        return build_opener(SafeRedirect()).open(request, timeout=timeout)
