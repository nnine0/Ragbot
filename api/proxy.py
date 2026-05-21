import os, sys, json, uuid, io, re, textwrap, mimetypes
from datetime import datetime
from urllib.parse import parse_qs, urlparse

DOCS_DIR = '/tmp/ragbot_docs'
AUTH_DIR = '/tmp/ragbot_auth'
os.makedirs(DOCS_DIR, exist_ok=True)
os.makedirs(AUTH_DIR, exist_ok=True)

def log(msg):
    print(str(msg), file=sys.stderr)

CORS_HEADERS = [
    ('Access-Control-Allow-Origin', '*'),
    ('Access-Control-Allow-Methods', 'GET, POST, OPTIONS, DELETE'),
    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
]

def json_response(start_response, data, status='200 OK'):
    h = [('Content-Type', 'application/json; charset=utf-8')] + CORS_HEADERS
    start_response(status, h)
    return [json.dumps(data).encode()]

def parse_multipart(body, content_type):
    boundary = content_type.split('boundary=')[-1].strip()
    if not boundary:
        return {}
    parts = {}
    for section in body.split(b'--' + boundary.encode()):
        if section.strip(b'\r\n') in (b'', b'--'):
            continue
        header_end = section.find(b'\r\n\r\n')
        if header_end == -1:
            continue
        raw_headers = section[:header_end].decode('utf-8', errors='replace')
        file_data = section[header_end + 4:]
        if file_data.endswith(b'\r\n'):
            file_data = file_data[:-2]
        filename = None
        name = None
        for line in raw_headers.split('\r\n'):
            if line.lower().startswith('content-disposition:'):
                for seg in line.split(';'):
                    seg = seg.strip()
                    if seg.startswith('name='):
                        name = seg[5:].strip('"')
                    if seg.startswith('filename='):
                        filename = seg[9:].strip('"')
        if name:
            parts[name] = {'filename': filename, 'data': file_data}
    return parts

def extract_text(data, filename):
    ext = (filename or '').lower().split('.')[-1] if filename else ''
    if ext in ('txt', 'md', 'csv', 'html', 'json'):
        return data.decode('utf-8', errors='replace')
    if ext == 'pdf':
        import tempfile
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
        tmp.write(data)
        tmp.close()
        try:
            import fitz
            doc = fitz.open(tmp.name)
            text = '\n'.join(page.get_text() for page in doc)
            doc.close()
            os.unlink(tmp.name)
            return text
        except ImportError:
            os.unlink(tmp.name)
            return f'[PDF extraction requires PyMuPDF: content length {len(data)} bytes]'
        except Exception as e:
            os.unlink(tmp.name)
            return f'[PDF error: {e}]'
    return f'[{ext} extraction not supported]'

def search_texts(query, docs):
    if not query or not docs:
        return []
    terms = [t.lower() for t in re.findall(r'\w+', query) if len(t) > 2]
    scored = []
    for doc in docs:
        text = (doc.get('text', '') or '').lower()
        score = sum(term in text for term in terms)
        if score > 0:
            snippet = doc['text'][:500] if len(doc['text']) > 500 else doc['text']
            scored.append({'filename': doc['filename'], 'score': score, 'snippet': snippet})
    scored.sort(key=lambda x: -x['score'])
    return scored

def verify_token(auth_header):
    if not auth_header or not auth_header.startswith('Bearer '):
        return None
    t = auth_header[7:]
    p = os.path.join(AUTH_DIR, t)
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return None

