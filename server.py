import os
import time
import uuid
import threading
from flask import Flask, request, send_file, jsonify
from yt_dlp import YoutubeDL

DOWNLOAD_DIR = "downloads"
COOKIE_FILE = "cookies.txt"        # auto-used when available
EXPIRY_SECONDS = 2 * 60 * 60

app = Flask(__name__)
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


def cleanup_loop():
    while True:
        now = time.time()
        for f in os.listdir(DOWNLOAD_DIR):
            p = os.path.join(DOWNLOAD_DIR, f)
            if os.path.isfile(p) and now - os.path.getmtime(p) > EXPIRY_SECONDS:
                try: os.remove(p)
                except: pass
        time.sleep(300)

threading.Thread(target=cleanup_loop, daemon=True).start()


def base_ydl_opts(out_path, quality, use_cookies=False):
    opts = {
        "outtmpl": out_path,
        "format": quality,
        "quiet": True,
        "forceipv4": True,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },
    }
    if use_cookies and os.path.exists(COOKIE_FILE):
        opts["cookiefile"] = COOKIE_FILE
    return opts


@app.route("/upload-cookies", methods=["POST"])
def upload_cookies():
    file = request.files.get("file")
    if not file:
        return {"error": "cookies.txt file required"}, 400
    file.save(COOKIE_FILE)
    return {"status": "cookies stored", "using": COOKIE_FILE}


@app.route("/download", methods=["POST"])
def download():
    data = request.json or {}
    url = data.get("url")
    quality = data.get("quality", "best")
    dry = data.get("dry", False)

    if not url:
        return {"error": "url required"}, 400

    file_id = str(uuid.uuid4())
    out_path = os.path.join(DOWNLOAD_DIR, f"{file_id}.%(ext)s")

    def run_dl(use_cookies):
        opts = base_ydl_opts(out_path, quality, use_cookies)
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=not dry)
            filename = None if dry else ydl.prepare_filename(info)
        return info, filename

    try:
        # Try **without cookies first**
        info, filename = run_dl(use_cookies=False)

    except Exception as e:
        msg = str(e).lower()

        # Auto-detect cookie-required cases
        if "cookies" in msg or "not a bot" in msg or "sign in" in msg:
            # Retry **with cookies if available**
            if os.path.exists(COOKIE_FILE):
                try:
                    info, filename = run_dl(use_cookies=True)
                except Exception as e2:
                    return {
                        "error": "Cookies expired or invalid",
                        "needs_cookies": True,
                        "details": str(e2),
                    }, 403
            else:
                return {
                    "error": "This video requires sign-in verification",
                    "needs_cookies": True,
                    "hint": "Upload cookies.txt via /upload-cookies",
                }, 403
        else:
            return {"error": str(e)}, 500

    if dry:
        return {"info": info}

    return {
        "file_id": file_id,
        "filename": os.path.basename(filename),
        "download_url": f"/file/{os.path.basename(filename)}",
        "expires_in": "2 hours",
        "cookies_used": os.path.exists(COOKIE_FILE)
    }


@app.route("/file/<name>")
def serve(name):
    path = os.path.join(DOWNLOAD_DIR, name)
    if not os.path.exists(path):
        return {"error": "file expired or not found"}, 404
    return send_file(path, as_attachment=True)


@app.route("/")
def home():
    return {"status": "yt-dlp backend running", "cookies": os.path.exists(COOKIE_FILE)}
