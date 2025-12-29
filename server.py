import os
import time
import uuid
import threading
from flask import Flask, request, send_file, jsonify
from yt_dlp import YoutubeDL

DOWNLOAD_DIR = "downloads"
EXPIRY_SECONDS = 2 * 60 * 60  # 2 hours

app = Flask(__name__)

os.makedirs(DOWNLOAD_DIR, exist_ok=True)


def cleanup_loop():
    while True:
        now = time.time()
        for f in os.listdir(DOWNLOAD_DIR):
            path = os.path.join(DOWNLOAD_DIR, f)
            if os.path.isfile(path):
                if now - os.path.getmtime(path) > EXPIRY_SECONDS:
                    try:
                        os.remove(path)
                    except:
                        pass
        time.sleep(300)  # run every 5 min


threading.Thread(target=cleanup_loop, daemon=True).start()


@app.route("/download", methods=["POST"])
def download():
    data = request.json
    url = data.get("url")
    quality = data.get("quality", "best")   # e.g. best / 720p / 128k / audio

    if not url:
        return jsonify({"error": "url required"}), 400

    file_id = str(uuid.uuid4())
    out_path = os.path.join(DOWNLOAD_DIR, f"{file_id}.%(ext)s")

    ydl_opts = {
        "outtmpl": out_path,
        "format": quality,
        "quiet": True,
    }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            real_file = ydl.prepare_filename(info)

        return jsonify({
            "file_id": file_id,
            "filename": os.path.basename(real_file),
            "download_url": f"/file/{os.path.basename(real_file)}",
            "expires_in": "2 hours"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/file/<name>")
def serve(name):
    path = os.path.join(DOWNLOAD_DIR, name)
    if not os.path.exists(path):
        return jsonify({"error": "file expired or not found"}), 404
    return send_file(path, as_attachment=True)


@app.route("/")
def home():
    return {"status": "yt-dlp backend running"}
    

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
