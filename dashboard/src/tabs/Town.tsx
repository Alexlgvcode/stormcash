// Town tab (spec §18.4, §16.6): the 40-shop simulated town around the three
// real phones, relay paths, and sliders that re-run a quick in-memory model.
import { useCallback, useEffect, useRef, useState } from "react";
import { getJSON, type Quick, type QuickResult, type RelayPath, type Town } from "../api";
import { useEvents } from "../events";
import { dollars } from "../format";

const CELL = 22;
const REGION_FILL = ["#0c4a6e", "#1e3a8a", "#134e4a", "#3f3f46"];

interface Pulse {
  id: number;
  x: number;
  y: number;
}

function TownMap({ town, pulses }: { town: Town; pulses: Pulse[] }) {
  const { w, h } = town.grid;
  const alertsByRegion = new Map<string, Town["alerts"]>();
  for (const a of town.alerts) {
    if (a.region_id) alertsByRegion.set(a.region_id, [...(alertsByRegion.get(a.region_id) ?? []), a]);
  }
  return (
    <svg viewBox={`0 0 ${w * CELL} ${h * CELL}`} className="w-full rounded-2xl border border-slate-800 bg-slate-950">
      <defs>
        <pattern id="hatch" width="10" height="10" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <line x1="0" y1="0" x2="0" y2="10" stroke="#f43f5e" strokeWidth="3" strokeOpacity="0.45" />
        </pattern>
      </defs>
      {town.regions.map((r, i) => (
        <g key={r.region_id}>
          <rect x={r.x * CELL} y={r.y * CELL} width={r.w * CELL} height={r.h * CELL} fill={REGION_FILL[i % 4]}
            fillOpacity={0.35} stroke="#334155" />
          {town.dark_regions.includes(r.region_id) && (
            <rect x={r.x * CELL} y={r.y * CELL} width={r.w * CELL} height={r.h * CELL} fill="url(#hatch)" />
          )}
          <text x={r.x * CELL + 8} y={r.y * CELL + 22} fill="#e2e8f0" fontSize="16" fontWeight="600">
            {r.display_name}
            {town.dark_regions.includes(r.region_id) ? " · dark" : ""}
          </text>
          {(alertsByRegion.get(r.region_id) ?? []).map((a, j) => (
            <text key={a.alert_id} x={r.x * CELL + 8} y={r.y * CELL + 42 + j * 18} fill="#fbbf24" fontSize="13">
              ⚠ {a.event} ({a.source})
            </text>
          ))}
        </g>
      ))}
      {town.merchants.map((m) => (
        <g key={m.merchant_id}>
          <circle cx={(m.x + 0.5) * CELL} cy={(m.y + 0.5) * CELL} r={m.simulated ? 5 : 10}
            fill={m.simulated ? (m.pool_eligible ? "#94a3b8" : "#f59e0b") : "#38bdf8"}
            stroke={m.simulated ? "none" : "#e0f2fe"} strokeWidth="2">
            <title>
              {m.display_name}
              {m.simulated ? " (simulated)" : ""}
              {m.pool_eligible ? "" : " · pool payouts suspended"}
            </title>
          </circle>
          {!m.simulated && (
            <text x={(m.x + 0.5) * CELL + 14} y={(m.y + 0.5) * CELL + 5} fill="#e0f2fe" fontSize="15" fontWeight="700">
              {m.display_name}
            </text>
          )}
        </g>
      ))}
      {pulses.map((p) => (
        <circle key={p.id} cx={(p.x + 0.5) * CELL} cy={(p.y + 0.5) * CELL} r="6" fill="none" stroke="#34d399"
          strokeWidth="3">
          <animate attributeName="r" from="6" to="34" dur="1.6s" fill="freeze" />
          <animate attributeName="opacity" from="1" to="0" dur="1.6s" fill="freeze" />
        </circle>
      ))}
    </svg>
  );
}

