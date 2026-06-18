#!/usr/bin/env python3
"""Static file server for the BBTV web page with no-cache headers, so browsers
always pull the latest index.html/app.js/style.css instead of a stale cached
copy (the plain `http.server` lets browsers cache the page indefinitely, which
stranded viewers on an old UI after a deploy). Usage:
    serve_nocache.py [PORT] [--directory DIR]
"""
import argparse
import http.server
import socketserver


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("port", nargs="?", type=int, default=8788)
    ap.add_argument("--directory", default=".")
    a = ap.parse_args()
    handler = lambda *args, **kw: NoCacheHandler(*args, directory=a.directory, **kw)
    with socketserver.ThreadingTCPServer(("", a.port), handler) as httpd:
        httpd.allow_reuse_address = True
        print(f"no-cache static server on :{a.port} ({a.directory})", flush=True)
        httpd.serve_forever()


if __name__ == "__main__":
    main()
