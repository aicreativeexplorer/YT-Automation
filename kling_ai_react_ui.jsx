/*
KlingAI — Advanced React UI (single-file component)
Platform: React (Tailwind CSS + Framer Motion)
Features: 1 main preview + 3 thumbnails, real-time progress + logs, upload manager (local/Drive stub), presets & templates, fancy player + download

How to use:
1) Drop this file into a React app (Vite / Create React App / Next.js). Ensure Tailwind is configured.
2) Install dependencies: `npm i framer-motion lucide-react` (lucide used for icons). Framer Motion powers animations.
3) Wire backend:
   - `POST /api/generate` should accept { prompt, mode, duration, image } and return { jobId }
   - `GET /api/job/:jobId` should return { status: 'queued'|'running'|'done'|'error', progress:0-100, outputUrl, logs:[] }
   - Alternatively the UI will run a simulated job if no API exists.

Drop me the backend contract if you want me to adapt the network hooks.
*/

import React, { useState, useEffect, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { CloudUpload, Play, Download, Settings, Trash2, FilePlus } from 'lucide-react'

// ---------- NETWORK / BACKEND HOOKS (real) ----------
const API_BASE = "https://yt-automation-mt1d.onrender.com"; // <- set your backend public URL here

// Real generate: POST form (prompt, mode, duration, file optional) => { jobId }
async function realGenerate({ prompt, mode, duration, file }) {
  try {
    const fd = new FormData();
    fd.append("prompt", prompt || "");
    fd.append("mode", mode || "TEXT");
    fd.append("duration", String(duration || 4));
    if (file) fd.append("file", file, file.name || "upload.mp4");

    const res = await fetch(`${API_BASE}/api/generate`, {
      method: "POST",
      body: fd,
    });

    if (!res.ok) {
      const txt = await res.text();
      throw new Error(`Generate error: ${res.status} ${txt}`);
    }
    const json = await res.json();
    return json; // expect { jobId: "job-..." }
  } catch (err) {
    console.error("realGenerate error:", err);
    throw err;
  }
}

// Poll job status: calls onUpdate({ status, progress, logs, outputUrl })
// Returns stop() function to cancel polling
function pollJob(jobId, onUpdate, intervalMs = 1500) {
  let stopped = false;
  async function tick() {
    if (stopped) return;
    try {
      const r = await fetch(`${API_BASE}/api/job/${jobId}`);
      if (!r.ok) {
        const txt = await r.text();
        onUpdate({ status: "error", progress: 0, logs: [`HTTP ${r.status}: ${txt}`] });
        return;
      }
      const j = await r.json();
      // j: { jobId, status, progress, logs, outputUrl }
      let outUrl = j.outputUrl;
      if (outUrl && outUrl.startsWith("/")) outUrl = API_BASE + outUrl;
      onUpdate({ status: j.status, progress: j.progress || 0, logs: j.logs || [], outputUrl: outUrl });
      if (j.status === "done" || j.status === "error") {
        stopped = true;
        return;
      }
    } catch (e) {
      console.error("poll error", e);
      onUpdate({ status: "error", progress: 0, logs: [`poll error: ${String(e)}`] });
      stopped = true;
    }
    if (!stopped) setTimeout(tick, intervalMs);
  }
  setTimeout(tick, 200);
  return () => { stopped = true; };
}

// --- Presets storage ---
const defaultPresets = [
  { id: 'p1', name: 'Cute Tiny Animal', prompt: 'tiny playful kitten in a wool sweater, cinematic closeup', duration: 15 },
  { id: 'p2', name: 'Futuristic City', prompt: 'neon cyberpunk alley, rain, cinematic 3d', duration: 20 },
  { id: 'p3', name: 'Calm Nature Loop', prompt: 'tiny bird drinking water, soft light, loop', duration: 10 }
]

export default function KlingAIUI() {
  const [mode, setMode] = useState('TEXT')
  const [prompt, setPrompt] = useState('woolen cat playing')
  const [duration, setDuration] = useState(15)
  const [presets, setPresets] = useState(defaultPresets)
  const [jobs, setJobs] = useState([]) // { jobId, prompt, progress, status, outputUrl, logs }
  const [selectedJob, setSelectedJob] = useState(null)
  const [uploads, setUploads] = useState([]) // uploaded sample list (stub) => stores {id, name, url, size, file}
  const [isGenerating, setIsGenerating] = useState(false)
  const [themeAccent, setThemeAccent] = useState('#06b6d4')
  const logsRef = useRef([])

  // create job using real backend
  const startGenerate = async () => {
    setIsGenerating(true)
    const cfg = { prompt, mode, duration }

    // choose first upload file if present
    let fileObj = null
    if (uploads && uploads.length > 0 && uploads[0].file instanceof File) {
      fileObj = uploads[0].file
    }

    try {
      const json = await realGenerate({ prompt, mode, duration, file: fileObj })
      if (!json || !json.jobId) throw new Error("No jobId returned from backend")
      const jobId = json.jobId
      const newJob = { jobId, prompt, progress: 0, status: 'queued', outputUrl: null, logs: ['Job queued'] }
      setJobs(prev => [newJob, ...prev])
      setSelectedJob(jobId)

      // start polling
      const stop = pollJob(jobId, (update) => {
        setJobs(prev => prev.map(j => j.jobId===jobId ? { ...j, ...update } : j))
        if (update.status === 'done' || update.status === 'error') setIsGenerating(false)
      }, 1500)

      return () => stop()
    } catch (e) {
      setIsGenerating(false)
      console.error('Generate failed', e)
      setJobs(prev => [{ jobId: 'local-error', prompt, progress: 0, status: 'error', logs: [String(e)], outputUrl: null }, ...prev])
    }
  }

  // upload manager: store File object and blob url for preview
  const onFileUpload = (file) => {
    const id = 's' + Math.random().toString(36).slice(2,8)
    const url = URL.createObjectURL(file)
    const item = { id, name: file.name, url, size: file.size, file }
    setUploads(u => [item, ...u])
  }

  const removeUpload = (id) => setUploads(u => u.filter(x => x.id !== id))

  // UI helpers
  const activeJob = jobs.find(j => j.jobId === selectedJob) || jobs[0] || null

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-900 to-[#041018] text-slate-100 p-6">
      <div className="max-w-6xl mx-auto">
        <header className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-4">
            <motion.div whileHover={{ scale: 1.05 }} className="p-3 rounded-2xl bg-gradient-to-br from-[#042b38] to-[#071124] shadow-2xl">
              <img src="/logo192.png" alt="KlingAI" className="w-10 h-10" />
            </motion.div>
            <div>
              <h1 className="text-2xl font-extrabold tracking-tight">KlingAI — TinyShort Lab</h1>
              <p className="text-sm text-slate-300">Advanced UI • Multi-preview • Live logs • Presets • Upload manager</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <button className="px-3 py-2 rounded-lg bg-slate-800/50 hover:bg-slate-800/70 flex items-center gap-2"><Settings size={16} />Settings</button>
            <button onClick={() => { setThemeAccent('#06b6d4') }} className="px-3 py-2 rounded-lg bg-[#06b6d4]/20 hover:bg-[#06b6d4]/30">Teal</button>
            <button onClick={() => { setThemeAccent('#f97316') }} className="px-3 py-2 rounded-lg bg-[#f97316]/20 hover:bg-[#f97316]/30">Orange</button>
          </div>
        </header>

        <main className="grid grid-cols-12 gap-6">
          {/* Left column: controls */}
          <section className="col-span-4 bg-[#071124] p-4 rounded-2xl shadow-md">
            <div className="mb-4">
              <label className="text-xs text-slate-400">Mode</label>
              <div className="mt-2 flex gap-2">
                <button onClick={() => setMode('TEXT')} className={`px-3 py-2 rounded-md ${mode==='TEXT' ? 'bg-slate-700' : 'bg-slate-800/40'}`}>Text</button>
                <button onClick={() => setMode('IMAGE')} className={`px-3 py-2 rounded-md ${mode==='IMAGE' ? 'bg-slate-700' : 'bg-slate-800/40'}`}>Image</button>
              </div>
            </div>

            <div className="mb-3">
              <label className="text-xs text-slate-400">Prompt</label>
              <textarea value={prompt} onChange={e=>setPrompt(e.target.value)} rows={3} className="mt-2 w-full rounded-md bg-slate-900 p-3 text-sm" />
            </div>

            <div className="mb-4 flex items-center gap-2">
              <label className="text-xs text-slate-400">Duration (sec)</label>
              <input type="number" value={duration} onChange={e=>setDuration(Number(e.target.value))} min={1} max={60} className="ml-auto w-24 p-2 rounded-md bg-slate-900 text-sm" />
            </div>

            <div className="flex gap-3">
              <button onClick={startGenerate} disabled={isGenerating} className="flex-1 py-3 rounded-xl bg-gradient-to-r from-[#06b6d4] to-[#0ea5a4] font-bold shadow-lg flex items-center justify-center gap-2"><Play size={18}/>Generate</button>
              <button className="py-3 px-4 rounded-xl bg-slate-700/40 flex items-center gap-2"><CloudUpload size={16}/>Upload</button>
            </div>

            <div className="mt-6">
              <h3 className="text-sm text-slate-300 mb-2">Presets</h3>
              <div className="flex flex-col gap-2">
                {presets.map(p => (
                  <motion.button key={p.id} whileHover={{ scale: 1.02 }} onClick={() => { setPrompt(p.prompt); setDuration(p.duration) }} className="text-left p-3 rounded-lg bg-slate-800/40">
                    <div className="flex justify-between items-center">
                      <div>
                        <div className="font-semibold">{p.name}</div>
                        <div className="text-xs text-slate-400">{p.duration}s</div>
                      </div>
                      <div className="text-xs text-slate-400">Apply</div>
                    </div>
                  </motion.button>
                ))}
              </div>
            </div>

            <div className="mt-6">
              <h3 className="text-sm text-slate-300 mb-2">Upload Manager</h3>
              <div className="flex gap-2 items-center">
                <input id="file-in" type="file" accept="video/*" onChange={e => e.target.files && onFileUpload(e.target.files[0])} className="hidden" />
                <label htmlFor="file-in" className="cursor-pointer px-3 py-2 rounded-lg bg-slate-800/40 flex items-center gap-2"><FilePlus size={14}/>Add Sample</label>
              </div>
              <div className="mt-3 flex flex-col gap-2 max-h-36 overflow-auto">
                {uploads.length===0 && <div className="text-xs text-slate-500">No uploads yet</div>}
                {uploads.map(u => (
                  <div key={u.id} className="flex items-center justify-between p-2 bg-slate-900 rounded">
                    <div className="truncate text-sm">{u.name}</div>
                    <div className="flex items-center gap-2">
                      <a href={u.url} target="_blank" rel="noreferrer" className="text-xs text-slate-300 underline">Preview</a>
                      <button onClick={() => removeUpload(u.id)} className="p-1 rounded bg-slate-800/50"><Trash2 size={12}/></button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </section>

          {/* Right column: preview and job list */}
          <section className="col-span-8">
            <div className="grid grid-cols-12 gap-4">
              <div className="col-span-8 bg-[#071124] rounded-2xl p-4 shadow-md">
                <div className="flex items-center justify-between mb-3">
                  <div>
                    <h2 className="font-bold text-lg">Preview</h2>
                    <div className="text-xs text-slate-400">Main preview — click thumbnails to swap.</div>
                  </div>
                  <div className="flex items-center gap-2">
                    <button onClick={() => window.open(activeJob?.outputUrl || '#')} className="px-3 py-2 rounded bg-slate-800/50"><Download size={16}/>Download</button>
                  </div>
                </div>

                <div className="bg-black rounded-lg overflow-hidden relative" style={{ height: 480 }}>
                  <AnimatePresence>
                    {activeJob && activeJob.outputUrl ? (
                      <motion.video key={activeJob.jobId} src={activeJob.outputUrl} controls autoPlay style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                    ) : (
                      <motion.div key="placeholder" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="w-full h-full flex items-center justify-center text-slate-400">
                        <div className="text-center">
                          <div className="mb-2 text-sm">No generated output yet</div>
                          <div className="text-xs">Press Generate to start a job. A created fallback will be used if no sample provided.</div>
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>

                <div className="mt-3 grid grid-cols-3 gap-2">
                  {jobs.slice(0,3).map(j => (
                    <motion.div key={j.jobId} whileHover={{ scale: 1.02 }} onClick={() => setSelectedJob(j.jobId)} className={`p-2 rounded-lg ${selectedJob===j.jobId ? 'ring-2 ring-slate-600' : 'bg-slate-900/40'}`}>
                      <div className="h-28 bg-black rounded mb-2 flex items-center justify-center text-slate-500">{j.outputUrl ? <video src={j.outputUrl} style={{ width: '100%', height: '100%', objectFit: 'cover' }} /> : 'Preview'}</div>
                      <div className="text-xs">{j.prompt.slice(0,40)}</div>
                      <div className="text-2xs text-slate-400">{j.progress}% — {j.status}</div>
                    </motion.div>
                  ))}
                </div>

              </div>

              <div className="col-span-4 bg-[#071124] rounded-2xl p-4 shadow-md flex flex-col">
                <h3 className="font-semibold mb-2">Jobs & Logs</h3>
                <div className="flex-1 overflow-auto p-2 bg-slate-900/30 rounded">
                  {jobs.length===0 && <div className="text-sm text-slate-500">No jobs yet — generate one.</div>}
                  {jobs.map(j => (
                    <div key={j.jobId} className="p-2 border-b border-slate-800 last:border-b-0">
                      <div className="flex justify-between items-center">
                        <div>
                          <div className="font-medium">{j.jobId}</div>
                          <div className="text-xs text-slate-400">{j.prompt.slice(0,60)}</div>
                        </div>
                        <div className="text-sm">{j.progress}%</div>
                      </div>
                      <div className="mt-2 text-xs text-slate-400 max-h-20 overflow-auto">
                        {(j.logs||[]).slice(-5).map((l, i) => <div key={i}>{l}</div>)}
                      </div>
                      <div className="mt-2 flex gap-2">
                        <button onClick={() => { setSelectedJob(j.jobId) }} className="text-xs px-2 py-1 rounded bg-slate-800/40">View</button>
                        <button onClick={() => setJobs(prev => prev.filter(x => x.jobId !== j.jobId))} className="text-xs px-2 py-1 rounded bg-red-700/60">Delete</button>
                      </div>
                    </div>
                  ))}
                </div>

                <div className="mt-3 text-xs text-slate-500">Live logs appear here while jobs run.</div>
              </div>
            </div>
          </section>
        </main>

        <footer className="mt-8 text-center text-slate-500 text-sm">Made with ❤️ for AI Creative Explorer — adapt backend endpoints to hook gen model.</footer>
      </div>
    </div>
  )
}
