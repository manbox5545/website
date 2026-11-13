"""
Mpoxel AI - low-latency streaming backend
Run:
    Windows PowerShell:
        $env:GEMINI_API_KEY="YOUR_KEY"
        python server.py

    Linux/macOS:
        export GEMINI_API_KEY="YOUR_KEY"
        python server.py

Required environment variables:
    GEMINI_API_KEY=your_gemini_key
    CLOUDFLARE_ACCOUNT_ID=your_account_id
    CLOUDFLARE_API_TOKEN=your_cloudflare_token

Optional environment variables:
    GEMINI_MODEL=gemini-3.5-flash-lite
    MAX_CONCURRENT_REQUESTS=4
    MAX_QUEUE_SIZE=30
    CLOUDFLARE_ACCOUNT_ID=your_account_id
    CLOUDFLARE_API_TOKEN=your_secret_token
    PORT=8000
"""

import json
import os
import random
import socket
import threading
import time
import urllib.error
import urllib.request
import urllib.parse
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

# -------------------- CONFIG --------------------

# Keep API credentials in environment variables, never in source code.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
CLOUDFLARE_ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
CLOUDFLARE_API_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()


CLOUDFLARE_IMAGE_MODEL = os.environ.get("CLOUDFLARE_IMAGE_MODEL", "@cf/black-forest-labs/flux-1-schnell").strip()
# Flash-Lite is Google's low-latency, high-throughput choice.
# Change via GEMINI_MODEL if you prefer a different supported model.
GEMINI_MODEL = os.environ.get(
    "GEMINI_MODEL", "gemini-3.5-flash-lite"
).strip()

HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", "8000"))

MAX_CONCURRENT_REQUESTS = max(
    1, int(os.environ.get("MAX_CONCURRENT_REQUESTS", "4"))
)
MAX_QUEUE_SIZE = max(1, int(os.environ.get("MAX_QUEUE_SIZE", "30")))
QUEUE_WAIT_SECONDS = 12
CONNECT_AND_READ_TIMEOUT = 75

MAX_HISTORY_MESSAGES = 6
MAX_MESSAGE_LENGTH = 8000
MAX_OUTPUT_TOKENS = 1536
MAX_ATTACHMENTS = 4
MAX_BODY_BYTES = 24 * 1024 * 1024
MAX_RETRIES = 1

BASE_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = BASE_DIR / "public" if (BASE_DIR / "public" / "index.html").is_file() else BASE_DIR

API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/"
    f"models/{GEMINI_MODEL}:streamGenerateContent?alt=sse"
)
GEMINI_GENERATE_URL = (
    "https://generativelanguage.googleapis.com/v1beta/"
    f"models/{GEMINI_MODEL}:generateContent"
)

slots = threading.BoundedSemaphore(MAX_CONCURRENT_REQUESTS)
queue_lock = threading.Lock()
waiting_requests = 0


# -------------------- GEMINI --------------------

def error_message(body):
    try:
        data = json.loads(body)
        return data.get("error", {}).get("message", "Unknown Gemini error")
    except (ValueError, TypeError):
        return str(body)[:500]


def is_daily_quota_error(message):
    value = message.lower()
    return any(term in value for term in (
        "per day", "per_day", "daily quota",
        "requests per day", "daily limit"
    ))


