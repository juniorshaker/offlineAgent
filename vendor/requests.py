"""
vendor/requests.py — A urllib-based drop-in compatibility layer for `requests.post`.

Provides a minimal subset of the `requests` API using only Python stdlib.
The user's example code: `requests.post(url, headers=headers, json=data)`
works exactly as written, with `.json()` and `.status_code` available.
"""

import json as _json
import urllib.request as _urllib_request
import urllib.error as _urllib_error


class Response:
    """Minimal response object compatible with requests.Response."""

    def __init__(self, raw_response, data: bytes):
        self.status_code = raw_response.status
        self._data = data
        self.headers = dict(raw_response.headers)
        self.reason = raw_response.reason

    def json(self):
        """Parse response body as JSON."""
        return _json.loads(self._data.decode("utf-8"))

    def text(self):
        """Return response body as text."""
        return self._data.decode("utf-8")


class ConnectionError(Exception):
    """Raised on network-level failures (DNS, refused, timeout)."""
    pass


def post(url, headers=None, json=None, timeout=60):
    """Send a POST request with JSON body.

    Args:
        url: Target URL.
        headers: Dict of HTTP headers.
        json: Python object to serialize as JSON body.
        timeout: Seconds before giving up.

    Returns:
        Response object with .json() and .status_code.

    Raises:
        ConnectionError: on network failure.
    """
    if headers is None:
        headers = {}
    # Build a mutable headers dict for the stdlib API
    req_headers = dict(headers)
    req_headers.setdefault("Content-Type", "application/json")

    if json is not None:
        body = _json.dumps(json).encode("utf-8")
    else:
        body = b""

    req = _urllib_request.Request(url, data=body, headers=req_headers, method="POST")

    try:
        with _urllib_request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            return Response(resp, data)
    except _urllib_error.HTTPError as e:
        # HTTP errors still return a response body from the server
        data = e.read()
        resp = Response(e, data)
        return resp
    except _urllib_error.URLError as e:
        raise ConnectionError(str(e.reason))
    except OSError as e:
        raise ConnectionError(str(e))


def get(url, headers=None, timeout=60):
    """Send a GET request."""
    if headers is None:
        headers = {}
    req = _urllib_request.Request(url, headers=headers, method="GET")

    try:
        with _urllib_request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            return Response(resp, data)
    except _urllib_error.HTTPError as e:
        data = e.read()
        return Response(e, data)
    except _urllib_error.URLError as e:
        raise ConnectionError(str(e.reason))
    except OSError as e:
        raise ConnectionError(str(e))
