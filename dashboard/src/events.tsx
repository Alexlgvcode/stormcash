// One EventSource for the whole dashboard (GET /v1/stream, spec §12.3).
// Components subscribe to event names; the provider tracks the connection
// state for the header dot and reconnects on its own (EventSource does).
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { API_BASE } from "./api";

type Handler = (data: unknown) => void;
type Status = "connecting" | "live" | "down";

interface Events {
  status: Status;
  subscribe: (events: string[], handler: Handler) => () => void;
}

// Every event the server publishes (§12.3); EventSource needs them by name.
const EVENT_NAMES = [
  "nessie_call", "accounts", "payment", "case_opened", "policy", "candidate",
  "stormdesk_step", "flag", "approval", "message", "upload", "town", "appeal", "owner_freeze", "author",
];

const EventsContext = createContext<Events | null>(null);

export function EventsProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>("connecting");
  const handlers = useRef(new Map<string, Set<Handler>>());

  useEffect(() => {
    const source = new EventSource(`${API_BASE}/v1/stream`);
    source.onopen = () => setStatus("live");
    source.onerror = () => setStatus(source.readyState === EventSource.CLOSED ? "down" : "connecting");
    for (const name of EVENT_NAMES) {
      source.addEventListener(name, (e) => {
        const data = JSON.parse((e as MessageEvent).data);
        handlers.current.get(name)?.forEach((h) => h(data));
      });
    }
    return () => source.close();
  }, []);

  const subscribe = (events: string[], handler: Handler) => {
    for (const name of events) {
      if (!handlers.current.has(name)) handlers.current.set(name, new Set());
      handlers.current.get(name)!.add(handler);
    }
    return () => events.forEach((name) => handlers.current.get(name)?.delete(handler));
  };

  return <EventsContext.Provider value={{ status, subscribe }}>{children}</EventsContext.Provider>;
}

export function useEventsStatus(): Status {
  return useContext(EventsContext)!.status;
}

/** Call `handler` for each of `events`; the latest handler is always used. */
export function useEvents(events: string[], handler: Handler): void {
  const ctx = useContext(EventsContext)!;
  const latest = useRef(handler);
  latest.current = handler;
  const key = events.join(",");
  useEffect(() => ctx.subscribe(key.split(","), (d) => latest.current(d)), [ctx, key]);
}