MIME_BY_EXTENSION = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "jpe": "image/jpeg",
    "png": "image/png", "gif": "image/gif", "webp": "image/webp",
    "bmp": "image/bmp", "heic": "image/heic", "heif": "image/heif",
    "avif": "image/avif", "pdf": "application/pdf",
    "txt": "text/plain", "md": "text/markdown", "csv": "text/csv",
    "json": "application/json", "js": "text/javascript", "mjs": "text/javascript",
    "html": "text/html", "htm": "text/html", "css": "text/css",
    "xml": "text/xml", "py": "text/x-python", "log": "text/plain",
    "yaml": "text/plain", "yml": "text/plain", "sql": "text/plain",
    "mp3": "audio/mpeg", "wav": "audio/wav", "m4a": "audio/mp4",
    "aac": "audio/aac", "ogg": "audio/ogg", "flac": "audio/flac",
    "aiff": "audio/aiff", "mp4": "video/mp4", "mpeg": "video/mpeg",
    "mpg": "video/mpg", "mov": "video/quicktime", "webm": "video/webm",
    "m4v": "video/mp4", "avi": "video/avi", "wmv": "video/wmv",
    "flv": "video/x-flv", "3gp": "video/3gpp",
}

# Supported media types for Gemini inline_data. Keep this list explicit so
# unsupported uploads never fall through as application/octet-stream.
GEMINI_INLINE_MIME_TYPES = {
    "image/png", "image/jpeg", "image/jpg", "image/webp", "image/bmp",
    "image/heic", "image/heif", "image/gif", "image/avif",
    "application/pdf", "application/json", "application/rtf",
    "text/plain", "text/html", "text/css", "text/xml", "text/csv",
    "text/rtf", "text/javascript", "text/markdown", "text/x-python",
    "text/x-typescript", "audio/mpeg", "audio/mp3", "audio/wav",
    "audio/aac", "audio/ogg", "audio/flac", "audio/aiff", "audio/mp4",
    "video/mp4", "video/mpeg", "video/mpg", "video/quicktime",
    "video/avi", "video/x-flv", "video/webm", "video/wmv", "video/3gpp",
}


def resolve_attachment_mime_type(attachment):
    """Resolve a real MIME type from frontend metadata, data URL, or extension."""
    supplied = (
        attachment.get("contentType")
        or attachment.get("mimeType")
        or attachment.get("mime_type")
        or ""
    )
    mime_type = str(supplied).split(";", 1)[0].strip().lower()

    # If a data URL was supplied, its declared media type is more specific
    # than a generic browser MIME value.
    data = attachment.get("data", "")
    data_url_mime = ""
    if isinstance(data, str) and data.startswith("data:") and "," in data:
        header = data.split(",", 1)[0]
        data_url_mime = header[5:].split(";", 1)[0].strip().lower()

    if data_url_mime and data_url_mime not in (
        "application/octet-stream", "binary/octet-stream"
    ):
        mime_type = data_url_mime

    if mime_type in ("image/jpg",):
        mime_type = "image/jpeg"

    if mime_type in ("application/octet-stream", "binary/octet-stream", ""):
        filename = str(attachment.get("name", ""))
        extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        mime_type = MIME_BY_EXTENSION.get(extension, "")

    if mime_type not in GEMINI_INLINE_MIME_TYPES:
        filename = str(attachment.get("name", "unknown file"))
        raise ValueError(
            f"Unsupported or unknown file type for {filename} "
            f"({mime_type or 'unknown MIME type'}). "
            "Upload a supported image, PDF, audio, video, or text file."
        )

    return mime_type


def build_payload(user_text, history, attachments):
    contents = []

    # Keep recent context only. Avoid sending oversized histories every turn.
    for item in history[-MAX_HISTORY_MESSAGES:]:
        if not isinstance(item, dict):
            continue

        role = item.get("role", "user")
        if role not in ("user", "model"):
            continue

        old_text = str(item.get("text", ""))[:MAX_MESSAGE_LENGTH]
        if old_text.strip():
            contents.append({
                "role": role,
                "parts": [{"text": old_text}]
            })

    parts = [{"text": user_text[:MAX_MESSAGE_LENGTH]}]

    for attachment in attachments[:MAX_ATTACHMENTS]:
        if not isinstance(attachment, dict):
            continue

        data = attachment.get("data", "")
        if not isinstance(data, str) or not data:
            continue

        mime_type = resolve_attachment_mime_type(attachment)

        # If the frontend sends a data URL, use its MIME type when useful
        # and strip the prefix before forwarding the base64 payload.
        if data.startswith("data:") and "," in data:
            header, data = data.split(",", 1)
            data_url_mime = header[5:].split(";", 1)[0].strip().lower()
            if data_url_mime and data_url_mime not in (
                "application/octet-stream", "binary/octet-stream"
            ):
                mime_type = data_url_mime
            if mime_type == "image/jpg":
                mime_type = "image/jpeg"

        parts.append({
            "inline_data": {
                "mime_type": mime_type,
                "data": data
            }
        })

    contents.append({"role": "user", "parts": parts})

    return {
        "contents": contents,
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": MAX_OUTPUT_TOKENS,
            "candidateCount": 1
        }
    }


