# server.py
"""
YT-Automation Backend (Advanced Version)
---------------------------------------
- Flask + CORS
- In-memory job store with thread-safety
- Spawns background worker thread per job:
    - DUMMY/LOCAL: run `generate_video.py`
    - KAGGLE_LIVE: call external Colab/ngrok SVD API
- API:
    GET  /                  -> health/info
    POST /api/generate      -> enqueue + start job, returns { jobId }
    GET  /api/job/<jobId>   -> job status, progress, logs, outputUrl
    GET  /api/output/<jobId>-> streams generated mp4 (local-only)

Contract with generate_video.py (for DUMMY/LOCAL):
- Called as: python3 generate_video.py --prompt PROMPT --duration N --outdir WORKDIR [--seed_url URL]
- Must print a final JSON line: {"output": "<path/to/video.mp4>"}
"""
import requests  # NEW
import os
import json
import uuid
import time
import threading
import subprocess
from pathlib import Path

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import requests  # NEW: for KAGGLE_LIVE / Colab calls

# -------------------------------------------------------------------
# App & config
# -------------------------------------------------------------------

app = Flask(__name__)
CORS(app)  # allow all origins; tighten later if needed

# Where generated videos will be stored (for local/dummy engine)
WORKDIR = Path(os.path.abspath("work"))
WORKDIR.mkdir(parents=True, exist_ok=True)

# Simple in-memory job store
jobs = {}          # job_id -> metadata dict
jobs_lock = threading.Lock()

# External live GPU API base (Colab/ngrok)
# Example: https://something.ngrok-free.dev
KAGGLE_LIVE_API_BASE = os.environ.get("KAGGLE_LIVE_API_BASE", "").rstrip("/") or None


# -------------------------------------------------------------------
# Helpers: job lifecycle
# -------------------------------------------------------------------