def app(environ, start_response):
    path = environ.get('PATH_INFO', '').lstrip('/') or ''
    method = environ.get('REQUEST_METHOD', 'GET')
    qs = environ.get('QUERY_STRING', '')
    params = parse_qs(qs)
    cl = int(environ.get('CONTENT_LENGTH', '0'))
    body = environ['wsgi.input'].read(cl) if cl > 0 else b''
    ct = environ.get('CONTENT_TYPE', '')
    ah = environ.get('HTTP_AUTHORIZATION', '')

    if method == 'OPTIONS':
        start_response('200 OK', CORS_HEADERS)
        return [b'']

    route_path = (params.get('path', [''])[0] or path).lstrip('/')

    if route_path.startswith('api/'):
        route_path = route_path[4:]

    if route_path.startswith('auth/token') and method == 'POST':
        token = 'tok_' + uuid.uuid4().hex[:24]
        user_id = 'user'
        try:
            if body:
                d = json.loads(body.decode())
                user_id = d.get('user_id', 'user')
        except: pass
        with open(os.path.join(AUTH_DIR, token), 'w') as f:
            json.dump({'user_id': user_id, 'created': datetime.utcnow().isoformat()}, f)
        return json_response(start_response, {'access_token': token, 'token_type': 'bearer'})

    user = verify_token(ah)
    if not user:
        return json_response(start_response, {'detail': 'Invalid token'}, '401 Unauthorized')

    if route_path.startswith('upload') and method == 'POST':
        parts = parse_multipart(body, ct)
        f = parts.get('file', {})
        if not f or not f.get('data'):
            return json_response(start_response, {'detail': 'No file'}, '400 Bad Request')
        filename = f['filename'] or 'unnamed'
        fpath = os.path.join(DOCS_DIR, filename)
        with open(fpath, 'wb') as out:
            out.write(f['data'])
        text = extract_text(f['data'], filename)
        with open(fpath + '.meta', 'w') as out:
            json.dump({'filename': filename, 'text': text, 'size': len(f['data']), 'uploaded': datetime.utcnow().isoformat()}, out)
        return json_response(start_response, {'filename': filename, 'chunks': max(1, len(text) // 500)})

    if route_path.startswith('documents') and method == 'GET':
        docs = []
        for fn in os.listdir(DOCS_DIR):
            if fn.endswith('.meta'):
                with open(os.path.join(DOCS_DIR, fn)) as f:
                    meta = json.load(f)
                    docs.append(meta['filename'])
        return json_response(start_response, {'documents': docs})

    if route_path.startswith('ask') and method == 'POST':
        q_params = parse_qs(qs)
        question = (q_params.get('question', [''])[0] or '')
        if not question:
            return json_response(start_response, {'detail': 'No question'}, '400 Bad Request')

        docs = []
        for fn in os.listdir(DOCS_DIR):
            if fn.endswith('.meta'):
                with open(os.path.join(DOCS_DIR, fn)) as f:
                    meta = json.load(f)
                    docs.append(meta)

        results = search_texts(question, docs)
        if results:
            answer = f'Found {len(results)} relevant document(s)\n\n'
            for r in results:
                answer += f'From {r["filename"]}:\n{r["snippet"][:300]}\n---\n'
            used_docs = list(set(r['filename'] for r in results))
        else:
            doc_names = [d['filename'] for d in docs]
            if doc_names:
                answer = f'No specific matches found. Try asking about: {", ".join(doc_names)}'
                used_docs = doc_names
            else:
                answer = 'No documents uploaded yet. Upload a file to get started.'
                used_docs = []
        resp = json.dumps({'answer': answer, 'sources': [], 'filenames': used_docs, 'type': 'done'}).encode()
        h = [('Content-Type', 'application/json; charset=utf-8')] + CORS_HEADERS
        start_response('200 OK', h)
        return [resp]

    dir_path = os.path.dirname(os.path.abspath(__file__))
    for p in [
        os.path.join(dir_path, '..', 'static', 'index.html'),
        os.path.join(dir_path, '..', 'public', 'static', 'index.html'),
        os.path.join(dir_path, '..', 'index.html'),
    ]:
        if os.path.exists(p):
            with open(p, 'rb') as f:
                content = f.read()
            start_response('200 OK', [('Content-Type', 'text/html; charset=utf-8')] + CORS_HEADERS)
            return [content]

    return json_response(start_response, {'error': 'Not found'}, '404 Not Found')