def open_gemini_stream(payload):
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "x-goog-api-key": GEMINI_API_KEY,
            "Connection": "keep-alive"
        },
        method="POST"
    )

    for attempt in range(MAX_RETRIES + 1):
        try:
            return urllib.request.urlopen(
                request, timeout=CONNECT_AND_READ_TIMEOUT
            )

        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            message = error_message(raw)

            if exc.code == 429 and is_daily_quota_error(message):
                raise RuntimeError(
                    "Gemini daily quota is exhausted. Try after the quota resets."
                ) from None

            retryable = exc.code in (429, 500, 502, 503, 504)
            if not retryable or attempt >= MAX_RETRIES:
                raise RuntimeError(
                    f"Gemini API error ({exc.code}): {message}"
                ) from None

            # Respect Retry-After where provided; keep retry delay short.
            retry_after = exc.headers.get("Retry-After")
            try:
                delay = min(float(retry_after), 2.5) if retry_after else 0.8
            except (TypeError, ValueError):
                delay = 0.8
            time.sleep(delay + random.uniform(0.05, 0.25))

        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            if attempt >= MAX_RETRIES:
                reason = getattr(exc, "reason", exc)
                raise RuntimeError(
                    f"Gemini connection failed: {reason}"
                ) from None
            time.sleep(0.4 + random.uniform(0.05, 0.2))

    raise RuntimeError("Gemini request failed.")


def extract_text_from_sse_data(data_line):
    """Convert one Gemini SSE data payload into text chunks."""
    if not data_line or data_line == "[DONE]":
        return []

    try:
        chunk = json.loads(data_line)
    except json.JSONDecodeError:
        return []

    output = []
    for candidate in chunk.get("candidates", []):
        content = candidate.get("content") or {}
        for part in content.get("parts", []):
            # Do not expose internal thought parts if the API returns them.
            if part.get("thought") is True:
                continue
            value = part.get("text")
            if isinstance(value, str) and value:
                output.append(value)
    return output


# -------------------- HTTP HANDLER --------------------

