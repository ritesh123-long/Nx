import os
import time
import uuid
import threading
from flask import Flask, request, send_file, jsonify
from yt_dlp import YoutubeDL

DOWNLOAD_DIR = "downloads"
COOKIE_FILE = "cookies.txt"
EXPIRY_SECONDS = 2 * 60 * 60  # 2 hours

app = Flask(__name__)
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


# ---------- AUTO DELETE OLD FILES ----------
def cleanup_loop():
    while True:
        now = time.time()
        for f in os.listdir(DOWNLOAD_DIR):
            p = os.path.join(DOWNLOAD_DIR, f)
            if os.path.isfile(p) and now - os.path.getmtime(p) > EXPIRY_SECONDS:
                try:
                    os.remove(p)
                except:
                    pass
        time.sleep(300)

threading.Thread(target=cleanup_loop, daemon=True).start()


# ---------- BASE YTDLP OPTIONS ----------
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


# ---------- UPLOAD COOKIES ----------
@app.route("/upload-cookies", methods=["POST"])
def upload_cookies():
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "cookies.txt file required"}), 400
    file.save(COOKIE_FILE)
    return jsonify({"status": "cookies stored", "using": COOKIE_FILE})


# ---------- DOWNLOAD + META ----------
@app.route("/download", methods=["POST"])
def download():
    data = request.json or {}
    url = data.get("url")
    quality = data.get("quality", "best")
    dry = data.get("dry", False)

    if not url:
        return jsonify({"error": "url required"}), 400

    file_id = str(uuid.uuid4())
    out_path = os.path.join(DOWNLOAD_DIR, f"{file_id}.%(ext)s")

    def run_dl(use_cookies):
        opts = base_ydl_opts(out_path, quality, use_cookies)
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=not dry)
            filename = None if dry else ydl.prepare_filename(info)
        return info, filename

    try:
        # Try without cookies first
        info, filename = run_dl(use_cookies=False)

    except Exception as e:
        msg = str(e).lower()

        # Detect cookie-required situations
        cookie_needed_keywords = [
            "cookies",
            "sign in",
            "not a bot",
            "confirm you’re not a bot",
            "verify",
        ]

        if any(k in msg for k in cookie_needed_keywords):
            # Retry with cookies if available
            if os.path.exists(COOKIE_FILE):
                try:
                    info, filename = run_dl(use_cookies=True)
                except Exception as e2:
                    return jsonify({
                        "error": "Cookies expired or invalid",
                        "needs_cookies": True,
                        "details": str(e2),
                    }), 403
            else:
                return jsonify({
                    "error": "This video requires sign-in verification",
                    "needs_cookies": True,
                    "hint": "Upload cookies.txt using /upload-cookies",
                }), 403
        else:
            return jsonify({"error": str(e)}), 500

    # DRY MODE — metadata only (used by UI preview)
    if dry:
        return jsonify({"info": info})

    return jsonify({
        "file_id": file_id,
        "filename": os.path.basename(filename),
        "download_url": f"/file/{os.path.basename(filename)}",
        "expires_in": "2 hours",
        "cookies_used": os.path.exists(COOKIE_FILE)
    })


# ---------- SERVE FILE ----------
@app.route("/file/<name>")
def serve(name):
    path = os.path.join(DOWNLOAD_DIR, name)
    if not os.path.exists(path):
        return jsonify({"error": "file expired or not found"}), 404
    return send_file(path, as_attachment=True)


# ---------- HEALTH ----------
@app.route("/")
def home():
    return jsonify({
        "status": "yt-dlp backend running",
        "cookies_present": os.path.exists(COOKIE_FILE)
    })


# ---------- RENDER PORT SUPPORT ----------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