def job_init(job_id, prompt, mode, duration, seed_url=None, engine="LOCAL"):
    """Create initial metadata for a new job."""
    meta = {
        "jobId": job_id,
        "prompt": prompt,
        "mode": mode,
        "duration": duration,
        "seedUrl": seed_url,
        "engine": engine,          # NEW
        "status": "queued",        # queued | running | done | error
        "progress": 0,
        "logs": ["queued"],
        "outputUrl": None,
        "outputPath": None,
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
# Worker: call generate_video.py (DUMMY/LOCAL engine)
# -------------------------------------------------------------------

def generate_call_local(job_id, prompt, mode, duration, seed_url):
    """
    Background worker function for local/DUMMY engine:
    - Runs generate_video.py
    - Parses its output
    - Updates job state accordingly
    """
    job_log(job_id, "starting local generation")
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

def generate_call_kaggle_live(job_id, prompt, mode, duration, seed_url):
    """
    Worker that forwards the job to Colab SVD API (KAGGLE_LIVE_API_BASE).
    - Calls:  POST {BASE}/api/generate  with JSON { id, prompt, duration, mode }
    - Expects Colab to create /api/output/<jobId> mp4.
    """
    if not KAGGLE_LIVE_API_BASE:
        job_update(job_id, status="error", progress=0)
        job_log(job_id, "KAGGLE_LIVE_API_BASE not set on server.")
        return

    job_log(job_id, f"forwarding to Colab SVD at {KAGGLE_LIVE_API_BASE}")
    job_update(job_id, status="running", progress=10)

    try:
        url = f"{KAGGLE_LIVE_API_BASE}/api/generate"
        payload = {
            "id": job_id,
            "prompt": prompt,
            "duration": int(duration),
            "mode": (mode or "TEXT").upper(),
        }
        job_log(job_id, f"POST {url} with {payload}")

        resp = requests.post(url, json=payload, timeout=60 * 60)
        job_log(job_id, f"Colab response: {resp.status_code}")

        try:
            data = resp.json()
        except Exception:
            data = {"raw": resp.text[:500]}

        if resp.status_code != 200 or not data.get("ok"):
            job_update(job_id, status="error", progress=0)
            job_log(job_id, f"Colab error: {data}")
            return

        # Colab saves file as /content/generated_videos/{job_id}_svd.mp4
        out_url = f"{KAGGLE_LIVE_API_BASE}/api/output/{job_id}"

        job_update(
            job_id,
            status="done",
            progress=100,
            outputPath=None,          # file lives on Colab, not here
            outputUrl=out_url,        # FULL URL, not relative
        )
        job_log(job_id, f"finished via Colab: {out_url}")

    except Exception as e:
        job_update(job_id, status="error", progress=0)
        job_log(job_id, f"KAGGLE_LIVE exception: {repr(e)}")


# -------------------------------------------------------------------
# Worker: call external Colab/ngrok SVD API (KAGGLE_LIVE engine)
# -------------------------------------------------------------------

def generate_call_kaggle_live(job_id, prompt, mode, duration, seed_url):
    """
    Background worker for KAGGLE_LIVE engine:
    - Calls external Colab/ngrok API: POST /api/generate
    - Expects JSON: { ok, jobId, status, output_path? }
    - Sets outputUrl to Colab /api/output/<jobId>
    """
    job_log(job_id, "starting KAGGLE_LIVE (Colab) generation")
    job_update(job_id, status="running", progress=5)

    if not KAGGLE_LIVE_API_BASE:
        job_update(job_id, status="error", progress=0)
        job_log(job_id, "KAGGLE_LIVE_API_BASE not configured")
        return

    payload = {
        "id": job_id,
        "prompt": prompt,
        "duration": duration,
        "mode": mode,
    }

    try:
        resp = requests.post(
            f"{KAGGLE_LIVE_API_BASE}/api/generate",
            json=payload,
            timeout=60 * 60,
        )
        text = resp.text
        try:
            data = resp.json()
        except Exception as e:
            job_update(job_id, status="error", progress=0)
            job_log(job_id, f"invalid JSON from KAGGLE_LIVE: {repr(e)}; body={text[:500]}")
            return

        job_log(job_id, f"KAGGLE_LIVE response: {data}")

        if not data.get("ok"):
            job_update(job_id, status="error", progress=0)
            job_log(job_id, f"KAGGLE_LIVE reported error: {data.get('error')}")
            return

        # Success: video is hosted on Colab side; we just point the UI there
        out_url = f"{KAGGLE_LIVE_API_BASE}/api/output/{job_id}"
        job_update(
            job_id,
            status=data.get("status", "done"),
            progress=100,
            outputPath=None,     # remote
            outputUrl=out_url,
        )
        job_log(job_id, f"KAGGLE_LIVE finished. Output URL: {out_url}")

    except requests.Timeout:
        job_update(job_id, status="error", progress=0)
        job_log(job_id, "KAGGLE_LIVE call timed out")
    except Exception as e:
        job_update(job_id, status="error", progress=0)
        job_log(job_id, f"KAGGLE_LIVE exception: {repr(e)}")


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
    data = request.json or request.form.to_dict()

    prompt = data.get("prompt", "tiny glowing fox")
    mode = data.get("mode", "TEXT")
    seed_url = data.get("seed_url")

    try:
        duration = int(data.get("duration") or 15)
    except Exception:
        duration = 15

    duration = max(1, min(duration, 60))

    # NEW: engine flag from UI
    engine = data.get("engine", "LOCAL").upper()  # LOCAL | KAGGLE_LIVE | ...

    job_id = "job-" + uuid.uuid4().hex[:8]
    job_init(job_id, prompt, mode, duration, seed_url=seed_url, engine=engine)

    # Pick worker based on engine
    if engine == "KAGGLE_LIVE":
        t = threading.Thread(
            target=generate_call_kaggle_live,
            args=(job_id, prompt, mode, duration, seed_url),
            daemon=True,
        )
    else:
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
      "outputUrl": "/api/output/job-xxxx" | "https://colab.../api/output/..." | null,
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
    Stream the generated mp4 for LOCAL jobs.
    For KAGGLE_LIVE jobs, the UI should use the remote URL directly.
    """
    with jobs_lock:
        meta = jobs.get(job_id)

    if not meta:
        return jsonify({"error": "job_not_found"}), 404

    output_path = meta.get("outputPath")
    if not output_path:
        return jsonify({"error": "output_not_ready_or_remote"}), 404

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



