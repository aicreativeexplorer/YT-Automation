/*
KlingAI — Advanced React UI (single-file component)
Backend contract:
  POST  ${API_BASE}/api/generate   -> { jobId }
  GET   ${API_BASE}/api/job/:jobId -> { jobId,status,progress,logs,outputUrl }
*/

import React, { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { CloudUpload, Play, Download, Settings, Trash2, FilePlus } from "lucide-react";

// ---------- CONFIG ----------
const API_BASE = "https://yt-automation-mt1d.onrender.com"; // <- your Render backend

// ---------- NETWORK / BACKEND HOOKS ----------
async function realGenerate({ prompt, mode, duration, file }) {
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
  return res.json(); // { jobId }
}

// Poll job status: calls onUpdate({ status, progress, logs, outputUrl })
function pollJob(jobId, onUpdate, onError, intervalMs = 1500) {
  let stopped = false;

  async function tick() {
    if (stopped) return;
    try {
      const r = await fetch(`${API_BASE}/api/job/${jobId}`);
      if (!r.ok) {
        const txt = await r.text();
        const msg = `HTTP ${r.status}: ${txt}`;
        onUpdate({ status: "error", progress: 0, logs: [msg], outputUrl: null });
        onError(msg);
        stopped = true;
        return;
      }
      const j = await r.json();
      let outUrl = j.outputUrl;
      if (outUrl && outUrl.startsWith("/")) outUrl = API_BASE + outUrl;

      onUpdate({
        status: j.status,
        progress: j.progress ?? 0,
        logs: j.logs || [],
        outputUrl: outUrl || null,
      });

      if (j.status === "done" || j.status === "error") {
        stopped = true;
        return;
      }
    } catch (e) {
      const msg = `poll error: ${String(e)}`;
      console.error(msg);
      onUpdate({ status: "error", progress: 0, logs: [msg], outputUrl: null });
      onError(msg);
      stopped = true;
    }
    if (!stopped) setTimeout(tick, intervalMs);
  }

  setTimeout(tick, 200);
  return () => {
    stopped = true;
  };
}

// --- Presets storage ---
const defaultPresets = [
  {
    id: "p1",
    name: "Cute Tiny Animal",
    prompt: "tiny playful kitten in a wool sweater, cinematic closeup",
    duration: 15,
  },
  {
    id: "p2",
    name: "Futuristic City",
    prompt: "neon cyberpunk alley, rain, cinematic 3d",
    duration: 20,
  },
  {
    id: "p3",
    name: "Calm Nature Loop",
    prompt: "tiny bird drinking water, soft light, loop",
    duration: 10,
  },
];

export default function KlingAIUI() {
  const [mode, setMode] = useState("TEXT");
  const [prompt, setPrompt] = useState("woolen cat playing");
  const [duration, setDuration] = useState(15);
  const [presets] = useState(defaultPresets);
  const [jobs, setJobs] = useState([]); // { jobId, prompt, progress, status, outputUrl, logs }
  const [selectedJob, setSelectedJob] = useState(null);
  const [uploads, setUploads] = useState([]); // {id, name, url, size, file}
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState(null);

  const activeJob = jobs.find((j) => j.jobId === selectedJob) || jobs[0] || null;

  const startGenerate = async () => {
    if (isGenerating) return;
    setError(null);
    setIsGenerating(true);

    let fileObj = null;
    if (uploads && uploads.length > 0 && uploads[0].file instanceof File) {
      fileObj = uploads[0].file;
    }

    try {
      const json = await realGenerate({ prompt, mode, duration, file: fileObj });
      if (!json || !json.jobId) throw new Error("No jobId returned from backend");

      const jobId = json.jobId;
      const newJob = {
        jobId,
        prompt,
        progress: 0,
        status: "queued",
        outputUrl: null,
        logs: ["Job queued"],
      };

      setJobs((prev) => [newJob, ...prev]);
      setSelectedJob(jobId);

      pollJob(
        jobId,
        (update) => {
          setJobs((prev) =>
            prev.map((j) => (j.jobId === jobId ? { ...j, ...update } : j)),
          );
          if (update.status === "done" || update.status === "error") {
            setIsGenerating(false);
          }
        },
        (msg) => setError(msg),
      );
    } catch (e) {
      console.error("Generate failed", e);
      setIsGenerating(false);
      const msg = String(e);
      setError(msg);
      setJobs((prev) => [
        {
          jobId: "local-error-" + Date.now(),
          prompt,
          progress: 0,
          status: "error",
          logs: [msg],
          outputUrl: null,
        },
        ...prev,
      ]);
    }
  };

  const onFileUpload = (file) => {
    if (!file) return;
    const id = "s" + Math.random().toString(36).slice(2, 8);
    const url = URL.createObjectURL(file);
    const item = { id, name: file.name, url, size: file.size, file };
    setUploads((u) => [item, ...u]);
  };

  const removeUpload = (id) => setUploads((u) => u.filter((x) => x.id !== id));

  const handleDownload = () => {
    if (!activeJob || !activeJob.outputUrl) return;
    try {
      window.open(activeJob.outputUrl, "_blank", "noopener,noreferrer");
    } catch (e) {
      console.error("download open error", e);
      setError("Could not open download link.");
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-900 to-[#041018] text-slate-100 p-6">
      <div className="max-w-6xl mx-auto">
        {/* Top bar */}
        <header className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-4">
            <motion.div
              whileHover={{ scale: 1.05 }}
              className="p-3 rounded-2xl bg-gradient-to-br from-[#042b38] to-[#071124] shadow-2xl"
            >
              <img src="/logo192.png" alt="KlingAI" className="w-10 h-10" />
            </motion.div>
            <div>
              <h1 className="text-2xl font-extrabold tracking-tight">
                KlingAI — TinyShort Lab
              </h1>
              <p className="text-sm text-slate-300">
                Advanced UI • Multi-preview • Live logs • Presets • Upload manager
              </p>
              <p className="text-[11px] text-slate-500 mt-1">
                Backend: <span className="font-mono">{API_BASE}</span>
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <button className="px-3 py-2 rounded-lg bg-slate-800/50 hover:bg-slate-800/70 flex items-center gap-2 text-xs">
              <Settings size={16} />
              Settings
            </button>
          </div>
        </header>

        {error && (
          <div className="mb-4 rounded-lg bg-red-900/40 border border-red-700/60 px-3 py-2 text-xs">
            <div className="font-semibold mb-1">Backend error</div>
            <div className="font-mono break-all">{error}</div>
          </div>
        )}

        <main className="grid grid-cols-12 gap-6">
          {/* Left column: controls */}
          <section className="col-span-4 bg-[#071124] p-4 rounded-2xl shadow-md">
            <div className="mb-4">
              <label className="text-xs text-slate-400">Mode</label>
              <div className="mt-2 flex gap-2">
                <button
                  onClick={() => setMode("TEXT")}
                  className={`px-3 py-2 rounded-md text-xs ${
                    mode === "TEXT" ? "bg-slate-700" : "bg-slate-800/40"
                  }`}
                >
                  Text
                </button>
                <button
                  onClick={() => setMode("IMAGE")}
                  className={`px-3 py-2 rounded-md text-xs ${
                    mode === "IMAGE" ? "bg-slate-700" : "bg-slate-800/40"
                  }`}
                >
                  Image
                </button>
              </div>
            </div>

            <div className="mb-3">
              <label className="text-xs text-slate-400">Prompt</label>
              <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                rows={3}
                className="mt-2 w-full rounded-md bg-slate-900 p-3 text-sm outline-none border border-slate-800 focus:border-cyan-500/70"
              />
            </div>

            <div className="mb-4 flex items-center gap-2">
              <label className="text-xs text-slate-400">Duration (sec)</label>
              <input
                type="number"
                value={duration}
                onChange={(e) => setDuration(Number(e.target.value) || 1)}
                min={1}
                max={60}
                className="ml-auto w-24 p-2 rounded-md bg-slate-900 text-sm outline-none border border-slate-800 focus:border-cyan-500/70"
              />
            </div>

            <div className="flex gap-3">
              <button
                onClick={startGenerate}
                disabled={isGenerating}
                className={`flex-1 py-3 rounded-xl bg-gradient-to-r from-[#06b6d4] to-[#0ea5a4] font-bold shadow-lg flex items-center justify-center gap-2 text-sm ${
                  isGenerating ? "opacity-60 cursor-wait" : ""
                }`}
              >
                <Play size={18} />
                {isGenerating ? "Generating..." : "Generate"}
              </button>
              <label className="py-3 px-4 rounded-xl bg-slate-700/40 flex items-center gap-2 text-xs cursor-pointer">
                <CloudUpload size={16} />
                Upload
                <input
                  type="file"
                  accept="video/*,image/*"
                  className="hidden"
                  onChange={(e) => e.target.files && onFileUpload(e.target.files[0])}
                />
              </label>
            </div>

            <div className="mt-6">
              <h3 className="text-sm text-slate-300 mb-2">Presets</h3>
              <div className="flex flex-col gap-2">
                {presets.map((p) => (
                  <motion.button
                    key={p.id}
                    whileHover={{ scale: 1.02 }}
                    onClick={() => {
                      setPrompt(p.prompt);
                      setDuration(p.duration);
                    }}
                    className="text-left p-3 rounded-lg bg-slate-800/40"
                  >
                    <div className="flex justify-between items-center">
                      <div>
                        <div className="font-semibold text-sm">{p.name}</div>
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
              <div className="mt-1 flex flex-col gap-2 max-h-36 overflow-auto">
                {uploads.length === 0 && (
                  <div className="text-xs text-slate-500">No uploads yet</div>
                )}
                {uploads.map((u) => (
                  <div
                    key={u.id}
                    className="flex items-center justify-between p-2 bg-slate-900 rounded"
                  >
                    <div className="truncate text-xs">{u.name}</div>
                    <div className="flex items-center gap-2">
                      <a
                        href={u.url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-[11px] text-slate-300 underline"
                      >
                        Preview
                      </a>
                      <button
                        onClick={() => removeUpload(u.id)}
                        className="p-1 rounded bg-slate-800/50"
                      >
                        <Trash2 size={12} />
                      </button>
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
                    <div className="text-xs text-slate-400">
                      Main preview — click thumbnails to swap.
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={handleDownload}
                      className="px-3 py-2 rounded bg-slate-800/50 flex items-center gap-1 text-xs"
                    >
                      <Download size={16} />
                      Download
                    </button>
                  </div>
                </div>

                <div
                  className="bg-black rounded-lg overflow-hidden relative flex items-center justify-center"
                  style={{ height: 480 }}
                >
                  <AnimatePresence>
                    {activeJob && activeJob.outputUrl ? (
                      <motion.video
                        key={activeJob.jobId}
                        src={activeJob.outputUrl}
                        controls
                        autoPlay
                        className="w-full h-full object-cover"
                      />
                    ) : (
                      <motion.div
                        key="placeholder"
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        className="w-full h-full flex items-center justify-center text-slate-400"
                      >
                        <div className="text-center">
                          <div className="mb-2 text-sm">No generated output yet</div>
                          <div className="text-xs">
                            Enter a prompt and hit <span className="font-semibold">Generate</span>.
                          </div>
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>

                  {activeJob && (
                    <div className="absolute bottom-0 left-0 right-0 bg-black/60 px-3 py-2 text-xs flex items-center gap-3">
                      <div className="flex-1">
                        <div className="flex justify-between mb-1">
                          <span className="uppercase tracking-wide text-[10px] text-slate-300">
                            {activeJob.status}
                          </span>
                          <span>{activeJob.progress ?? 0}%</span>
                        </div>
                        <div className="w-full bg-slate-800 h-1 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-cyan-400"
                            style={{ width: `${activeJob.progress ?? 0}%` }}
                          />
                        </div>
                      </div>
                    </div>
                  )}
                </div>

                <div className="mt-3 grid grid-cols-3 gap-2">
                  {jobs.slice(0, 3).map((j) => (
                    <motion.div
                      key={j.jobId}
                      whileHover={{ scale: 1.02 }}
                      onClick={() => setSelectedJob(j.jobId)}
                      className={`p-2 rounded-lg cursor-pointer ${
                        selectedJob === j.jobId
                          ? "ring-2 ring-slate-600 bg-slate-900/60"
                          : "bg-slate-900/40"
                      }`}
                    >
                      <div className="h-24 bg-black rounded mb-2 flex items-center justify-center text-slate-500 text-[11px] overflow-hidden">
                        {j.outputUrl ? (
                          <video
                            src={j.outputUrl}
                            className="w-full h-full object-cover"
                            muted
                          />
                        ) : (
                          "Preview"
                        )}
                      </div>
                      <div className="text-[11px] truncate">{j.prompt}</div>
                      <div className="text-[10px] text-slate-400">
                        {j.progress ?? 0}% — {j.status}
                      </div>
                    </motion.div>
                  ))}
                </div>
              </div>

              <div className="col-span-4 bg-[#071124] rounded-2xl p-4 shadow-md flex flex-col">
                <h3 className="font-semibold mb-2 text-sm">Jobs & Logs</h3>
                <div className="flex-1 overflow-auto p-2 bg-slate-900/30 rounded">
                  {jobs.length === 0 && (
                    <div className="text-sm text-slate-500">
                      No jobs yet — hit Generate.
                    </div>
                  )}
                  {jobs.map((j) => (
                    <div
                      key={j.jobId}
                      className="p-2 border-b border-slate-800 last:border-b-0"
                    >
                      <div className="flex justify-between items-center">
                        <div>
                          <div className="font-medium text-xs">{j.jobId}</div>
                          <div className="text-[11px] text-slate-400 truncate max-w-[180px]">
                            {j.prompt}
                          </div>
                        </div>
                        <div className="text-sm">{j.progress ?? 0}%</div>
                      </div>
                      <div className="mt-2 text-[11px] text-slate-400 max-h-20 overflow-auto font-mono">
                        {(j.logs || []).slice(-5).map((l, i) => (
                          <div key={i}>{l}</div>
                        ))}
                      </div>
                      <div className="mt-2 flex gap-2">
                        <button
                          onClick={() => setSelectedJob(j.jobId)}
                          className="text-[11px] px-2 py-1 rounded bg-slate-800/40"
                        >
                          View
                        </button>
                        <button
                          onClick={() =>
                            setJobs((prev) =>
                              prev.filter((x) => x.jobId !== j.jobId),
                            )
                          }
                          className="text-[11px] px-2 py-1 rounded bg-red-700/60"
                        >
                          Delete
                        </button>
                      </div>
                    </div>
                  ))}
                </div>

                <div className="mt-3 text-[11px] text-slate-500">
                  Live logs stream from your backend as jobs run.
                </div>
              </div>
            </div>
          </section>
        </main>

        <footer className="mt-8 text-center text-slate-500 text-xs">
          Made with ❤️ for AI Creative Explorer — wired to {API_BASE}
        </footer>
      </div>
    </div>
  );
}
