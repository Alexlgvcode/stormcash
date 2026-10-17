// Town tab (spec §18.4, §16.6): the 40-shop simulated town around the real
// phones, relay paths, and sliders that re-run a quick in-memory model.
import { useCallback, useEffect, useRef, useState } from "react";
import { getJSON, type Quick, type QuickResult, type RelayPath, type Town } from "../api";
import { Note, PageHeader, Pill, Section, Strip, Table, Tabs, Td, Th } from "../components/ui";
import { useEvents } from "../events";
import { dollars } from "../format";

const VIEWS = [
  { id: "map", label: "Map" },
  { id: "relay", label: "Relay paths" },
  { id: "whatif", label: "What-if" },
] as const;
type View = (typeof VIEWS)[number]["id"];

const CELL = 22;
const REGION_FILL = ["#F6F8FA", "#FFFFFF"];
const C = {
  rule: "#EBEEF1",
  hatch: "#D5DBE1",
  label: "#687385",
  heading: "#1A1B25",
  warning: "#A35A00",
  danger: "#B3093C",
  simulated: "#9AA3AF",
  real: "#2B3A9E",
  pulse: "#05690D",
};

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
    <svg viewBox={`0 0 ${w * CELL} ${h * CELL}`} className="w-full border border-rule" role="img"
      aria-label="Map of the simulated town">
      <defs>
        <pattern id="hatch" width="10" height="10" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <line x1="0" y1="0" x2="0" y2="10" stroke={C.hatch} strokeWidth="3" />
        </pattern>
      </defs>
      {town.regions.map((r, i) => {
        const dark = town.dark_regions.includes(r.region_id);
        return (
          <g key={r.region_id}>
            <rect x={r.x * CELL} y={r.y * CELL} width={r.w * CELL} height={r.h * CELL} fill={REGION_FILL[i % 2]}
              stroke={C.rule} />
            {dark && <rect x={r.x * CELL} y={r.y * CELL} width={r.w * CELL} height={r.h * CELL} fill="url(#hatch)" />}
            <text x={r.x * CELL + 8} y={r.y * CELL + 22} fill={dark ? C.warning : C.label} fontSize="15" fontWeight="500">
              {r.display_name}
              {dark ? " · dark" : ""}
            </text>
            {(alertsByRegion.get(r.region_id) ?? []).map((a, j) => (
              <text key={a.alert_id} x={r.x * CELL + 8} y={r.y * CELL + 42 + j * 18} fill={C.warning} fontSize="13">
                ⚠ {a.event} ({a.source})
              </text>
            ))}
          </g>
        );
      })}
      {town.merchants.map((m) => {
        const cx = (m.x + 0.5) * CELL;
        const cy = (m.y + 0.5) * CELL;
        const held = m.simulated && !m.pool_eligible;
        return (
          <g key={m.merchant_id}>
            <circle cx={cx} cy={cy} r={m.simulated ? (held ? 6 : 5) : 9}
              fill={m.simulated ? (held ? C.danger : C.simulated) : C.real}>
              <title>
                {m.display_name}
                {m.simulated ? " (simulated)" : ""}
                {m.pool_eligible ? "" : " · pool payouts suspended"}
              </title>
            </circle>
            {(!m.simulated || held) && (
              <text x={cx + 13} y={cy + 5} fill={held ? C.danger : C.heading} fontSize="14" fontWeight="600"
                stroke="#FFFFFF" strokeWidth="4" paintOrder="stroke">
                {m.display_name}
              </text>
            )}
          </g>
        );
      })}
      {pulses.map((p) => (
        <circle key={p.id} cx={(p.x + 0.5) * CELL} cy={(p.y + 0.5) * CELL} r="6" fill="none" stroke={C.pulse}
          strokeWidth="3">
          <animate attributeName="r" from="6" to="34" dur="1.6s" fill="freeze" />
          <animate attributeName="opacity" from="1" to="0" dur="1.6s" fill="freeze" />
        </circle>
      ))}
    </svg>
  );
}

