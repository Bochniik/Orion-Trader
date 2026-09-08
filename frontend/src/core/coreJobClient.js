import { startCoreJob, getCoreJob, cancelCoreJob } from "../api/api";

function aborted() { return new DOMException("Analysis cancelled", "AbortError"); }
export function pause(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) { reject(aborted()); return; }
    const stop = () => { clearTimeout(timer); reject(aborted()); };
    const timer = setTimeout(() => { signal?.removeEventListener("abort", stop); resolve(); }, ms);
    signal?.addEventListener("abort", stop, { once: true });
  });
}

export async function runCoreJob(body, { signal, onProgress = () => {} } = {},
  api = { start: startCoreJob, get: getCoreJob, cancel: cancelCoreJob, wait: pause }) {
  let job;
  try {
    // Admission can wait briefly for a cancelled task's in-flight stage to exit.
    for (let attempt = 0; attempt < 30; attempt += 1) {
      if (signal?.aborted) throw aborted();
      try { job = await api.start(body); break; }
      catch (error) {
        if (error.status !== 409 || attempt === 29) throw error;
        onProgress("Waiting for the previous review to finish stopping…");
        await api.wait(1000, signal);
      }
    }
    // Do not abort the POST before we know its job ID: otherwise a response
    // arriving after navigation could leave uncancellable server work behind.
    while (true) {
      if (signal?.aborted) throw aborted();
      onProgress(job.stage);
      if (job.state === "completed") return job.result;
      if (!["queued", "running"].includes(job.state)) throw new Error(job.stage || "The review stopped.");
      await api.wait(800, signal);
      if (signal?.aborted) throw aborted();
      job = await api.get(job.id, { signal });
    }
  } finally {
    // Also request cancellation after a polling failure, not just a UI abort.
    if (job && ["queued", "running"].includes(job.state)) {
      try { await api.cancel(job.id); } catch { /* timeout/logout remains a server-side stop boundary */ }
    }
  }
}
