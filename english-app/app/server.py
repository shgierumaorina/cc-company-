"""英語リスニング・ラボのWebサーバー（標準ライブラリのみ）。

Render: 環境変数 PORT で起動。APP_PASSWORD を設定するとパスワード保護（Basic認証）。
手元: python -m app.server → http://localhost:8765
"""
import base64
import hmac
import json
import mimetypes
import os
import re
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import api, gemini, store, talk, turso

STATIC = os.path.join(store.BASE, "static")
OPEN_PATHS = ("/api/health", "/static/")  # パスワードなしで開ける（アイコン等）


class Handler(BaseHTTPRequestHandler):
    server_version = "ListeningLab/1.0"

    def log_message(self, fmt, *args):
        pass

    def _authorized(self, path):
        password = os.environ.get("APP_PASSWORD", "")
        if not password or path.startswith(OPEN_PATHS):
            return True
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Basic "):
            try:
                supplied = base64.b64decode(auth[6:]).decode("utf-8").split(":", 1)[-1]
            except (ValueError, UnicodeDecodeError):
                supplied = ""
            if hmac.compare_digest(supplied.encode("utf-8"), password.encode("utf-8")):
                return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Listening Lab", charset="UTF-8"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def _json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _static(self, path, ctype=None):
        if not os.path.isfile(path):
            return self.send_error(404)
        with open(path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype or mimetypes.guess_type(path)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, url):
        self.send_response(302)
        self.send_header("Location", url)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        p = urllib.parse.urlparse(self.path).path
        if not self._authorized(p):
            return
        try:
            if p == "/api/health":
                return self._json({"ok": True})
            if p in ("/", "/index.html"):
                return self._static(os.path.join(STATIC, "index.html"), "text/html; charset=utf-8")
            if p.startswith("/static/"):
                name = os.path.normpath(p[len("/static/"):])
                if name.startswith("..") or os.path.isabs(name):
                    return self.send_error(403)
                ctype = "application/manifest+json" if name.endswith("manifest.json") else None
                return self._static(os.path.join(STATIC, name), ctype)
            if p.startswith("/audio/"):
                # 音声は保存せず、番組の配信元から直接再生する
                meta = store.episode_meta(re.sub(r"[^0-9a-f]", "", p[len("/audio/"):]))
                if not meta.get("audio_url"):
                    return self.send_error(404)
                return self._redirect(meta["audio_url"])
            if p == "/api/state":
                return self._json(api.public_state())
            if p.startswith("/api/episode/"):
                ep_id = re.sub(r"[^0-9a-f]", "", p[len("/api/episode/"):])
                return self._json({"meta": store.episode_meta(ep_id),
                                   "sections": store.get(f"ep:{ep_id}:sections", [])})
            if p == "/api/talks":
                return self._json(talk.summaries())
            if p.startswith("/api/talk/"):
                tid = re.sub(r"[^0-9A-Za-z-]", "", p[len("/api/talk/"):])
                return self._json(store.get(f"talk:{tid}", {}))
            self.send_error(404)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    def do_POST(self):
        p = urllib.parse.urlparse(self.path).path
        if not self._authorized(p):
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
            result = api.route(p, body)
            if result is None:
                return self.send_error(404)
            self._json(result)
        except (ValueError, gemini.GeminiError) as e:
            self._json({"error": str(e)}, 400)
        except turso.TursoError as e:
            self._json({"error": f"データベースエラー: {e}"}, 502)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)


def main():
    store.ensure_ready()
    port = int(os.environ.get("PORT", "8765"))
    host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    srv = ThreadingHTTPServer((host, port), Handler)
    print(f"Listening Lab on http://{host}:{port}  (cloud={store.CLOUD})", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
