// Persistent header (spec §18.1): title, Demo mode, connection dot, Reset demo, clock.
import { useEffect, useState } from "react";
import { ApiError, getJSON, operatorPost, type Health } from "../api";
import { useEventsStatus } from "../events";

const DOT = { live: "bg-emerald-400", connecting: "bg-amber-400 animate-pulse", down: "bg-rose-500" };
const DOT_LABEL = { live: "Live", connecting: "Connecting…", down: "Disconnected" };

export function Header() {
  const status = useEventsStatus();
  const [health, setHealth] = useState<Health | null>(null);
  const [now, setNow] = useState(new Date());
  const [reset, setReset] = useState<{ busy: boolean; message?: string }>({ busy: false });

  useEffect(() => {
    getJSON<Health>("/v1/health").then(setHealth).catch(() => setHealth(null));
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  async function resetDemo() {
    if (!confirm("Reset the demo? This clears real-device demo data and reissues Maya's certificate.")) return;
    setReset({ busy: true });
    try {
      await operatorPost("/v1/demo/reset");
      setReset({ busy: false, message: "Demo reset" });
      setTimeout(() => location.reload(), 600);
    } catch (e) {
      const msg = e instanceof ApiError && e.status === 404 ? "Reset isn't available on this server yet" : String(e);
      setReset({ busy: false, message: msg });
    }
  }

  return (
    <header className="flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-slate-800 bg-slate-950 px-6 py-4">
      <h1 className="text-3xl font-bold tracking-tight text-white">
        Storm<span className="text-sky-400">Cash</span>
      </h1>
      {health?.demo_mode && (
        <span className="rounded-full bg-amber-500/15 px-3 py-1 text-sm font-semibold text-amber-300">Demo mode</span>
      )}
      {health && !health.nessie_enabled && (
        <span className="rounded-full bg-rose-500/15 px-3 py-1 text-sm font-semibold text-rose-300">
          Nessie off: ledger only
        </span>
      )}
      <span className="flex items-center gap-2 text-sm text-slate-300">
        <span className={`h-3 w-3 rounded-full ${DOT[status]}`} />
        {DOT_LABEL[status]}
      </span>
      <div className="ml-auto flex items-center gap-4">
        {reset.message && <span className="text-sm text-slate-300">{reset.message}</span>}
        <button
          onClick={resetDemo}
          disabled={reset.busy}
          className="rounded-lg bg-slate-800 px-4 py-2 text-base font-semibold text-white hover:bg-slate-700 disabled:opacity-50"
        >
          {reset.busy ? "Resetting…" : "Reset demo"}
        </button>
        <time className="font-mono text-2xl tabular-nums text-slate-200">
          {now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
        </time>
      </div>
    </header>
  );
}