function Legend() {
  return (
    <div className="flex flex-wrap gap-4 text-sm text-slate-300">
      <span className="flex items-center gap-2"><span className="h-4 w-4 rounded-full bg-sky-400" /> real phone</span>
      <span className="flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full bg-slate-400" /> simulated shop</span>
      <span className="flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full bg-amber-500" /> simulated, pool payouts suspended</span>
      <span className="flex items-center gap-2"><span className="h-3 w-5 bg-rose-500/40" /> dark region (no uploads)</span>
      <span className="flex items-center gap-2"><span className="h-3 w-3 rounded-full border-2 border-emerald-400" /> payment</span>
    </div>
  );
}

function RelayPanel({ paths }: { paths: RelayPath[] }) {
  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
      <h2 className="mb-3 text-xl font-semibold text-white">Relay paths</h2>
      {paths.length === 0 && <p className="text-slate-400">No relayed payments yet.</p>}
      <ol className="max-h-80 space-y-2 overflow-y-auto">
        {paths.map((p) => (
          <li key={p.tag_hash} className="text-base">
            <span className="text-slate-100">
              {p.path.map((h) => h.name).join(" → ")} → server
            </span>
            <span className="block text-sm text-slate-400">
              {dollars(p.amount_cents)} at {p.merchant}
              {p.simulated ? " (simulated)" : ""} · {p.hops} {p.hops === 1 ? "hop" : "hops"} ·{" "}
              {Math.max(0, Math.round(p.latency_s / 60))} min
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}

const METRICS: { key: keyof QuickResult; label: string; show: (v: number) => string; max: (a: number, b: number) => number }[] = [
  { key: "share_refused_offline", label: "Double spends refused offline", show: (v) => `${Math.round(v * 100)}%`, max: () => 1 },
  { key: "share_caught_at_settlement", label: "Caught at settlement", show: (v) => `${Math.round(v * 100)}%`, max: () => 1 },
  { key: "mean_loss_per_cheater_cents", label: "Pool loss per cheater", show: (v) => dollars(v), max: (a, b) => Math.max(a, b, 1) },
  { key: "median_hours_to_settlement", label: "Median hours to settlement", show: (v) => `${v.toFixed(1)} h`, max: (a, b) => Math.max(a, b, 0.1) },
];

function Bars({ base, cur }: { base: QuickResult; cur: QuickResult }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {METRICS.map((m) => {
        const b = (base[m.key] as number | null) ?? 0;
        const c = (cur[m.key] as number | null) ?? 0;
        const max = m.max(b, c);
        return (
          <div key={m.key} className="rounded-xl bg-slate-950 p-4">
            <div className="mb-2 text-base font-medium text-slate-200">{m.label}</div>
            {[["Default town", b, "bg-slate-500"], ["Your settings", c, "bg-sky-400"]].map(([label, v, color]) => (
              <div key={label as string} className="mb-1 flex items-center gap-2">
                <span className="w-28 shrink-0 text-sm text-slate-400">{label}</span>
                <div className="h-5 flex-1 rounded bg-slate-800">
                  <div className={`h-5 rounded ${color} transition-all duration-500`}
                    style={{ width: `${Math.min(100, ((v as number) / max) * 100)}%` }} />
                </div>
                <span className="w-16 text-right font-mono text-sm text-slate-100">{m.show(v as number)}</span>
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}

function Sliders() {
  const [adoption, setAdoption] = useState(0.6);
  const [pLink, setPLink] = useState(0.6);
  const [pUplink, setPUplink] = useState(0.03);
  const [quick, setQuick] = useState<Quick | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const t = setTimeout(() => {
      setBusy(true);
      getJSON<Quick>(`/v1/town/quick?adoption=${adoption}&p_link=${pLink}&p_uplink=${pUplink}`)
        .then((q) => {
          setQuick(q);
          setError(null);
        })
        .catch((e) => setError(String(e)))
        .finally(() => setBusy(false));
    }, 250);
    return () => clearTimeout(t);
  }, [adoption, pLink, pUplink]);

  const slider = (label: string, value: number, set: (v: number) => void, min: number, max: number, step: number,
    show: (v: number) => string) => (
    <label className="block">
      <span className="flex justify-between text-base text-slate-200">
        {label} <span className="font-mono">{show(value)}</span>
      </span>
      <input type="range" min={min} max={max} step={step} value={value}
        onChange={(e) => set(Number(e.target.value))} className="w-full accent-sky-400" />
    </label>
  );

  return (
    <section className="space-y-4 rounded-2xl border border-slate-800 bg-slate-900 p-5">
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-xl font-semibold text-white">How often does this work?</h2>
        <span className="text-sm text-slate-400">
          {busy ? "re-simulating…" : quick ? `simulated in ${quick.seconds}s` : ""}
        </span>
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        {slider("Adoption", adoption, setAdoption, 0.1, 1, 0.05, (v) => `${Math.round(v * 100)}%`)}
        {slider("Foot traffic (p_link)", pLink, setPLink, 0.05, 1, 0.05, (v) => v.toFixed(2))}
        {slider("Relay density (uplink/h)", pUplink, setPUplink, 0.005, 0.2, 0.005, (v) => v.toFixed(3))}
      </div>
      {error && <p className="text-rose-300">{error}</p>}
      {quick && <Bars base={quick.baseline} cur={quick.current} />}
      <p className="text-sm text-slate-400">
        Simulated: a quick in-memory model of the town (5 seeded runs, {quick?.current.double_spend_attempts ?? "…"}{" "}
        double-spend attempts), not live data.
      </p>
    </section>
  );
}

export function TownTab() {
  const [town, setTown] = useState<Town | null>(null);
  const [paths, setPaths] = useState<RelayPath[]>([]);
  const [pulses, setPulses] = useState<Pulse[]>([]);
  const pulseId = useRef(0);

  const load = useCallback(() => {
    getJSON<Town>("/v1/town").then(setTown).catch(() => undefined);
    getJSON<RelayPath[]>("/v1/relay/paths?limit=20").then(setPaths).catch(() => undefined);
  }, []);
  useEffect(load, [load]);
  useEvents(["town", "candidate", "upload"], load);
  useEvents(["payment"], (data) => {
    const p = data as { merchant_id: string };
    const m = town?.merchants.find((x) => x.merchant_id === p.merchant_id);
    if (!m) return;
    const id = ++pulseId.current;
    setPulses((cur) => [...cur, { id, x: m.x, y: m.y }]);
    setTimeout(() => setPulses((cur) => cur.filter((q) => q.id !== id)), 1800);
  });

  if (!town) return <p className="p-8 text-xl text-slate-300">Loading…</p>;
  const s = town.town_stats;
  return (
    <div className="grid gap-6 p-6 xl:grid-cols-[3fr_2fr]">
      <div className="space-y-4">
        <p className="text-lg text-slate-300">
          Your 3 phones are part of a {town.merchants.length}-shop town. Every shop but the real ones is{" "}
          <span className="font-semibold text-slate-100">simulated</span>, checked by the same code as the phones.
        </p>
        <TownMap town={town} pulses={pulses} />
        <Legend />
        {s && (
          <p className="text-base text-slate-300">
            Seeded town (seed {s.seed}, simulated): {s.double_spends.attempts} double-spend attempts,{" "}
            {Math.round((s.double_spends.share_refused_offline ?? 0) * 100)}% refused offline,{" "}
            {Math.round((s.double_spends.share_caught_at_settlement ?? 0) * 100)}% caught at settlement, pool loss{" "}
            {dollars(s.mean_loss_per_cheater_cents ?? 0)} per cheater, median {s.median_hours_to_settlement} h to settle.
          </p>
        )}
      </div>
      <div className="space-y-6">
        <Sliders />
        <RelayPanel paths={paths} />
      </div>
    </div>
  );
}
