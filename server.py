import os
import time
import uuid
import threading
from flask import Flask, request, send_file, jsonify
from yt_dlp import YoutubeDL
from flask_cors import CORS   # ✅ added

DOWNLOAD_DIR = "downloads"
COOKIE_FILE = "cookies.txt"
EXPIRY_SECONDS = 2 * 60 * 60  # 2 hours

app = Flask(__name__)

# ✅ enable CORS
CORS(
    app,
    origins=["https://nx-downloader.free.nf"],   # ⚠️ apna frontend origin
    methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

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

# (rest of your code unchanged…)
# ---------- SMART FORMAT PICKER ----------
def pick_best_available_format(info, requested):
    formats = info.get("formats", []) or []
    for f in formats:
        if f.get("format_id") == requested:
            return requested
    if isinstance(requested, str) and requested.endswith("p"):
        try:
            req_h = int(requested.replace("p", ""))
            candidates = [
                f for f in formats
                if f.get("height") and f["height"] <= req_h
            ]
            if candidates:
                return sorted(candidates, key=lambda x: x["height"])[-1]["format_id"]
        except:
            pass
    return "best"

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
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "cookies.txt file required"}), 400
    f.save(COOKIE_FILE)
    return jsonify({"status": "cookies stored"})

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

    def run_dl(q, use_cookies):
        opts = base_ydl_opts(out_path, q, use_cookies)
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=not dry)
            filename = None if dry else ydl.prepare_filename(info)
        return info, filename

    try:
        info, filename = run_dl(quality, use_cookies=False)
        if not dry and quality != "best":
            quality_adj = pick_best_available_format(info, quality)
            if quality_adj != quality:
                info, filename = run_dl(
                    quality_adj,
                    use_cookies=os.path.exists(COOKIE_FILE)
                )
                quality = quality_adj
    except Exception as e:
        msg = str(e).lower()
        cookie_msgs = ["cookies", "sign in", "not a bot", "verify", "consent"]
        if any(k in msg for k in cookie_msgs):
            if os.path.exists(COOKIE_FILE):
                info, filename = run_dl(quality, use_cookies=True)
            else:
                return jsonify({
                    "error": "This video requires sign-in verification",
                    "needs_cookies": True
                }), 403
        else:
            return jsonify({"error": str(e)}), 500

    if dry:
        return jsonify({"info": info})

    return jsonify({
        "file_id": file_id,
        "filename": os.path.basename(filename),
        "download_url": f"/file/{os.path.basename(filename)}",
        "quality_used": quality,
        "expires_in": "2 hours",
        "cookies_used": os.path.exists(COOKIE_FILE)
    })

@app.route("/file/<name>")
def serve(name):
    p = os.path.join(DOWNLOAD_DIR, name)
    if not os.path.exists(p):
        return jsonify({"error": "file expired or not found"}), 404
    return send_file(p, as_attachment=True)

@app.route("/")
def home():
    return jsonify({
        "status": "yt-dlp backend running",
        "cookies_present": os.path.exists(COOKIE_FILE)
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
