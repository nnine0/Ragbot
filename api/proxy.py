import os
import sys
import json
import urllib.request
import urllib.parse

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8080")


def log(msg):
    print(str(msg), file=sys.stderr)


def app(environ, start_response):
    path = environ.get("PATH_INFO", "").lstrip("/")
    if path == "api/proxy.py" or not path:
        path = ""

    qs = environ.get("QUERY_STRING", "")
    params = urllib.parse.parse_qs(qs)

    if "path" in params and params["path"]:
        routed_path = params["path"][0]
    else:
        routed_path = path

    target = f"{BACKEND_URL}/{routed_path}"
    qs_params = {k: v for k, v in params.items() if k != "path"}
    if qs_params:
        target += "?" + urllib.parse.urlencode(qs_params, doseq=True)

    method = environ.get("REQUEST_METHOD", "GET")
    content_length = int(environ.get("CONTENT_LENGTH", "0"))
    body = environ["wsgi.input"].read(content_length) if content_length > 0 else b""

    headers = {}
    for k, v in environ.items():
        if k.startswith("HTTP_"):
            h = k[5:].replace("_", "-").title()
            if h.lower() not in ("host", "x-forwarded-for", "x-forwarded-proto"):
                headers[h] = v
        elif k == "CONTENT_TYPE":
            headers["Content-Type"] = v

    try:
        req = urllib.request.Request(target, data=body or None, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=25) as resp:
            resp_headers = [(k, v) for k, v in resp.getheaders()
                           if k.lower() not in ("transfer-encoding", "content-encoding", "connection")]
            resp_body = resp.read()
            start_response(f"{resp.status} OK", resp_headers)
            return [resp_body]

    except urllib.error.HTTPError as e:
        start_response(f"{e.code} ERROR", [("Content-Type", "application/json")])
        return [e.read()]
    except Exception as e:
        log(f"Proxy error: {e}")
        err = json.dumps({"error": str(e), "detail": "Backend unreachable"})
        start_response("502 Bad Gateway", [("Content-Type", "application/json")])
        return [err.encode()]
