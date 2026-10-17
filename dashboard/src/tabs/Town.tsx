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
// The map in the bank style of the "Capital One" mockup: deep navy text, bank blue
// for real shops, a soft blue tint, rounded corners. No logo or brand red.
const B = {
  navy: "#0B3B5C",
  blue: "#0B5D8C",
  tint: "#E6F0F6",
  grey: "#F4F5F7",
  hatch: "#D9D9D9",
  red: "#B0261B",
  warn: "#9A5300",
  ok: "#1E6B35",
  sim: "#9A9A9A",
};

interface Pulse {
  id: number;
  x: number;
  y: number;
}

type Shop = Town["merchants"][number];

/** Relay legs between shops on the map, from the latest uploads that real phones carried (the town's own would be noise). */
function relayLegs(town: Town, paths: RelayPath[]): [Shop, Shop][] {
  const byName = new Map(town.merchants.map((m) => [m.display_name, m]));
  const seen = new Set<string>();
  const legs: [Shop, Shop][] = [];
  for (const p of paths.slice(0, 10)) {
    if (p.path.every((hop) => hop.simulated !== false)) continue;
    const stops = p.path.filter((hop) => hop.kind === "merchant").map((hop) => byName.get(hop.name))
      .filter((m): m is Shop => !!m);
    for (let i = 0; i + 1 < stops.length; i++) {
      const key = `${stops[i].merchant_id}>${stops[i + 1].merchant_id}`;
      if (stops[i] === stops[i + 1] || seen.has(key)) continue;
      seen.add(key);
      legs.push([stops[i], stops[i + 1]]);
    }
  }
  return legs;
}

function TownMap({ town, pulses, paths }: { town: Town; pulses: Pulse[]; paths: RelayPath[] }) {
  const { w, h } = town.grid;
  const W = w * CELL;
  const H = h * CELL;
  const alertsByRegion = new Map<string, Town["alerts"]>();
  for (const a of town.alerts) {
    if (a.region_id) alertsByRegion.set(a.region_id, [...(alertsByRegion.get(a.region_id) ?? []), a]);
  }
  // Areas along the top edge get their name, status and alerts in a header row above the map,
  // where no shop can cover them; any other area is labelled inside.
  const header = town.regions.filter((r) => r.y === 0).sort((x, y) => x.x - y.x);
  const inside = town.regions.filter((r) => r.y !== 0);
  const at = (m: Shop) => [(m.x + 0.5) * CELL, (m.y + 0.5) * CELL] as const;
  const labelled = town.merchants.filter((m) => !m.simulated || !m.pool_eligible);
  return (
    <div className="w-full max-w-3xl">
      <div className="mb-2 grid" style={{ gridTemplateColumns: header.map((r) => `${r.w}fr`).join(" ") }}>
        {header.map((r) => {
          const dark = town.dark_regions.includes(r.region_id);
          return (
            <div key={r.region_id} className="min-w-0 px-2">
              <div className="font-semibold leading-snug" style={{ color: B.navy }}>{r.display_name}</div>
              {dark && <div className="text-th" style={{ color: B.warn }}>Dark: no uploads</div>}
              {(alertsByRegion.get(r.region_id) ?? []).map((a) => (
                <div key={a.alert_id} className="text-th" style={{ color: B.warn }}>⚠ {a.event} ({a.source})</div>
              ))}
            </div>
          );
        })}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="block w-full" role="img" aria-label="Map of the simulated town">
        <defs>
          <pattern id="hatch" width="10" height="10" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="10" stroke={B.hatch} strokeWidth="3" />
          </pattern>
          <clipPath id="town-clip">
            <rect width={W} height={H} rx="16" />
          </clipPath>
        </defs>
        <g clipPath="url(#town-clip)">
          {town.regions.map((r, i) => {
            const dark = town.dark_regions.includes(r.region_id);
            return (
              <g key={r.region_id}>
                <rect x={r.x * CELL} y={r.y * CELL} width={r.w * CELL} height={r.h * CELL}
                  fill={dark || i % 2 ? B.grey : B.tint} stroke="#FFFFFF" strokeWidth="4" />
                {dark && <rect x={r.x * CELL} y={r.y * CELL} width={r.w * CELL} height={r.h * CELL} fill="url(#hatch)" />}
              </g>
            );
          })}
          {inside.map((r) => (
            <text key={r.region_id} x={r.x * CELL + 10} y={r.y * CELL + 26} fill={B.navy} fontSize="18" fontWeight="600"
              stroke="#FFFFFF" strokeWidth="5" paintOrder="stroke">
              {r.display_name}
              {town.dark_regions.includes(r.region_id) ? " · dark" : ""}
            </text>
          ))}
          {relayLegs(town, paths).map(([from, to]) => {
            const [x1, y1] = at(from);
            const [x2, y2] = at(to);
            return (
              <path key={`${from.merchant_id}>${to.merchant_id}`}
                d={`M ${x1} ${y1} Q ${(x1 + x2) / 2} ${Math.min(y1, y2) - Math.min(40, Math.hypot(x2 - x1, y2 - y1) / 4)} ${x2} ${y2}`}
                fill="none" stroke={B.blue} strokeWidth="3" strokeDasharray="6 5" />
            );
          })}
          {town.merchants.map((m) => {
            const [cx, cy] = at(m);
            const held = m.simulated && !m.pool_eligible;
            return (
              <circle key={m.merchant_id} cx={cx} cy={cy} r={m.simulated ? (held ? 8 : 6) : 11}
                fill={m.simulated ? (held ? B.red : B.sim) : B.blue} stroke="#FFFFFF" strokeWidth="2">
                <title>
                  {m.display_name}
                  {m.simulated ? " (simulated)" : ""}
                  {m.pool_eligible ? "" : " · pool payouts held"}
                </title>
              </circle>
            );
          })}
          {pulses.map((p) => (
            <circle key={p.id} cx={(p.x + 0.5) * CELL} cy={(p.y + 0.5) * CELL} r="6" fill="none" stroke={B.ok}
              strokeWidth="3">
              <animate attributeName="r" from="6" to="34" dur="1.6s" fill="freeze" />
              <animate attributeName="opacity" from="1" to="0" dur="1.6s" fill="freeze" />
            </circle>
          ))}
          {/* Labels last, over every dot, with a white halo; near the right edge they read leftwards. */}
          {labelled.map((m) => {
            const [cx, cy] = at(m);
            const left = cx > W - 230;
            return (
              <text key={m.merchant_id} x={left ? cx - 14 : cx + 14} y={cy + 6} textAnchor={left ? "end" : "start"}
                fill={m.simulated ? B.red : B.navy} fontSize="18" fontWeight="600" stroke="#FFFFFF" strokeWidth="6"
                paintOrder="stroke">
                {m.display_name}
              </text>
            );
          })}
        </g>
      </svg>
    </div>
  );
}