class MpoxelHandler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC_DIR), **kwargs)

    def setup(self):
        super().setup()
        try:
            self.connection.setsockopt(
                socket.IPPROTO_TCP, socket.TCP_NODELAY, 1
            )
        except OSError:
            pass

    def send_json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def send_sse(self, data):
        packet = (
            "data: " + json.dumps(data, ensure_ascii=False) + "\n\n"
        ).encode("utf-8")
        self.wfile.write(packet)
        self.wfile.flush()

    def handle_image_prompt(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 12000:
                self.send_json(413, {"error": "Prompt request is invalid or too large."})
                return
            payload = json.loads(self.rfile.read(length))
            prompt = str(payload.get("prompt", "")).strip()
            if not prompt or len(prompt) > 1800:
                self.send_json(400, {"error": "Prompt must be 1–1800 characters."})
                return
            if not GEMINI_API_KEY:
                self.send_json(500, {"error": "Set GEMINI_API_KEY in the server environment."})
                return
            request_body = {
                "contents": [{"role": "user", "parts": [{
                    "text": (
                        "Convert the user's image request into one detailed, safe, "
                        "visual image-generation prompt. Preserve the requested subject, "
                        "style, composition, and mood. Return only the prompt, no quotes "
                        "or explanation. User request: " + prompt
                    )
                }]}],
                "generationConfig": {"temperature": 0.4, "maxOutputTokens": 300}
            }
            req = urllib.request.Request(
                GEMINI_GENERATE_URL,
                data=json.dumps(request_body).encode("utf-8"),
                headers={"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=35) as response:
                result = json.loads(response.read().decode("utf-8"))
            parts = result.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            enhanced = " ".join(str(part.get("text", "")) for part in parts).strip()
            if not enhanced:
                raise RuntimeError("Gemini returned an empty image prompt.")
            self.send_json(200, {"prompt": enhanced[:3000]})
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            self.send_json(502, {"error": "Gemini prompt error: " + error_message(detail)})
        except Exception as exc:
            self.send_json(502, {"error": str(exc)[:500]})

    def handle_image_generation(self):
        """Generate an image through Cloudflare Workers AI REST; credentials stay server-side."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 12000:
                self.send_json(413, {"error": "Image request is invalid or too large."})
                return
            payload = json.loads(self.rfile.read(length))
            prompt = str(payload.get("prompt", "")).strip()
            if not prompt or len(prompt) > 2048:
                self.send_json(400, {"error": "Image prompt must be 1–2048 characters."})
                return
            if not CLOUDFLARE_ACCOUNT_ID or not CLOUDFLARE_API_TOKEN:
                self.send_json(503, {"error": "Set CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN on the server."})
                return
            endpoint = (
                "https://api.cloudflare.com/client/v4/accounts/"
                + urllib.parse.quote(CLOUDFLARE_ACCOUNT_ID, safe="")
                + "/ai/run/"
                + CLOUDFLARE_IMAGE_MODEL
            )
            req = urllib.request.Request(
                endpoint,
                data=json.dumps({"prompt": prompt, "steps": 4}).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer " + CLOUDFLARE_API_TOKEN,
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=90) as upstream:
                result = json.loads(upstream.read().decode("utf-8"))
            if result.get("success") is False:
                raise RuntimeError("Cloudflare image generation failed.")
            data = result.get("result", result)
            image = data.get("image") if isinstance(data, dict) else None
            if not image:
                raise RuntimeError("Cloudflare did not return an image.")
            self.send_json(200, {"image": "data:image/jpeg;base64," + image})
        except urllib.error.HTTPError as exc:
            detail = exc.read(2048).decode("utf-8", errors="replace")
            self.send_json(502, {"error": "Cloudflare error (" + str(exc.code) + "): " + error_message(detail)[:300]})
        except (ValueError, json.JSONDecodeError):
            self.send_json(400, {"error": "Invalid image request JSON."})
        except Exception as exc:
            self.send_json(502, {"error": "Image generation failed: " + str(exc)[:250]})

    def do_POST(self):
        global waiting_requests

        if self.path == "/api/generate-image":
            self.handle_image_generation()
            return
        if self.path == "/api/image-prompt":
            self.handle_image_prompt()
            return
        if self.path != "/api/chat":
            self.send_json(404, {"error": "Endpoint not found"})
            return

        stream_started = False
        acquired = False
        upstream = None

        try:
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                content_length = 0

            if content_length <= 0 or content_length > MAX_BODY_BYTES:
                self.send_json(413, {"error": "Request size is invalid or too large."})
                return

            raw = self.rfile.read(content_length)
            try:
                request_data = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                self.send_json(400, {"error": "Invalid JSON request."})
                return

            if not isinstance(request_data, dict):
                self.send_json(400, {"error": "Invalid request format."})
                return

            user_text = str(request_data.get("text", "")).strip()
            history = request_data.get("history", [])
            attachments = request_data.get("attachments", [])

            if not isinstance(history, list):
                history = []
            if not isinstance(attachments, list):
                attachments = []

            if not user_text and not attachments:
                self.send_json(400, {"error": "Please enter a message."})
                return

            if not GEMINI_API_KEY:
                self.send_json(500, {
                    "error": "GEMINI_API_KEY environment variable is missing."
                })
                return

            # Bound waiting requests so overload fails quickly, not after a
            # long invisible queue.
            with queue_lock:
                if waiting_requests >= MAX_QUEUE_SIZE:
                    self.send_json(503, {
                        "error": "Mpoxel AI is busy. Please retry in a moment."
                    })
                    return
                waiting_requests += 1

            try:
                acquired = slots.acquire(timeout=QUEUE_WAIT_SECONDS)
            finally:
                with queue_lock:
                    waiting_requests -= 1

            if not acquired:
                self.send_json(503, {
                    "error": "Mpoxel AI is busy. Please try again shortly."
                })
                return

            payload = build_payload(user_text, history, attachments)
            upstream = open_gemini_stream(payload)

            # Start the browser stream as soon as Gemini accepts the request.
            self.send_response(200)
            self.send_header(
                "Content-Type", "text/event-stream; charset=utf-8"
            )
            self.send_header("Cache-Control", "no-cache, no-transform")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            stream_started = True

            # Forward each SSE data event immediately; no full-answer buffering.
            for raw_line in upstream:
                if not raw_line:
                    continue

                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue

                data_line = line[5:].strip()
                for generated_text in extract_text_from_sse_data(data_line):
                    self.send_sse({"text": generated_text})

            # Signal normal completion without simulating typing.
            self.send_sse({"done": True})

        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            # Browser closed the tab/request. Release the slot in finally.
            pass

        except Exception as exc:
            message = str(exc)
            if stream_started:
                try:
                    self.send_sse({"error": message, "done": True})
                except (BrokenPipeError, ConnectionError, OSError):
                    pass
            else:
                try:
                    self.send_json(502, {"error": message})
                except (BrokenPipeError, ConnectionError, OSError):
                    pass

        finally:
            if upstream is not None:
                try:
                    upstream.close()
                except Exception:
                    pass
            if acquired:
                slots.release()

    def log_message(self, fmt, *args):
        print("[Mpoxel]", fmt % args)



# -------------------- WSGI APPLICATION (RENDER / PYTHONANYWHERE) --------------------
# Gunicorn imports the callable named "application" on Render. This adapter
# reuses the existing Gemini/Cloudflare logic and does not bind its own port.

def _wsgi_json(start_response, status, data):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    phrase = {
        200: "OK", 400: "Bad Request", 404: "Not Found",
        413: "Payload Too Large", 429: "Too Many Requests",
        500: "Internal Server Error", 502: "Bad Gateway",
        503: "Service Unavailable",
    }.get(status, "Error")
    start_response(
        f"{status} {phrase}",
        [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"),
        ],
    )
    return [body]


def _wsgi_read_json(environ):
    try:
        length = int(environ.get("CONTENT_LENGTH") or "0")
    except (TypeError, ValueError):
        length = 0
    if length <= 0:
        raise ValueError("Request body is empty.")
    if length > MAX_BODY_BYTES:
        raise OverflowError("Request body is too large.")
    raw = environ["wsgi.input"].read(length)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("Invalid JSON request.") from None
    if not isinstance(value, dict):
        raise ValueError("Invalid request format.")
    return value


def _wsgi_stream_gemini(upstream):
    try:
        for raw_line in upstream:
            if not raw_line:
                continue
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data_line = line[5:].strip()
            for generated_text in extract_text_from_sse_data(data_line):
                packet = (
                    "data: " + json.dumps(
                        {"text": generated_text}, ensure_ascii=False
                    ) + "\n\n"
                ).encode("utf-8")
                yield packet

        yield (
            "data: " + json.dumps({"done": True}) + "\n\n"
        ).encode("utf-8")
    except (BrokenPipeError, ConnectionResetError, GeneratorExit):
        # The visitor disconnected; stop reading from Gemini.
        return
    except Exception as exc:
        packet = (
            "data: " + json.dumps(
                {"error": str(exc)[:500], "done": True}, ensure_ascii=False
            ) + "\n\n"
        ).encode("utf-8")
        yield packet
    finally:
        try:
            upstream.close()
        except Exception:
            pass
        slots.release()


def _wsgi_chat(environ, start_response):
    global waiting_requests
    acquired = False
    upstream = None

    try:
        request_data = _wsgi_read_json(environ)
        user_text = str(request_data.get("text", "")).strip()
        history = request_data.get("history", [])
        attachments = request_data.get("attachments", [])

        if not isinstance(history, list):
            history = []
        if not isinstance(attachments, list):
            attachments = []

        if not user_text and not attachments:
            return _wsgi_json(start_response, 400, {"error": "Please enter a message."})
        if not GEMINI_API_KEY:
            return _wsgi_json(
                start_response, 500,
                {"error": "GEMINI_API_KEY environment variable is missing."},
            )

        with queue_lock:
            if waiting_requests >= MAX_QUEUE_SIZE:
                return _wsgi_json(
                    start_response, 503,
                    {"error": "Mpoxel AI is busy. Please retry in a moment."},
                )
            waiting_requests += 1

        try:
            acquired = slots.acquire(timeout=QUEUE_WAIT_SECONDS)
        finally:
            with queue_lock:
                waiting_requests -= 1

        if not acquired:
            return _wsgi_json(
                start_response, 503,
                {"error": "Mpoxel AI is busy. Please try again shortly."},
            )

        payload = build_payload(user_text, history, attachments)
        upstream = open_gemini_stream(payload)

        start_response(
            "200 OK",
            [
                ("Content-Type", "text/event-stream; charset=utf-8"),
                ("Cache-Control", "no-cache, no-transform"),
                ("X-Accel-Buffering", "no"),
                ("Connection", "keep-alive"),
            ],
        )
        # Ownership of the semaphore and upstream response transfers to the
        # generator, which releases both even if the client disconnects.
        return _wsgi_stream_gemini(upstream)

    except OverflowError as exc:
        if acquired:
            slots.release()
        return _wsgi_json(start_response, 413, {"error": str(exc)})
    except ValueError as exc:
        if acquired:
            slots.release()
        return _wsgi_json(start_response, 400, {"error": str(exc)})
    except Exception as exc:
        if upstream is not None:
            try:
                upstream.close()
            except Exception:
                pass
        if acquired:
            slots.release()
        return _wsgi_json(start_response, 502, {"error": str(exc)[:500]})


def _wsgi_image_prompt(environ, start_response):
    try:
        payload = _wsgi_read_json(environ)
        prompt = str(payload.get("prompt", "")).strip()
        if not prompt or len(prompt) > 1800:
            return _wsgi_json(
                start_response, 400,
                {"error": "Prompt must be 1–1800 characters."},
            )
        if not GEMINI_API_KEY:
            return _wsgi_json(
                start_response, 500,
                {"error": "Set GEMINI_API_KEY in the server environment."},
            )

        request_body = {
            "contents": [{"role": "user", "parts": [{
                "text": (
                    "Convert the user's image request into one detailed, safe, "
                    "visual image-generation prompt. Preserve the requested subject, "
                    "style, composition, and mood. Return only the prompt, no quotes "
                    "or explanation. User request: " + prompt
                )
            }]}],
            "generationConfig": {"temperature": 0.4, "maxOutputTokens": 300},
        }
        req = urllib.request.Request(
            GEMINI_GENERATE_URL,
            data=json.dumps(request_body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": GEMINI_API_KEY,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=35) as response:
            result = json.loads(response.read().decode("utf-8"))
        parts = result.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        enhanced = " ".join(
            str(part.get("text", "")) for part in parts
        ).strip()
        if not enhanced:
            raise RuntimeError("Gemini returned an empty image prompt.")
        return _wsgi_json(start_response, 200, {"prompt": enhanced[:3000]})

    except OverflowError as exc:
        return _wsgi_json(start_response, 413, {"error": str(exc)})
    except ValueError as exc:
        return _wsgi_json(start_response, 400, {"error": str(exc)})
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return _wsgi_json(
            start_response, 502,
            {"error": "Gemini prompt error: " + error_message(detail)},
        )
    except Exception as exc:
        return _wsgi_json(start_response, 502, {"error": str(exc)[:500]})


def _wsgi_image_generation(environ, start_response):
    try:
        payload = _wsgi_read_json(environ)
        prompt = str(payload.get("prompt", "")).strip()
        if not prompt or len(prompt) > 2048:
            return _wsgi_json(
                start_response, 400,
                {"error": "Image prompt must be 1–2048 characters."},
            )
        if not CLOUDFLARE_ACCOUNT_ID or not CLOUDFLARE_API_TOKEN:
            return _wsgi_json(
                start_response, 503,
                {"error": "Set CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN on the server."},
            )

        endpoint = (
            "https://api.cloudflare.com/client/v4/accounts/"
            + urllib.parse.quote(CLOUDFLARE_ACCOUNT_ID, safe="")
            + "/ai/run/"
            + CLOUDFLARE_IMAGE_MODEL
        )
        req = urllib.request.Request(
            endpoint,
            data=json.dumps({"prompt": prompt, "steps": 4}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + CLOUDFLARE_API_TOKEN,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=90) as upstream_response:
            result = json.loads(upstream_response.read().decode("utf-8"))
        if result.get("success") is False:
            raise RuntimeError("Cloudflare image generation failed.")
        data = result.get("result", result)
        image_data = data.get("image") if isinstance(data, dict) else None
        if not image_data:
            raise RuntimeError("Cloudflare did not return an image.")
        return _wsgi_json(
            start_response, 200,
            {"image": "data:image/jpeg;base64," + image_data},
        )

    except OverflowError as exc:
        return _wsgi_json(start_response, 413, {"error": str(exc)})
    except ValueError as exc:
        return _wsgi_json(start_response, 400, {"error": "Invalid image request JSON."})
    except urllib.error.HTTPError as exc:
        detail = exc.read(2048).decode("utf-8", errors="replace")
        return _wsgi_json(
            start_response, 502,
            {"error": "Cloudflare error (" + str(exc.code) + "): " + error_message(detail)[:300]},
        )
    except Exception as exc:
        return _wsgi_json(
            start_response, 502,
            {"error": "Image generation failed: " + str(exc)[:250]},
        )


def _mpoxel_wsgi_application(environ, start_response):
    """Core WSGI app. CORS is applied by the public wrapper below."""
    method = environ.get("REQUEST_METHOD", "GET").upper()
    path = urllib.parse.unquote(environ.get("PATH_INFO", "/") or "/")

    if method == "POST":
        if path == "/api/chat":
            return _wsgi_chat(environ, start_response)
        if path == "/api/image-prompt":
            return _wsgi_image_prompt(environ, start_response)
        if path == "/api/generate-image":
            return _wsgi_image_generation(environ, start_response)
        return _wsgi_json(start_response, 404, {"error": "Endpoint not found"})

    if method not in ("GET", "HEAD"):
        return _wsgi_json(start_response, 405, {"error": "Method not allowed"})

    # Render health check. Keep this independent of API credentials so the
    # platform can verify that the web process is alive after deployment.
    if path == "/health":
        return _wsgi_json(start_response, 200, {"status": "ok", "service": "mpoxel-api"})

    # Serve local files only as a fallback. In this deployment the frontend
    # lives on mpoxel.in; the API is hosted separately on PythonAnywhere.
    relative = "index.html" if path == "/" else path.lstrip("/")
    target = (PUBLIC_DIR / relative).resolve()
    try:
        target.relative_to(PUBLIC_DIR.resolve())
    except ValueError:
        return _wsgi_json(start_response, 404, {"error": "File not found"})

    blocked_suffixes = {
        ".py", ".pyc", ".pyo", ".env", ".ini", ".toml",
        ".yaml", ".yml", ".sh", ".bat", ".ps1",
    }
    if any(part.startswith(".") for part in target.relative_to(PUBLIC_DIR.resolve()).parts):
        return _wsgi_json(start_response, 404, {"error": "File not found"})
    if target.suffix.lower() in blocked_suffixes or not target.is_file():
        return _wsgi_json(start_response, 404, {"error": "File not found"})

    content_type = __import__("mimetypes").guess_type(str(target))[0] or "application/octet-stream"
    try:
        size = target.stat().st_size
        start_response(
            "200 OK",
            [
                ("Content-Type", content_type),
                ("Content-Length", str(size)),
                ("Cache-Control", "no-cache" if target.name == "index.html" else "public, max-age=3600"),
            ],
        )
        if method == "HEAD":
            return [b""]
        return [target.read_bytes()]
    except OSError:
        return _wsgi_json(start_response, 500, {"error": "Unable to read requested file."})


# The browser frontend is hosted on mpoxel.in while this API is hosted on
# mpoxel.pythonanywhere.com. Allow only the known frontend origins.
ALLOWED_CORS_ORIGINS = {
    origin.strip().rstrip("/")
    for origin in os.environ.get(
        "MPOXEL_ALLOWED_ORIGINS",
        "https://mpoxel.in,https://www.mpoxel.in"
    ).split(",")
    if origin.strip()
}


def application(environ, start_response):
    """WSGI entry point with restricted cross-origin support."""
    origin = (environ.get("HTTP_ORIGIN") or "").rstrip("/")
    origin_allowed = origin in ALLOWED_CORS_ORIGINS

    def cors_start_response(status, headers, exc_info=None):
        response_headers = list(headers)
        # Vary prevents caches from mixing responses for different origins.
        vary_value = next((value for key, value in response_headers if key.lower() == "vary"), None)
        if vary_value:
            if "Origin" not in [part.strip() for part in vary_value.split(",")]:
                response_headers = [(key, value) for key, value in response_headers if key.lower() != "vary"]
                response_headers.append(("Vary", vary_value + ", Origin"))
        else:
            response_headers.append(("Vary", "Origin"))

        if origin_allowed:
            response_headers.extend([
                ("Access-Control-Allow-Origin", origin),
                ("Access-Control-Allow-Methods", "GET, HEAD, POST, OPTIONS"),
                ("Access-Control-Allow-Headers", "Content-Type, Accept"),
                ("Access-Control-Max-Age", "86400"),
            ])
        return start_response(status, response_headers, exc_info)

    method = environ.get("REQUEST_METHOD", "GET").upper()
    if method == "OPTIONS":
        if not origin_allowed:
            return _wsgi_json(start_response, 403, {"error": "Origin not allowed."})
        requested_headers = {
            item.strip().lower()
            for item in (environ.get("HTTP_ACCESS_CONTROL_REQUEST_HEADERS") or "").split(",")
            if item.strip()
        }
        permitted_headers = {"content-type", "accept"}
        if not requested_headers.issubset(permitted_headers):
            return _wsgi_json(start_response, 403, {"error": "Requested CORS header is not allowed."})
        cors_start_response("204 No Content", [("Content-Length", "0"), ("Cache-Control", "no-store")])
        return [b""]

    return _mpoxel_wsgi_application(environ, cors_start_response)


# -------------------- SERVER --------------------

class MpoxelServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 128
