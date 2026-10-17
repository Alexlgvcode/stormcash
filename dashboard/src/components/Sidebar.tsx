// Persistent shell (spec §18.1, issue #93): a left sidebar with the tabs, then,
// quietly at the bottom, Demo mode, the connection status, the clock and Reset demo.
import { useEffect, useState } from "react";
import { ApiError, getJSON, operatorPost, type Health } from "../api";
import { useEventsStatus } from "../events";
import { Icon, type IconName } from "./Icon";
import { Eyebrow } from "./ui";

const DOT = { live: "bg-success", connecting: "bg-warning animate-pulse", down: "bg-danger" };
const DOT_LABEL = { live: "Live", connecting: "Connecting…", down: "Disconnected" };

type Item = { id: string; label: string; icon: IconName };
const MAIN: Item[] = [
  { id: "intro", label: "Intro", icon: "intro" },
  { id: "accounts", label: "Accounts", icon: "accounts" },
  { id: "cases", label: "Cases", icon: "cases" },
  { id: "town", label: "Town", icon: "town" },
];
const AGENTS: Item[] = [
  { id: "droid", label: "Droid", icon: "droid" },
  { id: "evals", label: "Evals", icon: "evals" },
];

function NavItem({ item, active }: { item: Item; active: boolean }) {
  const intro = item.id === "intro";
  return (
    <a
      href={`#${item.id}`}
      aria-current={active ? "page" : undefined}
      aria-keyshortcuts={intro ? "I" : undefined}
      title={intro ? "Opening slide (press I)" : undefined}
      className={`flex items-center gap-2.5 px-2.5 py-1.5 text-ui hover:bg-accent-tint ${
        active ? "font-medium text-accent" : "text-nav"
      }`}
    >
      <Icon name={item.icon} />
      {item.label}
    </a>
  );
}

export function Sidebar({ tab }: { tab: string }) {
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
    <aside className="sticky top-0 flex h-screen w-44 shrink-0 flex-col border-r border-rule px-3 py-5">
      <div className="mb-6 px-2.5 text-[18px] font-semibold text-heading">StormCash</div>
      <nav className="flex flex-col gap-0.5">
        {MAIN.map((item) => (
          <NavItem key={item.id} item={item} active={tab === item.id} />
        ))}
        <div className="mt-6 mb-1.5 px-2.5">
          <Eyebrow>Agents</Eyebrow>
        </div>
        {AGENTS.map((item) => (
          <NavItem key={item.id} item={item} active={tab === item.id} />
        ))}
      </nav>
      <div className="mt-auto space-y-2 px-2.5 text-th text-secondary">
        {health?.demo_mode && <div className="text-ui font-medium text-warning">Demo mode</div>}
        {health && !health.nessie_enabled && <div className="text-danger">Nessie off: ledger only</div>}
        <div className="flex items-center gap-2">
          <span className={`h-2 w-2 rounded-full ${DOT[status]}`} />
          {DOT_LABEL[status]}
          <time className="ml-auto tabular-nums">
            {now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
          </time>
        </div>
        <button
          onClick={resetDemo}
          disabled={reset.busy}
          className="flex items-center gap-1.5 text-nav hover:text-heading disabled:opacity-60"
        >
          <Icon name="reset" size={14} />
          {reset.busy ? "Resetting…" : "Reset demo"}
        </button>
        {reset.message && <div className="break-words text-ink">{reset.message}</div>}
      </div>
    </aside>
  );
}
