import os
import hashlib
import logging
import redis
import mimetypes
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from flask import Flask, request, jsonify, send_file
from werkzeug.utils import secure_filename
from functools import wraps

# Configuration
API_KEY = "..."
UPLOAD_FOLDER = "/path/to/folder"
LOGS_FOLDER = "logs"
REDIS_DB_PATH = "redis_db"
BASE_URL = "https://example.com"
TZ = ZoneInfo("Europe/Zurich")

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024 * 1024  # 1GB

# Initialize folders
Path(UPLOAD_FOLDER).mkdir(exist_ok=True)
Path(LOGS_FOLDER).mkdir(exist_ok=True)

# Initialize Redis
try:
    r = redis.Redis(
        unix_socket_path=os.path.join(REDIS_DB_PATH, "redis.sock"),
        decode_responses=True,
    )
    r.ping()
except Exception:
    print("Redis not running, starting in-memory fallback mode")
    r = None


def get_logger():
    """Get or create logger with daily rotation and timezone support"""
    now = datetime.now(tz=TZ)
    month_folder = os.path.join(LOGS_FOLDER, now.strftime("%Y-%m"))
    Path(month_folder).mkdir(exist_ok=True)

    log_file = os.path.join(
        month_folder, now.strftime("%d-%m-%Y") + ".log"
    )

    logger = logging.getLogger("uploader")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)

    handler = logging.FileHandler(log_file)
    formatter = logging.Formatter(
        "[%(asctime)s.%(msecs)03d] %(message)s",
        datefmt="%d-%m-%Y %H:%M:%S",
    )

    class TimezoneFormatter(logging.Formatter):
        def formatTime(self, record, datefmt=None):
            dt = datetime.fromtimestamp(record.created, tz=TZ)
            return dt.strftime(datefmt or "%d-%m-%Y %H:%M:%S")

    handler.setFormatter(TimezoneFormatter(
        "[%(asctime)s.%(msecs)03d] %(message)s",
        datefmt="%d-%m-%Y %H:%M:%S",
    ))
    logger.addHandler(handler)

    return logger


def get_client_ip():
    """Get client IP, respecting Cloudflare tunnel headers"""
    if request.headers.get("CF-Connecting-IP"):
        return request.headers.get("CF-Connecting-IP")
    elif request.headers.get("X-Forwarded-For"):
        return request.headers.get("X-Forwarded-For").split(",")[0]
    return request.remote_addr


def require_api_key(f):
    """Decorator to check API key"""
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get("X-API-Key")
        if key != API_KEY:
            logger = get_logger()
            logger.info(f"UNAUTHORIZED_ACCESS - IP: {get_client_ip()}")
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


def file_exists_in_cache(file_hash):
    """Check if file hash exists in Redis cache"""
    if r is None:
        return False
    return r.exists(f"file:{file_hash}") > 0


def get_file_from_cache(file_hash):
    """Get file info from Redis cache"""
    if r is None:
        return None
    return r.hgetall(f"file:{file_hash}")


def cache_file(file_hash, filepath, extension):
    """Cache file info in Redis"""
    if r is None:
        return
    r.hset(
        f"file:{file_hash}",
        mapping={
            "path": filepath,
            "extension": extension,
        },
    )

@app.route("/api/upload", methods=["POST"])
@require_api_key
def upload_file():
    """Upload a file and return its URL"""
    logger = get_logger()
    client_ip = get_client_ip()

    if "file" not in request.files:
        logger.info(f"UPLOAD_FAILED - IP: {client_ip} - REASON: No file")
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if file.filename == "":
        logger.info(f"UPLOAD_FAILED - IP: {client_ip} - REASON: Empty filename")
        return jsonify({"error": "No file selected"}), 400

    # Read and hash file
    file_data = file.read()
    file_hash = hashlib.sha256(file_data).hexdigest()[:12]

    # Get file extension
    original_filename = secure_filename(file.filename)
    extension = Path(original_filename).suffix.lstrip(".") or "bin"

    # Check if already exists
    filepath = os.path.join(
        app.config["UPLOAD_FOLDER"], f"{file_hash}.{extension}"
    )
    if os.path.exists(filepath):
        logger.info(
            f"UPLOAD_SUCCESS - IP: {client_ip} - HASH: {file_hash} "
            f"- STATUS: Already exists"
        )
        url = f"{BASE_URL}/{file_hash}"
        return jsonify({"url": url}), 200

    # Save file
    try:
        with open(filepath, "wb") as f:
            f.write(file_data)
        cache_file(file_hash, filepath, extension)
        logger.info(
            f"UPLOAD_SUCCESS - IP: {client_ip} - HASH: {file_hash} "
            f"- FILENAME: {original_filename}"
        )
        url = f"{BASE_URL}/{file_hash}"
        return jsonify({"url": url}), 200
    except Exception as e:
        logger.info(
            f"UPLOAD_FAILED - IP: {client_ip} - HASH: {file_hash} "
            f"- ERROR: {str(e)}"
        )
        return jsonify({"error": "Upload failed"}), 500

@app.route("/<file_hash>", defaults={"extension": None})
@app.route("/<file_hash>.<extension>")
def serve_file(file_hash, extension):
    """Serve a file by hash"""
    logger = get_logger()
    client_ip = get_client_ip()

    # Try cache first
    cached = get_file_from_cache(file_hash)
    if cached:
        filepath = cached["path"]
        if os.path.exists(filepath):
            logger.info(f"FILE_SERVED - IP: {client_ip} - HASH: {file_hash}")
            return send_file(filepath, as_attachment=False)

    # Search disk
    upload_dir = Path(app.config["UPLOAD_FOLDER"])
    for f in upload_dir.glob(f"{file_hash}.*"):
        cache_file(file_hash, str(f), f.suffix.lstrip("."))
        logger.info(f"FILE_SERVED - IP: {client_ip} - HASH: {file_hash}")
        return send_file(str(f), as_attachment=False)

    logger.info(f"FILE_NOT_FOUND - IP: {client_ip} - HASH: {file_hash}")
    return jsonify({"error": "File not found"}), 404

@app.route("/")
def index():
    """Root endpoint"""
    return jsonify({"message": "OK"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=6942, debug=False)
