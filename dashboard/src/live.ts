// GET a path once, then again (debounced) whenever one of `events` arrives on
// the stream. The last good answer stays on screen while a refetch is in flight.
import { useCallback, useEffect, useRef, useState } from "react";
import { getJSON } from "./api";
import { useEvents } from "./events";

export function useLive<T>(path: string, events: string[], debounceMs = 800) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const load = useCallback(() => {
    getJSON<T>(path)
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [path]);
  useEffect(load, [load]);
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);
  useEvents(events, () => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(load, debounceMs);
  });
  return { data, error, reload: load };
}

/** The current Unix second, ticking every `everyMs`. */
export function useNow(everyMs = 15000): number {
  const [now, setNow] = useState(() => Math.floor(Date.now() / 1000));
  useEffect(() => {
    const t = setInterval(() => setNow(Math.floor(Date.now() / 1000)), everyMs);
    return () => clearInterval(t);
  }, [everyMs]);
  return now;
}

export function prefersReducedMotion(): boolean {
  return typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
}
