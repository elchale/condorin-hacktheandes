"""FIXTURE: a local, in-memory stand-in for the Atomic Memory HTTP API. It is not Atomic Memory.

It answers only the routes expedientes/notas.py calls, with the request and response fields of the official
HTTP reference (docs.atomicstrata.ai/api-reference/http): POST /v1/memories/ingest/quick,
POST /v1/memories/search/fast, GET and DELETE /v1/memories/{id}. Memories are partitioned by `user_id`, the
bearer key is checked, and search ranks by shared words (no embeddings). Used by the tests and the local demo:

    python -m expedientes.tests.atomic_memory_fixture --port 4610 --key fixture-key
"""
import argparse
import json
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

WORD = re.compile(r'\w+', re.UNICODE)


class FixtureState:
    def __init__(self, key: str):
        self.key = key
        self.memories: dict[str, dict] = {}
        self.requests: list[dict] = []
        self.fail_status: int | None = None  # answer every call with this status
        self.fail_delete = False             # only DELETE fails (a correction whose old note stays)
        self.delay = 0.0                     # seconds before answering (timeouts)
        self.store_nothing = False           # ingest answers 200 without a stored id
        # (method, path) -> (status, raw body bytes, extra headers) or None: malformed, redirected or huge answers.
        self.override = None
        self.lock = threading.Lock()


def _words(text: str) -> set[str]:
    return {w.lower() for w in WORD.findall(text or '') if len(w) > 2}


def make_handler(state: FixtureState):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, status: int, body, headers: dict | None = None):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(data)

        def _handle(self, method: str):
            url = urlparse(self.path)
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            length = int(self.headers.get('Content-Length') or 0)
            body = json.loads(self.rfile.read(length) or b'{}') if length else {}
            with state.lock:
                state.requests.append({'method': method, 'path': url.path, 'query': query, 'body': body,
                                       'authorization': self.headers.get('Authorization')})
            if state.delay:
                time.sleep(state.delay)
            if self.headers.get('Authorization') != f'Bearer {state.key}':
                return self._send(401, {'error': 'unauthorized'})
            if state.fail_status:
                return self._send(state.fail_status, {'error': 'fixture failure', 'retryable': True})
            forced = state.override(method, url.path) if state.override else None
            if forced is not None:
                return self._send(*forced)

            if method == 'POST' and url.path == '/v1/memories/ingest/quick':
                return self._ingest(body)
            if method == 'POST' and url.path == '/v1/memories/search/fast':
                return self._search(body)
            match = re.fullmatch(r'/v1/memories/([0-9a-f-]{36})', url.path)
            if match and method in ('GET', 'DELETE'):
                return self._one(method, match.group(1), query)
            return self._send(404, {'error': 'route not in the fixture'})

        def _ingest(self, body):
            if not body.get('user_id') or not body.get('conversation') or not body.get('source_site'):
                return self._send(400, {'error': 'user_id, conversation and source_site are required'})
            if state.store_nothing:
                ids = []
            else:
                memory_id = str(uuid.uuid4())
                with state.lock:
                    state.memories[memory_id] = {
                        'id': memory_id, 'user_id': body['user_id'], 'content': body['conversation'],
                        'source_site': body['source_site'], 'metadata': body.get('metadata') or {},
                        'created_at': datetime.now(timezone.utc).isoformat(),
                    }
                ids = [memory_id]
            return self._send(200, {
                'episode_id': str(uuid.uuid4()), 'facts_extracted': 0, 'memories_stored': len(ids),
                'memories_updated': 0, 'memories_deleted': 0, 'memories_skipped': 0, 'stored_memory_ids': ids,
                'updated_memory_ids': [], 'links_created': 0, 'composites_created': 0,
            })

        def _search(self, body):
            if not body.get('user_id') or not body.get('query'):
                return self._send(400, {'error': 'user_id and query are required'})
            wanted = _words(body['query'])
            with state.lock:
                rows = [m for m in state.memories.values() if m['user_id'] == body['user_id']
                        and (not body.get('source_site') or m['source_site'] == body['source_site'])]
            scored = sorted(((len(wanted & _words(m['content'])), m) for m in rows),
                            key=lambda pair: (-pair[0], pair[1]['created_at']))
            hits = [{**{k: m[k] for k in ('id', 'content', 'metadata', 'created_at', 'source_site')},
                     'score': score, 'relevance': min(1.0, score / max(1, len(wanted)))}
                    for score, m in scored if score][:int(body.get('limit') or 10)]
            return self._send(200, {'memories': hits, 'count': len(hits), 'injection_text': '', 'citations': []})

        def _one(self, method, memory_id, query):
            if not query.get('user_id'):
                return self._send(400, {'error': 'user_id (string) is required'})
            with state.lock:
                memory = state.memories.get(memory_id)
                if memory is None or memory['user_id'] != query['user_id']:
                    return self._send(404, {'error': 'Memory not found'})
                if method == 'GET':
                    return self._send(200, memory)
                if state.fail_delete:
                    return self._send(503, {'error': 'fixture failure', 'retryable': True})
                del state.memories[memory_id]
            return self._send(200, {'success': True})

        def do_POST(self):
            self._handle('POST')

        def do_GET(self):
            self._handle('GET')

        def do_DELETE(self):
            self._handle('DELETE')

    return Handler


def start(key: str = 'fixture-key', port: int = 0) -> tuple[ThreadingHTTPServer, FixtureState]:
    """Starts the fixture on 127.0.0.1 (port 0: any free port) in a daemon thread."""
    state = FixtureState(key)
    server = ThreadingHTTPServer(('127.0.0.1', port), make_handler(state))
    threading.Thread(target=server.serve_forever, daemon=True, name='atomic-memory-fixture').start()
    return server, state


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='FIXTURE: fake Atomic Memory HTTP API for local demos.')
    parser.add_argument('--port', type=int, default=4610)
    parser.add_argument('--key', default='fixture-key')
    args = parser.parse_args()
    server, _ = start(args.key, args.port)
    print(f'FIXTURE Atomic Memory (not the real service) on http://127.0.0.1:{args.port}', flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        server.shutdown()