function Legend() {
  const dot = (color: string, size: number) => (
    <span className="inline-block shrink-0 rounded-full" style={{ background: color, width: size, height: size }} />
  );
  return (
    <div className="flex max-w-3xl flex-wrap gap-x-6 gap-y-2 py-3 text-th text-secondary">
      <span className="flex items-center gap-2">{dot(B.blue, 13)} real shop (a phone)</span>
      <span className="flex items-center gap-2">{dot(B.sim, 9)} simulated shop</span>
      <span className="flex items-center gap-2">{dot(B.red, 11)} simulated, pool payouts held</span>
      <span className="flex items-center gap-2">
        <span className="inline-block h-3 w-5 rounded-sm"
          style={{ background: `repeating-linear-gradient(45deg, ${B.hatch} 0 3px, ${B.grey} 3px 7px)` }} />
        dark area (no uploads)
      </span>
      <span className="flex items-center gap-2">
        <span className="inline-block w-6 border-t-2 border-dashed" style={{ borderColor: B.blue }} /> recent relay
      </span>
      <span className="flex items-center gap-2">
        <span className="inline-block h-3 w-3 rounded-full border-2" style={{ borderColor: B.ok }} /> payment
      </span>
      <span className="flex items-center gap-2"><span style={{ color: B.warn }}>⚠</span> weather alert (live or replayed)</span>
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
              <Td><Bar value={b} max={max} color="#9AA3AF" /></Td>
              <Td num className="font-medium text-heading">{m.show(c)}</Td>
              <Td><Bar value={c} max={max} color="#2B3A9E" /></Td>
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
          <TownMap town={town} pulses={pulses} paths={paths} />
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
