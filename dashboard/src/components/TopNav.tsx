// Persistent shell (spec §18.1, issue #93) in the bank style: a top navigation
// bar with the tabs, then, quietly on the right, Demo mode, the connection
// status, the clock and Reset demo.
import { useEffect, useState } from "react";
import { ApiError, getJSON, operatorPost, type Health } from "../api";
import { useEventsStatus } from "../events";
import { timeOfDay } from "../format";

const DOT = { live: "bg-success", connecting: "bg-warning animate-pulse", down: "bg-danger" };
const DOT_LABEL = { live: "Live", connecting: "Connecting…", down: "Disconnected" };

const ITEMS = [
  { id: "accounts", label: "Accounts" },
  { id: "cases", label: "Cases" },
  { id: "town", label: "Town" },
  { id: "droid", label: "Droid" },
  { id: "evals", label: "Evals" },
];

export function TopNav({ tab }: { tab: string }) {
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
    <header className="border-b border-rule bg-page">
      <div className="mx-auto flex max-w-[1280px] flex-wrap items-center gap-x-8 px-10">
        <a href="#accounts" className="py-4 text-[19px] font-bold text-heading">StormCash</a>
        <nav className="flex items-center gap-7">
          {ITEMS.map((item) => {
            const active = tab === item.id;
            return (
              <a key={item.id} href={`#${item.id}`} aria-current={active ? "page" : undefined}
                className={`border-b-[3px] py-4 text-[16px] ${
                  active ? "border-accent font-semibold text-heading" : "border-transparent text-secondary hover:text-heading"
                }`}>
                {item.label}
              </a>
            );
          })}
        </nav>
        <div className="ml-auto flex flex-wrap items-center gap-x-5 gap-y-1 py-3 text-th">
          {health?.demo_mode && <span className="font-semibold text-warning">Demo mode</span>}
          {health && !health.nessie_enabled && <span className="text-danger">Nessie off: ledger only</span>}
          <span className="flex items-center gap-2 text-secondary">
            <span className={`h-2 w-2 rounded-full ${DOT[status]}`} />
            {DOT_LABEL[status]}
          </span>
          <time className="tabular-nums text-secondary">{timeOfDay(now)}</time>
          <button onClick={resetDemo} disabled={reset.busy} className="font-semibold text-accent hover:underline disabled:opacity-50">
            {reset.busy ? "Resetting…" : "Reset demo"}
          </button>
          {reset.message && <span className="text-ink">{reset.message}</span>}
        </div>
      </div>
    </header>
  );
}
