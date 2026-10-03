"""Serve the dashboard assets on loopback for the mocked Playwright UI test."""

import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

STATIC_ROOT = Path(__file__).resolve().parents[1] / "dashboard" / "static"


class AssetHandler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        names = {"/": "index.html", "/assets/app.js": "app.js", "/assets/style.css": "style.css"}
        return str(STATIC_ROOT / names.get(urlsplit(path).path, "__not_found__"))

    def end_headers(self):
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' https: data:; connect-src 'self'; base-uri 'none'; "
            "frame-ancestors 'none'; form-action 'self'",
        )
        super().end_headers()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8088)
    args = parser.parse_args()
    with ThreadingHTTPServer(("127.0.0.1", args.port), AssetHandler) as server:
        print(f"Static test assets: http://127.0.0.1:{args.port}", flush=True)
        server.serve_forever()