function Legend() {
  const dot = (color: string, size: number) => (
    <span className="inline-block shrink-0 rounded-full" style={{ background: color, width: size, height: size }} />
  );
  return (
    <div className="flex flex-wrap gap-x-6 gap-y-2 py-3 text-th text-secondary">
      <span className="flex items-center gap-2">{dot(C.real, 14)} real phone</span>
      <span className="flex items-center gap-2">{dot(C.simulated, 9)} simulated shop</span>
      <span className="flex items-center gap-2">{dot(C.danger, 10)} simulated, pool payouts suspended</span>
      <span className="flex items-center gap-2">
        <span className="inline-block h-3 w-5 border border-rule"
          style={{ background: `repeating-linear-gradient(45deg, ${C.hatch} 0 3px, transparent 3px 7px)` }} />
        dark region (no uploads)
      </span>
      <span className="flex items-center gap-2">
        <span className="inline-block h-3 w-3 rounded-full border-2" style={{ borderColor: C.pulse }} /> payment
      </span>
      <span className="flex items-center gap-2"><span style={{ color: C.warning }}>⚠</span> weather alert (live or replayed)</span>
    </div>
  );
}

function RelayTable({ paths }: { paths: RelayPath[] }) {
  if (paths.length === 0) return <p className="py-2.5 text-secondary">No relayed payments yet.</p>;
  return (
    <Table>
      <thead>
        <tr>
          <Th>Path</Th>
          <Th>Payment</Th>
          <Th>Hops</Th>
          <Th num>To the server</Th>
        </tr>
      </thead>
      <tbody>
        {paths.map((p) => (
          <tr key={p.tag_hash}>
            <Td className="text-heading">{p.path.map((h) => h.name).join(" → ")} → server</Td>
            <Td className="text-ink">
              <span className="tabular-nums">{dollars(p.amount_cents)}</span> at {p.merchant}
              {p.simulated && <span className="text-secondary"> (simulated)</span>}
            </Td>
            <Td className="whitespace-nowrap text-secondary">
              {p.hops} {p.hops === 1 ? "hop" : "hops"}
            </Td>
            <Td num className="text-secondary">{Math.max(0, Math.round(p.latency_s / 60))} min</Td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

const METRICS: { key: keyof QuickResult; label: string; show: (v: number) => string; max: (a: number, b: number) => number }[] = [
  { key: "share_refused_offline", label: "Double spends refused offline", show: (v) => `${Math.round(v * 100)}%`, max: () => 1 },
  { key: "share_caught_at_settlement", label: "Caught at settlement", show: (v) => `${Math.round(v * 100)}%`, max: () => 1 },
  { key: "mean_loss_per_cheater_cents", label: "Pool loss per cheater", show: (v) => dollars(v), max: (a, b) => Math.max(a, b, 1) },
  { key: "median_hours_to_settlement", label: "Median hours to settlement", show: (v) => `${v.toFixed(1)} h`, max: (a, b) => Math.max(a, b, 0.1) },
];

function Bar({ value, max, color }: { value: number; max: number; color: string }) {
  return (
    <span className="flex items-center justify-end gap-3">
      <span className="h-1.5 w-32 overflow-hidden rounded-full bg-rule">
        <span className="block h-1.5 rounded-full transition-all duration-500"
          style={{ width: `${Math.min(100, (value / max) * 100)}%`, background: color }} />
      </span>
    </span>
  );
}

function Bars({ base, cur }: { base: QuickResult; cur: QuickResult }) {
  return (
    <Table>
      <thead>
        <tr>
          <Th>Metric</Th>
          <Th num>Default town</Th>
          <Th />
          <Th num>Your settings</Th>
          <Th />
        </tr>
      </thead>
      <tbody>
        {METRICS.map((m) => {
          const b = (base[m.key] as number | null) ?? 0;
          const c = (cur[m.key] as number | null) ?? 0;
          const max = m.max(b, c);
          return (
            <tr key={m.key}>
              <Td className="text-heading">{m.label}</Td>
              <Td num>{m.show(b)}</Td>
              <Td><Bar value={b} max={max} color={C.simulated} /></Td>
              <Td num className="font-medium text-heading">{m.show(c)}</Td>
              <Td><Bar value={c} max={max} color={C.real} /></Td>
            </tr>
          );
        })}
      </tbody>
    </Table>
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
      <span className="flex justify-between gap-3 text-ink">
        {label} <span className="font-medium tabular-nums text-heading">{show(value)}</span>
      </span>
      <input type="range" min={min} max={max} step={step} value={value}
        onChange={(e) => set(Number(e.target.value))} className="mt-1 w-full accent-accent" />
    </label>
  );

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <p className="max-w-[80ch] text-secondary">
          Simulated: a quick in-memory model of the town (5 seeded runs, {quick?.current.double_spend_attempts ?? "…"}{" "}
          double-spend attempts), not live data.
        </p>
        <span className="text-th text-secondary">
          {busy ? "re-simulating…" : quick ? `simulated in ${quick.seconds}s` : ""}
        </span>
      </div>
      <div className="grid gap-8 md:grid-cols-3">
        {slider("Adoption", adoption, setAdoption, 0.1, 1, 0.05, (v) => `${Math.round(v * 100)}%`)}
        {slider("Foot traffic (chance two phones meet)", pLink, setPLink, 0.05, 1, 0.05, (v) => v.toFixed(2))}
        {slider("Phones finding a signal (per hour)", pUplink, setPUplink, 0.005, 0.2, 0.005, (v) => v.toFixed(3))}
      </div>
      {error && <p className="text-danger">{error}</p>}
      {quick && <Bars base={quick.baseline} cur={quick.current} />}
    </div>
  );
}

const pct = (v: number | null) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`);

export function TownTab() {
  const [view, setView] = useState<View>("map");
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

  const simulated = town?.merchants.filter((m) => m.simulated).length ?? 0;
  const real = (town?.merchants.length ?? 0) - simulated;
  const s = town?.town_stats;
  const share = (v: number | null) => (v == null ? null : `${Math.round(v * 100)}%`);
  const takeaway = town && [
    `${simulated} simulated shops${real ? ` around ${real} real ${real === 1 ? "shop" : "shops"}` : ""}.`,
    s && share(s.double_spends.share_refused_offline) && share(s.double_spends.share_caught_at_settlement)
      ? `In the seeded town, ${share(s.double_spends.share_refused_offline)} of double spends were refused offline and ${
        share(s.double_spends.share_caught_at_settlement)} caught at settlement.`
      : null,
  ].filter(Boolean).join(" ");
  return (
    <div className="pb-12">
      <PageHeader title="Town"
        subtitle={town ? `${simulated} simulated shops in Buncombe County, NC, plus the real phones` : undefined}
        takeaway={takeaway || undefined}>
        <Tabs tabs={VIEWS} value={view} onChange={setView} />
      </PageHeader>
      {!town ? (
        <Note>Loading…</Note>
      ) : view === "map" ? (
        <div className="space-y-4">
          {s ? (
            <Strip items={[
              { label: "Refused offline", value: <span className="tabular-nums">{pct(s.double_spends.share_refused_offline)}</span> },
              { label: "Caught at settlement", value: <span className="tabular-nums">{pct(s.double_spends.share_caught_at_settlement)}</span> },
              { label: "Loss per cheater", value: <span className="tabular-nums">{s.mean_loss_per_cheater_cents == null ? "—" : dollars(s.mean_loss_per_cheater_cents)}</span> },
              { label: "Median to settlement", value: <span className="tabular-nums">{s.median_hours_to_settlement == null ? "—" : `${s.median_hours_to_settlement} h`}</span> },
              { label: "Double-spend attempts", value: <span className="tabular-nums">{s.double_spends.attempts}</span> },
              { label: "Data", value: <Pill tone="neutral">Simulated · seed {s.seed}</Pill> },
            ]} />
          ) : (
            <p className="border-y border-rule py-3 text-secondary">No seeded town stats yet.</p>
          )}
          <p className="text-secondary">
            Every shop but the real ones is <span className="font-medium text-heading">simulated</span>, checked by the
            same code as the phones.
          </p>
          <TownMap town={town} pulses={pulses} />
          <Legend />
          <div className="pt-6">
            <Section title="Recent relay paths">
              <RelayTable paths={paths.slice(0, 5)} />
            </Section>
          </div>
        </div>
      ) : view === "relay" ? (
        <RelayTable paths={paths} />
      ) : (
        <Sliders />
      )}
    </div>
  );
}
