import os
import sys
import json
import urllib.request
import urllib.parse
import io
import cgi

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8080")


def log(msg):
    print(msg, file=sys.stderr)


class ProxyResponse:
    def __init__(self):
        self.status = 200
        self.headers = {}
        self.body = b""


def application(environ, start_response):
    path = environ.get("PATH_INFO", "").lstrip("/")
    qs = environ.get("QUERY_STRING", "")
    method = environ.get("REQUEST_METHOD", "GET")

    target = f"{BACKEND_URL}/{path}"
    if qs:
        target += f"?{qs}"

    content_length = int(environ.get("CONTENT_LENGTH", "0"))
    body = environ["wsgi.input"].read(content_length) if content_length > 0 else b""

    headers = {}
    for key, val in environ.items():
        if key.startswith("HTTP_"):
            header_name = key[5:].replace("_", "-").title()
            if header_name.lower() not in ("host", "x-forwarded-for", "x-forwarded-proto", "x-vercel-*"):
                headers[header_name] = val
        elif key == "CONTENT_TYPE":
            headers["Content-Type"] = val

    try:
        req = urllib.request.Request(target, data=body or None, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=25) as resp:
            status = resp.status
            resp_headers = {}
            for k, v in resp.getheaders():
                if k.lower() not in ("transfer-encoding", "content-encoding", "connection", "x-vercel-id", "x-vercel-proxy-signature"):
                    resp_headers[k] = v
            resp_body = resp.read()

            if path.startswith("ask"):
                start_response(f"{status} OK", list(resp_headers.items()))
                return [resp_body]
            else:
                start_response(f"{status} OK", [("Content-Type", resp_headers.get("Content-Type", "application/json"))])
                return [resp_body]

    except urllib.error.HTTPError as e:
        body = e.read()
        start_response(f"{e.code} ERROR", [("Content-Type", "application/json")])
        return [body]
    except Exception as e:
        log(f"Proxy error: {e}")
        err = json.dumps({"error": str(e), "detail": "Backend unreachable. Is the Docker stack running?"})
        start_response("502 Bad Gateway", [("Content-Type", "application/json")])
        return [err.encode()]
