import { useState } from "react";
import useAsyncTask from "./useAsyncTask";
import { runCoreJob } from "./coreJobClient";

export default function useCoreJob() {
  const task = useAsyncTask();
  const [progress, setProgress] = useState("");
  function run(body) {
    setProgress("Starting review…");
    return task.run(signal => runCoreJob(body, { signal, onProgress: value => { if (!signal.aborted) setProgress(value); } }));
  }
  function cancel() { task.reset(); setProgress("Cancelled. Any in-flight data request may take a moment to stop."); }
  return { ...task, run, cancel, progress };
}
