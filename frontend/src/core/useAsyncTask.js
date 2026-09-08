import { useCallback, useEffect, useRef, useState } from "react";

// Ignore superseded and unmounted responses; never show ticker A under ticker B.
export default function useAsyncTask() {
  const sequence = useRef(0);
  const controller = useRef(null);
  const [state, setState] = useState({ data: null, error: "", busy: false });
  const reset = useCallback(() => {
    sequence.current += 1;
    controller.current?.abort();
    setState({ data: null, error: "", busy: false });
  }, []);
  const run = useCallback(async (loader) => {
    const id = ++sequence.current;
    controller.current?.abort();
    const next = new AbortController();
    controller.current = next;
    setState({ data: null, error: "", busy: true });
    try {
      const data = await loader(next.signal);
      if (id === sequence.current) setState({ data, error: "", busy: false });
      return data;
    } catch (error) {
      if (id === sequence.current && error.name !== "AbortError") setState({ data: null, error: error.message || "The request could not finish.", busy: false });
      return null;
    }
  }, []);
  useEffect(() => () => { sequence.current += 1; controller.current?.abort(); }, []);
  return { ...state, run, reset };
}
