from flask import Flask, request, jsonify
import threading, subprocess, uuid, os, json, time
import requests # Required for the keepalive ping
import datetime # Required for timestamping the keepalive log

app = Flask(__name__)
WORKDIR = os.path.abspath('work'); os.makedirs(WORKDIR, exist_ok=True)
jobs = {}

# ==========================================
# KEEPALIVE IMPLEMENTATION
# ==========================================
def run_keepalive():
    """Pings the server's own URL every 10 minutes to prevent Render from sleeping."""
    
    # Give the main server process time to fully start
    time.sleep(30)
    
    # Read the necessary environment variable
    url = os.environ.get("RENDER_EXTERNAL_URL")
    
    if not url:
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] ⚠️ KEEPALIVE ERROR: RENDER_EXTERNAL_URL environment variable is not set. Service may sleep.")
        return

    # Render sleeps after 15 mins, so 10 mins (600 seconds) is a safe interval.
    interval_seconds = 600
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] ✅ KEEPALIVE STARTED. Pinging {url} every 10 minutes.")
    
    while True:
        try:
            # Wait for the interval
            time.sleep(interval_seconds) 
            
            # Use a specific path if available, or just the root '/'
            ping_url = f"{url}/" 
            response = requests.get(ping_url, timeout=10)
            
            print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 🔄 Ping sent. Status: {response.status_code}")
            
        except Exception as e:
            print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] ⚠️ KEEPALIVE FAILED: {e}")

# Start the keepalive logic in a new background thread
threading.Thread(target=run_keepalive, daemon=True).start()
# ==========================================
# END KEEPALIVE IMPLEMENTATION
# ==========================================


def generate_call(jobid, prompt, mode, duration, seed_url=None):
    jobs[jobid]['status'] = 'running'; jobs[jobid]['logs'].append('starting generation')
    cmd = ['python3','generate_video.py','--prompt', prompt, '--duration', str(duration), '--outdir', WORKDIR]
    if seed_url:
        cmd += ['--seed_url', seed_url]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=60*60)
        jobs[jobid]['logs'].append(p.stdout.strip())
        if p.returncode == 0:
            # try parse last JSON line for {"output": "<path>"}
            try:
                out = json.loads(p.stdout.strip().splitlines()[-1])['output']
                jobs[jobid]['status'] = 'done'; jobs[jobid]['outputUrl'] = out; jobs[jobid]['progress'] = 100
                jobs[jobid]['logs'].append('finished: ' + str(out))
            except Exception as e:
                jobs[jobid]['status'] = 'error'
                jobs[jobid]['logs'].append('parse error: ' + repr(e))
        else:
            jobs[jobid]['status'] = 'error'
            jobs[jobid]['logs'].append('generator failed. rc=%s stderr=%s' % (p.returncode, p.stderr[:200]))
    except Exception as e:
        jobs[jobid]['status'] = 'error'
        jobs[jobid]['logs'].append('exception: ' + repr(e))

@app.route('/api/generate', methods=['POST'])
def api_generate():
    data = request.json or request.form.to_dict()
    prompt = data.get('prompt','tiny glowing fox')
    mode = data.get('mode','TEXT')
    duration = int(data.get('duration') or 15)
    seed_url = data.get('seed_url')
    jobid = 'job-' + uuid.uuid4().hex[:8]
    jobs[jobid] = {'jobId':jobid,'status':'queued','progress':0,'logs':['queued'],'outputUrl':None}
    threading.Thread(target=generate_call, args=(jobid,prompt,mode,duration,seed_url), daemon=True).start()
    return jsonify({'jobId': jobid}), 202

@app.route('/api/job/<jobid>', methods=['GET'])
def api_job(jobid):
    return jsonify(jobs.get(jobid, {'status':'notfound'}))

if __name__ == '__main__':
    # debug mode fine for local/Grok/Colab testing
    app.run(host='0.0.0.0', port=8787, debug=True)
