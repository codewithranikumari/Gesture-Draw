import json
import logging
import mimetypes
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen

from studio import DrawingStudio


HOST = "127.0.0.1"
PORT = 8765
WEB_ROOT = Path(__file__).with_name("web")
STATIC_FILES = {
    "/static/styles.css": WEB_ROOT / "static" / "styles.css",
    "/static/app.js": WEB_ROOT / "static" / "app.js",
}
LOGGER = logging.getLogger("gesture_draw")


class GestureDrawServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def __init__(self, address, handler):
        self.studio = DrawingStudio()
        super().__init__(address, handler)
        self.daemon_threads = True

    def server_close(self):
        self.studio.close()
        super().server_close()


class RequestHandler(BaseHTTPRequestHandler):

    server: GestureDrawServer

    def do_GET(self):
        route = urlsplit(self.path).path
        if route in ("/", "/rules", "/studio"):
            self._send_file(WEB_ROOT / "templates" / "index.html")
        elif route in STATIC_FILES:
            self._send_file(STATIC_FILES[route])
        elif route == "/api/status":
            self._send_json(200, self.server.studio.state())
        elif route == "/video_feed":
            self._stream_video()
        else:
            self._send_json(404, {"error": "Page not found."})

    def do_POST(self):
        if not self._same_origin():
            self._send_json(403, {"error": "Request did not originate from this application."})
            return

        route = urlsplit(self.path).path
        try:
            payload = self._read_json()
            if route == "/api/studio/start":
                result = self.server.studio.start(payload.get("confirmed"))
                self._send_json(202, result)
            elif route == "/api/studio/stop":
                self._send_json(202, self.server.studio.stop())
            elif route == "/api/studio/clear":
                self.server.studio.clear()
                self._send_json(200, {"message": "Canvas cleared."})
            elif route == "/api/studio/color":
                self.server.studio.select_color(payload.get("index"))
                self._send_json(200, {"message": "Drawing color changed."})
            elif route == "/api/studio/eraser":
                self._send_json(200, self.server.studio.toggle_eraser())
            elif route == "/api/studio/save":
                filename = self.server.studio.save_artwork()
                self._send_json(200, {"message": "Artwork saved.", "filename": filename})
            else:
                self._send_json(404, {"error": "Action not found."})
        except (ValueError, RuntimeError) as error:
            self._send_json(400, {"error": str(error)})
        except json.JSONDecodeError:
            self._send_json(400, {"error": "Request body must be valid JSON."})

    def _same_origin(self):
        origin = self.headers.get("Origin")
        if not origin:
            return True
        parsed = urlsplit(origin)
        return parsed.scheme == "http" and parsed.netloc == self.headers.get("Host")

    def _read_json(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length < 0 or content_length > 4096:
            raise ValueError("Request body is too large.")
        raw_body = self.rfile.read(content_length)
        if not raw_body:
            return {}
        payload = json.loads(raw_body)
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object.")
        return payload

    def _send_file(self, path):
        try:
            body = path.read_bytes()
        except OSError:
            self._send_json(404, {"error": "Application file not found."})
            return

        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in ("application/javascript",):
            content_type += "; charset=utf-8"
        self.send_response(200)
        self._security_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self._security_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _security_headers(self):
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'self'; connect-src 'self'; object-src 'none'; "
            "base-uri 'self'; frame-ancestors 'none'"
        )
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")

    def _stream_video(self):
        if self.server.studio.state()["status"] == "idle":
            self._send_json(409, {"error": "Launch the drawing studio first."})
            return

        boundary = b"--gesture-draw-frame\r\n"
        self.send_response(200)
        self._security_headers()
        self.send_header(
            "Content-Type",
            "multipart/x-mixed-replace; boundary=gesture-draw-frame"
        )
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.end_headers()

        last_frame = None
        try:
            while True:
                state = self.server.studio.state()
                frame = self.server.studio.latest_frame()
                if frame is not None and frame != last_frame:
                    self.wfile.write(boundary)
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode("ascii"))
                    self.wfile.write(frame + b"\r\n")
                    self.wfile.flush()
                    last_frame = frame
                elif state["status"] in ("idle", "standby", "error"):
                    break
                time.sleep(0.03)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return

    def log_message(self, format_string, *args):
        return


def run_server():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    url = f"http://{HOST}:{PORT}/"
    try:
        server = GestureDrawServer((HOST, PORT), RequestHandler)
    except OSError as error:
        try:
            with urlopen(f"{url}api/status", timeout=2) as response:
                status = json.loads(response.read().decode("utf-8"))
        except (OSError, ValueError) as probe_error:
            raise RuntimeError(
                f"Could not start Gesture Draw at {url}; port {PORT} is already in use."
            ) from probe_error

        if not isinstance(status, dict) or not {"status", "camera"}.issubset(status):
            raise RuntimeError(f"Port {PORT} is occupied by another application.") from error

        print(f"Gesture Draw is already running at {url}")
        if not webbrowser.open(url):
            print("Open the URL above in your browser.")
        return

    print(f"GESTURE DRAW is running at {url}")
    if not webbrowser.open(url):
        print("Open the URL above in your browser.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping GESTURE DRAW...")
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    run_server()
