# server.py — improved for safe local/prod behavior (lightweight API only)
from flask import Flask, request, jsonify
from asgiref.wsgi import WsgiToAsgi
import threading, subprocess, uuid, os, json, time, datetime
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict

app = Flask(__name__)
WORKDIR = os.path.abspath('work'); os.makedirs(WORKDIR, exist_ok=True)

# Thread-safe in-memory job store (OK for dev/single-instance only)
jobs_lock = threading.Lock()
jobs: Dict[str, dict] = {}

# Limit concurrent background jobs to avoid OOM/exhaustion (tune as needed)
MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "2"))
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)

# ==========================================
# KEEPALIVE (resilient)
# ==========================================
def run_keepalive():
    """Keepalive: waits for RENDER_EXTERNAL_URL and then pings forever."""
    interval_seconds = 600
    # small initial jitter
    time.sleep(5)
    while True:
        url = os.environ.get("RENDER_EXTERNAL_URL")
        if not url:
            print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] ⚠️ KEEPALIVE: RENDER_EXTERNAL_URL not set - retrying in 30s")
            time.sleep(30)
            continue

        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] ✅ KEEPALIVE STARTED. Pinging {url} every {interval_seconds//60}m")
        while True:
            try:
                time.sleep(interval_seconds)
                ping_url = f"{url.rstrip('/')}/"
                r = requests.get(ping_url, timeout=10)
                print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 🔄 Ping {ping_url} -> {r.status_code}")
            except Exception as e:
                print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] ⚠️ KEEPALIVE FAILED: {e}")
                # keep trying (do not exit)
            # check whether RENDER_EXTERNAL_URL changed/removed mid-run
            if os.environ.get("RENDER_EXTERNAL_URL") != url:
                break

threading.Thread(target=run_keepalive, daemon=True).start()

# ==========================================
# Helper: safe job meta updates
# ==========================================
def job_set(jobid, **updates):
    with jobs_lock:
        meta = jobs.get(jobid, {})
        meta.update(updates)
        jobs[jobid] = meta

# ==========================================
# Generation worker (runs in executor thread)
# ==========================================
def generate_call(jobid, prompt, mode, duration, seed_url=None):
    job_set(jobid, status='running', logs=jobs[jobid].get('logs', []) + ['starting generation'])
    cmd = ['python3', 'generate_video.py', '--prompt', prompt, '--duration', str(duration), '--outdir', WORKDIR]
    if seed_url:
        cmd += ['--seed_url', seed_url]

    try:
        # LONG TIMEOUT but bounded (tune to your job)
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=60*60*2)
        outlogs = (p.stdout or '') + '\n' + (p.stderr or '')
        logs = jobs[jobid].get('logs', []) + [outlogs.strip()]
        if p.returncode == 0:
            # attempt to parse last json line for {"output": "<path>"}
            try:
                last_line = p.stdout.strip().splitlines()[-1]
                out = json.loads(last_line).get('output')
                job_set(jobid, status='done', progress=100, outputUrl=out, logs=logs + [f'finished: {out}'])
            except Exception as e:
                job_set(jobid, status='error', logs=logs + [f'parse error: {repr(e)}'])
        else:
            job_set(jobid, status='error', logs=logs + [f'generator failed rc={p.returncode}'])
    except Exception as e:
        job_set(jobid, status='error', logs=jobs[jobid].get('logs', []) + [f'exception: {repr(e)}'])

# ==========================================
# API endpoints
# ==========================================
@app.route('/api/generate', methods=['POST'])
def api_generate():
    data = request.json or request.form.to_dict()
    prompt = data.get('prompt', 'tiny glowing fox')
    mode = data.get('mode', 'TEXT')
    duration = int(data.get('duration') or 15)
    seed_url = data.get('seed_url')

    jobid = 'job-' + uuid.uuid4().hex[:8]
    initial_meta = {'jobId': jobid, 'status': 'queued', 'progress': 0, 'logs': ['queued'], 'outputUrl': None}
    with jobs_lock:
        jobs[jobid] = initial_meta

    # schedule background work safely with executor
    try:
        future = executor.submit(generate_call, jobid, prompt, mode, duration, seed_url)
        # optional: attach future to job for debugging
        job_set(jobid, future_id=id(future))
        return jsonify({'jobId': jobid}), 202
    except Exception as e:
        job_set(jobid, status='error', logs=['enqueue failed: ' + repr(e)])
        return jsonify({'error': 'enqueue_failed'}), 500

@app.route('/api/job/<jobid>', methods=['GET'])
def api_job(jobid):
    with jobs_lock:
        meta = jobs.get(jobid)
    if not meta:
        return jsonify({'status': 'notfound'}), 404
    return jsonify(meta)

# ==========================================
# ASGI wrapper export
# ==========================================
asgi_app = WsgiToAsgi(app)

if __name__ == '__main__':
    # Dev: keep reload True for local dev only.
    import uvicorn
    uvicorn.run("server:asgi_app", host="0.0.0.0", port=8787, reload=True)
