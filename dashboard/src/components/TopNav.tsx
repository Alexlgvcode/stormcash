// Persistent shell (spec §18.1). A status bar every tab shares: the mode
// (derived from Nessie's own escrow moves), the live stream, Nessie, Demo mode
// and the clock. Tabs sit in the bar from 1024 px up, and in a bottom tab bar
// below that, where thumbs are. Reset demo hides in a menu so it's never hit by accident.
import { useEffect, useRef, useState } from "react";
import { ApiError, operatorPost } from "../api";
import { useEventsStatus } from "../events";
import { timeOfDay } from "../format";
import { useStatus } from "../status";
import { Icon, type IconName } from "./Icon";

export const NAV: { id: string; label: string; icon: IconName }[] = [
  { id: "overview", label: "Overview", icon: "overview" },
  { id: "town", label: "Network", icon: "network" },
  { id: "cases", label: "Cases", icon: "shield" },
  { id: "ledger", label: "Ledger", icon: "ledger" },
  { id: "stormdesk", label: "StormDesk", icon: "agent" },
];

const LINK = { live: "bg-teal", connecting: "bg-amber", down: "bg-coral" };
const LINK_LABEL = { live: "Live", connecting: "Connecting…", down: "Disconnected" };

/** Storm / Normal, and what it was read from. */
export function ModeChip() {
  const { mode } = useStatus();
  if (!mode) return <span className="text-th text-secondary">Mode…</span>;
  const storm = mode.mode === "storm";
  const label = storm ? "Storm Mode" : mode.mode === "normal" ? "Normal" : "Mode unknown";
  const short = storm ? "Storm" : mode.mode === "normal" ? "Normal" : "Unknown";
  return (
    <span title={`Derived from the ${mode.basis}`}
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-pill border px-2.5 py-0.5 text-th font-semibold ${
        storm ? "border-amber/70 bg-warning-bg text-warning" : "border-rule bg-surface text-neutral"}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${storm ? "bg-amber" : "bg-neutral"}`} />
      <span className="max-[379px]:hidden">{label}</span>
      <span className="min-[380px]:hidden">{short}</span>
    </span>
  );
}

function DemoMenu() {
  const [open, setOpen] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    addEventListener("mousedown", close);
    return () => removeEventListener("mousedown", close);
  }, [open]);

  async function resetDemo() {
    if (!confirm("Reset the demo? This clears real-device demo data and reissues Maya's certificate.")) return;
    setBusy(true);
    try {
      await operatorPost("/v1/demo/reset");
      setMsg("Demo reset");
      setTimeout(() => location.reload(), 600);
    } catch (e) {
      setMsg(e instanceof ApiError && e.status === 404 ? "Reset isn't available on this server yet" : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div ref={ref} className="relative">
      <button onClick={() => setOpen((v) => !v)} aria-expanded={open} aria-haspopup="menu"
        className="min-h-9 whitespace-nowrap rounded-button border border-rule px-2.5 text-th font-semibold text-secondary hover:text-heading pointer-coarse:min-h-11">
        Demo ▾
      </button>
      {open && (
        <div role="menu" className="absolute right-0 top-full z-40 mt-1 w-64 rounded-[10px] border border-rule bg-raised p-2 shadow-lg">
          <button role="menuitem" onClick={resetDemo} disabled={busy}
            className="min-h-11 w-full rounded-button px-3 text-left font-semibold text-danger hover:bg-surface disabled:opacity-50">
            {busy ? "Resetting…" : "Reset demo…"}
          </button>
          <p className="px-3 pb-1 text-th text-secondary">Wipes the registered demo phones. Asks first.</p>
          {msg && <p className="px-3 pb-1 text-th text-ink">{msg}</p>}
        </div>
      )}
    </div>
  );
}

export function TopNav({ tab }: { tab: string }) {
  const link = useEventsStatus();
  const { health, healthError } = useStatus();
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 15000);
    return () => clearInterval(timer);
  }, []);

  return (
    <>
      <header className="sticky top-0 z-30 border-b border-rule bg-page/95 backdrop-blur">
        <div className="mx-auto flex min-h-14 max-w-[1600px] items-center gap-x-3 gap-y-1 px-4 sm:gap-x-6 sm:px-6 lg:px-8">
          <a href="#overview" className="flex items-center gap-2 py-3 text-[17px] font-bold text-heading">
            <span aria-hidden="true" className="inline-block h-2.5 w-2.5 rotate-45 bg-teal" />
            StormCash
            <span className="hidden text-th font-normal text-secondary xl:inline">Operations</span>
          </a>
          <nav aria-label="Main" className="hidden items-stretch gap-1 self-stretch lg:flex">
            {NAV.map((item) => {
              const active = tab === item.id;
              return (
                <a key={item.id} href={`#${item.id}`} aria-current={active ? "page" : undefined}
                  className={`flex items-center border-b-2 px-3 text-ui ${
                    active ? "border-ink font-semibold text-heading" : "border-transparent text-secondary hover:text-heading"
                  }`}>
                  {item.label}
                </a>
              );
            })}
          </nav>
          <div className="ml-auto flex min-w-0 items-center gap-x-3 gap-y-1 text-th sm:gap-x-4">
            <ModeChip />
            <span className="flex items-center gap-1.5 whitespace-nowrap text-secondary" title="Live event stream (/v1/stream)">
              <span className={`h-2 w-2 rounded-full ${LINK[link]} ${link === "connecting" ? "motion-safe:animate-pulse" : ""}`} />
              <span className="hidden sm:inline lg:hidden xl:inline">{LINK_LABEL[link]}</span>
            </span>
            {healthError && <span className="hidden text-danger md:inline">Server unreachable</span>}
            {health && !health.nessie_enabled && <span className="hidden text-danger md:inline">Nessie off</span>}
            {health?.demo_mode && <span className="hidden whitespace-nowrap font-semibold text-warning md:inline lg:hidden xl:inline">Demo mode</span>}
            <time className="hidden whitespace-nowrap tabular-nums text-secondary md:inline lg:hidden xl:inline">{timeOfDay(now)}</time>
            <DemoMenu />
          </div>
        </div>
      </header>
      <nav aria-label="Main"
        className="fixed inset-x-0 bottom-0 z-30 border-t border-rule bg-page/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden">
        <div className="mx-auto grid max-w-[720px] grid-cols-5">
          {NAV.map((item) => {
            const active = tab === item.id;
            return (
              <a key={item.id} href={`#${item.id}`} aria-current={active ? "page" : undefined}
                className={`flex min-h-14 flex-col items-center justify-center gap-0.5 text-[11px] leading-4 sm:text-th ${
                  active ? "font-semibold text-heading" : "text-secondary"}`}>
                <Icon name={item.icon} size={22} className={active ? "text-teal" : ""} />
                <span className="max-w-full truncate px-0.5">{item.label}</span>
              </a>
            );
          })}
        </div>
      </nav>
    </>
  );
}
