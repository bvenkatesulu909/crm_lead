import http.server, pathlib
LOG = pathlib.Path("/data/alerts-received.jsonl")
LOG.parent.mkdir(parents=True, exist_ok=True)
if LOG.exists():
    LOG.unlink()
class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(n)
        with LOG.open("ab") as f:
            f.write(body + b"\n")
        self.send_response(200); self.end_headers()
    def log_message(self, *a): pass
http.server.HTTPServer(("0.0.0.0", 9999), H).serve_forever()
