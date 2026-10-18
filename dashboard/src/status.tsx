// What every tab's header needs once: the server's health, the Nessie call log
// (newest first, live over the stream) and the mode derived from it.
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { getJSON, type Health, type NessieCall } from "./api";
import { useEvents } from "./events";
import { modeFromCalls, type Mode } from "./overview";

interface Status {
  health: Health | null;
  healthError: string | null;
  calls: NessieCall[] | null;
  mode: { mode: Mode; at: number | null; basis: string } | null;
}

const StatusContext = createContext<Status>({ health: null, healthError: null, calls: null, mode: null });

export function StatusProvider({ children }: { children: ReactNode }) {
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [calls, setCalls] = useState<NessieCall[] | null>(null);

  useEffect(() => {
    const check = () =>
      getJSON<Health>("/v1/health")
        .then((h) => {
          setHealth(h);
          setHealthError(null);
        })
        .catch((e) => setHealthError(String(e)));
    check();
    const t = setInterval(check, 30000);
    getJSON<NessieCall[]>("/v1/nessie/log?limit=300").then(setCalls).catch(() => setCalls([]));
    return () => clearInterval(t);
  }, []);
  useEvents(["nessie_call"], (data) => setCalls((prev) => [data as NessieCall, ...(prev ?? [])].slice(0, 300)));
  useEvents(["accounts"], (data) => {
    // A demo reset clears the log: read it again.
    if ((data as { reset?: boolean }).reset) getJSON<NessieCall[]>("/v1/nessie/log?limit=300").then(setCalls).catch(() => undefined);
  });

  const mode = calls ? modeFromCalls(calls) : null;
  return <StatusContext.Provider value={{ health, healthError, calls, mode }}>{children}</StatusContext.Provider>;
}

export const useStatus = () => useContext(StatusContext);
