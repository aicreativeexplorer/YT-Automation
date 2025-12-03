# server.py
"""
YT-Automation Backend (Advanced Version)
---------------------------------------
- Flask + CORS
- In-memory job store with thread-safety
- Spawns background worker thread per job to run `generate_video.py`
- API:
    GET  /                  -> health/info
    POST /api/generate      -> enqueue + start job, returns { jobId }
    GET  /api/job/<jobId>   -> job status, progress, logs, outputUrl
    GET  /api/output/<jobId>-> streams generated mp4

Contract with generate_video.py:
- Called as: python3 generate_video.py --prompt PROMPT --duration N --outdir WORKDIR [--seed_url URL]
- Must print a final JSON line: {"output": "<path/to/video.mp4>"}
"""

import os
import json
import uuid
import time
import threading
import subprocess
from pathlib import Path

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS

# -------------------------------------------------------------------
# App & config
# -------------------------------------------------------------------

app = Flask(__name__)
CORS(app)  # allow all origins; tighten later if needed

# Where generated videos will be stored
WORKDIR = Path(os.path.abspath("work"))
WORKDIR.mkdir(parents=True, exist_ok=True)

# Simple in-memory job store
jobs = {}          # job_id -> metadata dict
jobs_lock = threading.Lock()


# -------------------------------------------------------------------
# Helpers: job lifecycle
# -------------------------------------------------------------------

def job_init(job_id, prompt, mode, duration, seed_url=None):
    """Create initial metadata for a new job."""
    meta = {
        "jobId": job_id,
        "prompt": prompt,
        "mode": mode,
        "duration": duration,
        "seedUrl": seed_url,
        "status": "queued",          # queued | running | done | error
        "progress": 0,
        "logs": ["queued"],
        "outputUrl": None,           # e.g. /api/output/<jobId>
        "outputPath": None,          # absolute path on disk
        "createdAt": time.time(),
    }
    with jobs_lock:
        jobs[job_id] = meta
    return meta


def job_update(job_id, **fields):
    """Thread-safe partial update of a job."""
    with jobs_lock:
        meta = jobs.get(job_id)
        if not meta:
            return
        meta.update(fields)


def job_log(job_id, message):
    """Append a timestamped log line to a job."""
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {message}"
    with jobs_lock:
        meta = jobs.get(job_id)
        if not meta:
            return
        meta.setdefault("logs", []).append(line)


# -------------------------------------------------------------------
# Worker: call generate_video.py
# -------------------------------------------------------------------

def generate_call(job_id, prompt, mode, duration, seed_url):
    """
    Background worker function:
    - Runs generate_video.py
    - Parses its output
    - Updates job state accordingly
    """
    job_log(job_id, "starting generation")
    job_update(job_id, status="running", progress=5)

    cmd = [
        "python3",
        "generate_video.py",
        "--prompt", prompt,
        "--duration", str(duration),
        "--outdir", str(WORKDIR),
    ]
    if seed_url:
        cmd += ["--seed_url", seed_url]

    try:
        # 60 min timeout; adjust if needed
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60 * 60,
        )
        stdout = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()

        if stdout:
            job_log(job_id, "generator stdout:")
            for line in stdout.splitlines():
                job_log(job_id, line)

        if proc.returncode != 0:
            job_update(job_id, status="error", progress=0)
            job_log(
                job_id,
                f"generator failed: rc={proc.returncode}, stderr={stderr[:500]}",
            )
            return

        # Expect final line of stdout to be JSON: {"output": "..."}
        out_path = None
        try:
            last_line = stdout.splitlines()[-1]
            maybe_json = json.loads(last_line)
            out_path = maybe_json.get("output")
        except Exception as e:
            job_log(job_id, f"parse error on last line: {repr(e)}")

        if not out_path:
            job_update(job_id, status="error", progress=0)
            job_log(job_id, "no output path returned by generator")
            return

        out_path = Path(out_path)
        if not out_path.is_absolute():
            out_path = WORKDIR / out_path

        if not out_path.exists():
            job_update(job_id, status="error", progress=0)
            job_log(job_id, f"output file missing: {out_path}")
            return

        # Success
        job_update(
            job_id,
            status="done",
            progress=100,
            outputPath=str(out_path),
            outputUrl=f"/api/output/{job_id}",
        )
        job_log(job_id, f"finished: {out_path.name}")

    except subprocess.TimeoutExpired:
        job_update(job_id, status="error", progress=0)
        job_log(job_id, "generation timed out")
    except Exception as e:
        job_update(job_id, status="error", progress=0)
        job_log(job_id, f"exception: {repr(e)}")


# -------------------------------------------------------------------
# Routes
# -------------------------------------------------------------------

@app.route("/", methods=["GET"])
def root():
    """Simple health/info endpoint."""
    return jsonify({
        "ok": True,
        "service": "yt-automation-backend",
        "endpoints": [
            "/api/generate",
            "/api/job/<jobId>",
            "/api/output/<jobId>",
        ],
    })


@app.route("/api/generate", methods=["POST"])
def api_generate():
    """
    Enqueue + start a generation job in background.

    Body: JSON or form-data with:
      - prompt   (str)
      - mode     (str, e.g. TEXT / IMAGE)
      - duration (int seconds)
      - seed_url (optional str)

    Returns: { jobId }  (HTTP 202)
    """
    data = request.json or request.form.to_dict()

    prompt = data.get("prompt", "tiny glowing fox")
    mode = data.get("mode", "TEXT")
    seed_url = data.get("seed_url")

    try:
        duration = int(data.get("duration") or 15)
    except Exception:
        duration = 15

    # Clamp duration for safety
    duration = max(1, min(duration, 60))

    job_id = "job-" + uuid.uuid4().hex[:8]
    job_init(job_id, prompt, mode, duration, seed_url=seed_url)

    # Kick off worker thread
    t = threading.Thread(
        target=generate_call,
        args=(job_id, prompt, mode, duration, seed_url),
        daemon=True,
    )
    t.start()

    return jsonify({"jobId": job_id}), 202


@app.route("/api/job/<job_id>", methods=["GET"])
def api_job(job_id):
    """
    Poll job status.

    Returns (example):
    {
      "jobId": "...",
      "status": "queued|running|done|error",
      "progress": 0-100,
      "logs": [...],
      "outputUrl": "/api/output/job-xxxx" | null,
      ...
    }
    """
    with jobs_lock:
        meta = jobs.get(job_id)

    if not meta:
        return jsonify({"jobId": job_id, "status": "notfound"}), 404

    # Don't leak internal absolute paths to the UI
    resp = dict(meta)
    resp.pop("outputPath", None)
    return jsonify(resp)


@app.route("/api/output/<job_id>", methods=["GET"])
def api_output(job_id):
    """
    Stream the generated mp4 for this job.
    Frontend should use job.outputUrl, e.g. `${API_BASE}${outputUrl}`.
    """
    with jobs_lock:
        meta = jobs.get(job_id)

    if not meta:
        return jsonify({"error": "job_not_found"}), 404

    output_path = meta.get("outputPath")
    if not output_path:
        return jsonify({"error": "output_not_ready"}), 404

    p = Path(output_path)
    if not p.exists():
        return jsonify({"error": "file_missing"}), 404

    return send_file(str(p), mimetype="video/mp4", as_attachment=False)


# -------------------------------------------------------------------
# Main entry
# -------------------------------------------------------------------

if __name__ == "__main__":
    # Render sets PORT env; default to 8787 for local dev
    port = int(os.environ.get("PORT", "8787"))
    app.run(host="0.0.0.0", port=port, debug=False)
