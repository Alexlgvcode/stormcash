// Network (spec §18.4, §16.6): the simulated town (seed 42) around the real
// phones, as a network. Shops are nodes, recent relay paths are the links
// between them, areas show weather alerts and whether they've gone dark. Select
// a shop or an area for its side panel (a bottom sheet on narrow screens). Every
// simulated thing is labelled simulated; everything is read from /v1/town,
// /v1/relay/paths and /v1/cases.
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { getJSON, type CaseSummary, type Quick, type QuickResult, type RelayPath, type Town } from "../api";
import { caseTitle } from "../cases";
import { Icon } from "../components/Icon";
import { Note, PageHeader, Pill, Section, Source, Table, Tabs, Td, Th } from "../components/ui";
import { useEvents } from "../events";
import { clockTime, dollars } from "../format";
import { prefersReducedMotion } from "../live";
import { PAYMENT_STATUS } from "./Ledger";

const VIEWS = [
  { id: "map", label: "Network" },
  { id: "relay", label: "Relay paths" },
  { id: "whatif", label: "What-if" },
] as const;
type View = (typeof VIEWS)[number]["id"];

const CELL = 24;
// The map's own palette, the same tokens as the page (index.css).
const C = {
  page: "#101B2B",
  region: "#16253A",
  regionAlt: "#192A40",
  rule: "#2A3C52",
  hatch: "#2E4258",
  ink: "#F7F9FB",
  secondary: "#A3B2C4",
  sim: "#6F86A1",
  teal: "#13B8A6",
  amber: "#E8A23A",
  coral: "#DC5B55",
  accent: "#8CBCF0",
};

interface Pulse {
  id: number;
  x: number;
  y: number;
}

type Shop = Town["merchants"][number];
type Selection = { kind: "shop"; id: string } | { kind: "area"; id: string } | null;

/** One node per place: a real shop that registered twice (a reinstall) is still one shop. */
function nodesOf(town: Town): (Shop & { ids: string[] })[] {
  const out = new Map<string, Shop & { ids: string[] }>();
  for (const m of town.merchants) {
    const key = m.simulated ? m.merchant_id : `${m.display_name}@${m.x},${m.y}`;
    const cur = out.get(key);
    if (cur) cur.ids.push(m.merchant_id);
    else out.set(key, { ...m, ids: [m.merchant_id] });
  }
  return [...out.values()];
}

interface Leg {
  from: Shop;
  to: Shop;
  real: boolean;
  count: number;
}

/** Links between shops: consecutive shops on a payment's relay path, with how many paths used each. */
function legsOf(nodes: (Shop & { ids: string[] })[], paths: RelayPath[]): Leg[] {
  const byName = new Map(nodes.map((m) => [`${m.display_name}|${m.simulated}`, m]));
  const legs = new Map<string, Leg>();
  for (const p of paths) {
    const stops = p.path.filter((h) => h.kind === "merchant")
      .map((h) => byName.get(`${h.name}|${h.simulated !== false}`)).filter((m): m is Shop & { ids: string[] } => !!m);
    for (let i = 0; i + 1 < stops.length; i++) {
      if (stops[i] === stops[i + 1]) continue;
      const key = [stops[i].merchant_id, stops[i + 1].merchant_id].sort().join(">");
      const cur = legs.get(key);
      if (cur) cur.count++;
      else legs.set(key, { from: stops[i], to: stops[i + 1], real: !p.simulated, count: 1 });
    }
  }
  return [...legs.values()];
}

function TownMap({ town, nodes, legs, pulses, sel, onSelect }: {
  town: Town;
  nodes: (Shop & { ids: string[] })[];
  legs: Leg[];
  pulses: Pulse[];
  sel: Selection;
  onSelect: (s: Selection) => void;
}) {
  const { w, h } = town.grid;
  const W = w * CELL;
  const H = h * CELL;
  const alerts = new Map<string, Town["alerts"]>();
  for (const a of town.alerts) if (a.region_id) alerts.set(a.region_id, [...(alerts.get(a.region_id) ?? []), a]);
  const at = (m: Shop) => [(m.x + 0.5) * CELL, (m.y + 0.5) * CELL] as const;
  const selShop = sel?.kind === "shop" ? nodes.find((m) => m.merchant_id === sel.id) : undefined;
  const header = [...town.regions].sort((a, b) => a.x - b.x || a.y - b.y);
  // Keep labels and dots readable when the map is drawn small: k map units per screen pixel.
  const box = useRef<SVGSVGElement>(null);
  const [k, setK] = useState(1);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setK(el.clientWidth ? W / el.clientWidth : 1));
    ro.observe(el);
    return () => ro.disconnect();
  }, [W]);
  const font = Math.max(15, 12 * k);
  const grow = Math.min(1.8, Math.max(1, k * 0.75));
  return (
    <div className="min-w-0">
      {/* Area names, status and alerts above the map, where no shop covers them. Each is a button. */}
      <div className="mb-1.5 grid gap-1" style={{ gridTemplateColumns: header.filter((r) => r.y === 0).map((r) => `${r.w}fr`).join(" ") }}>
        {header.filter((r) => r.y === 0).map((r) => {
          const dark = town.dark_regions.includes(r.region_id);
          const on = sel?.kind === "area" && sel.id === r.region_id;
          const al = alerts.get(r.region_id) ?? [];
          return (
            <button key={r.region_id} onClick={() => onSelect(on ? null : { kind: "area", id: r.region_id })} aria-pressed={on}
              className={`min-h-11 min-w-0 rounded-[8px] border px-2 py-1 text-left ${on ? "border-accent bg-accent-tint" : "border-transparent hover:bg-surface"}`}>
              <div className="truncate text-th font-semibold text-heading sm:text-ui">{r.display_name}</div>
              <div className="flex flex-wrap gap-x-2 text-[11px] leading-4 sm:text-th">
                {dark && <span className="text-warning">dark</span>}
                {al.length > 0 && <span className="truncate text-warning">⚠ {al[0].event}{al.length > 1 ? ` +${al.length - 1}` : ""}</span>}
                {!dark && al.length === 0 && <span className="text-secondary">uploading</span>}
              </div>
            </button>
          );
        })}
      </div>
      <svg ref={box} viewBox={`0 0 ${W} ${H}`} className="block h-auto w-full touch-manipulation select-none" role="group"
        aria-label="Network of shops in the simulated town and the real phones">
        <defs>
          <pattern id="hatch" width="12" height="12" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="12" stroke={C.hatch} strokeWidth="4" />
          </pattern>
          <clipPath id="town-clip">
            <rect width={W} height={H} rx="10" />
          </clipPath>
        </defs>
        <g clipPath="url(#town-clip)">
          {town.regions.map((r, i) => {
            const dark = town.dark_regions.includes(r.region_id);
            const on = sel?.kind === "area" && sel.id === r.region_id;
            const alerted = (alerts.get(r.region_id) ?? []).length > 0;
            return (
              <g key={r.region_id} onClick={() => onSelect(on ? null : { kind: "area", id: r.region_id })} className="cursor-pointer">
                <rect x={r.x * CELL} y={r.y * CELL} width={r.w * CELL} height={r.h * CELL}
                  fill={i % 2 ? C.regionAlt : C.region} stroke={C.page} strokeWidth="3" />
                {dark && <rect x={r.x * CELL} y={r.y * CELL} width={r.w * CELL} height={r.h * CELL} fill="url(#hatch)" />}
                {(alerted || on) && (
                  <rect x={r.x * CELL + 3} y={r.y * CELL + 3} width={r.w * CELL - 6} height={r.h * CELL - 6} rx="6" fill="none"
                    stroke={on ? C.accent : C.amber} strokeOpacity={on ? 1 : 0.55} strokeWidth="2" strokeDasharray={on ? undefined : "6 6"} />
                )}
              </g>
            );
          })}
          {legs.map((l) => {
            const [x1, y1] = at(l.from);
            const [x2, y2] = at(l.to);
            const hot = !!selShop && (l.from.merchant_id === selShop.merchant_id || l.to.merchant_id === selShop.merchant_id);
            const bend = Math.min(36, Math.hypot(x2 - x1, y2 - y1) / 5);
            return (
              <path key={`${l.from.merchant_id}>${l.to.merchant_id}`}
                d={`M ${x1} ${y1} Q ${(x1 + x2) / 2} ${(y1 + y2) / 2 - bend} ${x2} ${y2}`} fill="none" pointerEvents="none"
                stroke={l.real ? C.teal : hot ? C.accent : C.sim} strokeOpacity={hot || l.real ? 0.95 : selShop ? 0.12 : 0.35}
                strokeWidth={hot || l.real ? 2.5 : 1.25 + Math.min(1.5, l.count / 3)} strokeDasharray={l.real ? undefined : "5 5"} />
            );
          })}
          {pulses.map((p) => (
            <circle key={p.id} cx={(p.x + 0.5) * CELL} cy={(p.y + 0.5) * CELL} r="6" fill="none" stroke={C.teal} strokeWidth="3"
              pointerEvents="none">
              <animate attributeName="r" from="6" to="34" dur="1.6s" fill="freeze" />
              <animate attributeName="opacity" from="1" to="0" dur="1.6s" fill="freeze" />
            </circle>
          ))}
          {nodes.map((m) => {
            const [cx, cy] = at(m);
            const held = !m.pool_eligible;
            const on = selShop?.merchant_id === m.merchant_id;
            const r = (m.simulated ? (held ? 7 : 5.5) : 10) * grow;
            return (
              <g key={m.merchant_id} role="button" tabIndex={0} aria-pressed={on}
                aria-label={`${m.display_name}${m.simulated ? ", simulated" : ", real phone"}${held ? ", pool payouts held" : ""}`}
                onClick={(e) => {
                  e.stopPropagation();
                  onSelect(on ? null : { kind: "shop", id: m.merchant_id });
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onSelect(on ? null : { kind: "shop", id: m.merchant_id });
                  }
                }}
                className="cursor-pointer outline-none [&:focus-visible>.ring]:stroke-accent">
                <circle cx={cx} cy={cy} r={22 * Math.max(1, k * 0.9)} fill="transparent" />
                <circle className="ring" cx={cx} cy={cy} r={r + 5} fill="none" stroke={on ? C.accent : "transparent"} strokeWidth="2.5" />
                {m.simulated ? (
                  <circle cx={cx} cy={cy} r={r} fill={held ? C.coral : C.sim} stroke={C.page} strokeWidth="1.5" />
                ) : (
                  <>
                    <circle cx={cx} cy={cy} r={r} fill={C.page} stroke={C.teal} strokeWidth="3" />
                    <circle cx={cx} cy={cy} r={3.5 * grow} fill={C.teal} />
                  </>
                )}
              </g>
            );
          })}
          {nodes.filter((m) => !m.simulated || !m.pool_eligible || m.merchant_id === selShop?.merchant_id).map((m) => {
            const [cx, cy] = at(m);
            const left = cx > W - 14 * font;
            return (
              <text key={m.merchant_id} x={left ? cx - 15 * grow : cx + 15 * grow} y={cy + font / 3} textAnchor={left ? "end" : "start"} pointerEvents="none"
                fill={!m.simulated ? C.ink : m.pool_eligible ? C.ink : C.coral} fontSize={font} fontWeight="600"
                stroke={C.page} strokeWidth={font / 3} paintOrder="stroke">
                {m.display_name}{m.simulated ? "" : " · real"}
              </text>
            );
          })}
        </g>
      </svg>
    </div>
  );
}

function Legend() {
  const dot = (bg: string, size: number, ring?: string) => (
    <span className="inline-block shrink-0 rounded-full" style={{ background: bg, width: size, height: size, boxShadow: ring ? `0 0 0 2.5px ${ring}` : undefined }} />
  );
  return (
    <div className="flex flex-wrap gap-x-5 gap-y-1.5 py-2 text-th text-secondary">
      <span className="flex items-center gap-2">{dot(C.page, 12, C.teal)} real shop (a phone)</span>
      <span className="flex items-center gap-2">{dot(C.sim, 9)} simulated shop</span>
      <span className="flex items-center gap-2">{dot(C.coral, 11)} pool payouts held</span>
      <span className="flex items-center gap-2"><span className="inline-block w-6 border-t-2 border-dashed" style={{ borderColor: C.sim }} /> simulated relay</span>
      <span className="flex items-center gap-2"><span className="inline-block w-6 border-t-2" style={{ borderColor: C.teal }} /> real relay</span>
      <span className="flex items-center gap-2">
        <span className="inline-block h-3 w-5 rounded-sm" style={{ background: `repeating-linear-gradient(45deg, ${C.hatch} 0 3px, ${C.region} 3px 7px)` }} />
        dark area (no uploads)
      </span>
      <span className="flex items-center gap-2"><span className="text-warning">⚠</span> weather alert</span>
    </div>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[7.5rem_minmax(0,1fr)] gap-3 border-b border-rule py-2 text-ui">
      <span className="text-secondary">{label}</span>
      <span className="min-w-0 break-words text-ink">{children}</span>
    </div>
  );
}

function PanelHead({ eyebrow, title, badge, onClose }: { eyebrow: string; title: string; badge?: ReactNode; onClose?: () => void }) {
  return (
    <div className="mb-2 flex items-start justify-between gap-3">
      <div className="min-w-0">
        <div className="text-eyebrow font-semibold uppercase text-secondary">{eyebrow}</div>
        <div className="mt-0.5 flex flex-wrap items-center gap-2">
          <h2 className="text-section font-semibold text-heading">{title}</h2>
          {badge}
        </div>
      </div>
      {onClose && (
        <button onClick={onClose} aria-label="Close" className="-mr-2 flex h-11 w-11 shrink-0 items-center justify-center rounded-button text-secondary hover:bg-raised hover:text-heading">
          <Icon name="close" size={20} />
        </button>
      )}
    </div>
  );
}

function ShopPanel({ town, shop, paths, cases, onClose, onSelect }: {
  town: Town;
  shop: Shop & { ids: string[] };
  paths: RelayPath[];
  cases: CaseSummary[];
  onClose: () => void;
  onSelect: (s: Selection) => void;
}) {
  const ids = new Set(shop.ids);
  const pays = town.recent_payments.filter((p) => ids.has(p.merchant_id));
  const byStatus = new Map<string, { n: number; cents: number }>();
  for (const p of pays) {
    const cur = byStatus.get(p.status) ?? { n: 0, cents: 0 };
    byStatus.set(p.status, { n: cur.n + 1, cents: cur.cents + p.amount_cents });
  }
  const through = paths.filter((p) => p.simulated === shop.simulated
    && p.path.some((h) => h.kind === "merchant" && h.name === shop.display_name));
  const area = town.regions.find((r) => r.region_id === shop.region_id);
  const involved = cases.filter((c) => !!c.simulated === shop.simulated
    && [c.payment_a?.merchant, c.payment_b?.merchant, c.merchant].includes(shop.display_name));
  return (
    <div>
      <PanelHead eyebrow={shop.simulated ? "Simulated shop" : "Real shop · a registered phone"} title={shop.display_name}
        badge={<Source kind={shop.simulated ? "simulated" : "real"} />} onClose={onClose} />
      <Fact label="Area">
        {area ? <button className="text-accent hover:underline" onClick={() => onSelect({ kind: "area", id: area.region_id })}>{area.display_name}</button> : "—"}
      </Fact>
      <Fact label="Guarantee pool">
        {shop.pool_eligible ? <Pill tone="success">Eligible</Pill> : <Pill tone="danger">Payouts held</Pill>}
      </Fact>
      {shop.ids.length > 1 && <Fact label="Registrations">{shop.ids.length} (the phone registered again)</Fact>}
      <Fact label="Payments">
        {pays.length === 0 ? <span className="text-secondary">none in the latest 200</span> : (
          <ul className="space-y-1">
            {[...byStatus.entries()].map(([s, v]) => (
              <li key={s} className="flex flex-wrap items-center justify-between gap-2">
                <Pill tone={PAYMENT_STATUS[s]?.tone ?? "neutral"}>{PAYMENT_STATUS[s]?.text ?? s}</Pill>
                <span className="tabular-nums">{v.n} · {dollars(v.cents)}</span>
              </li>
            ))}
          </ul>
        )}
      </Fact>
      <Fact label="Relay paths">
        {through.length === 0 ? <span className="text-secondary">none recently</span> : (
          <ul className="space-y-1.5">
            {through.slice(0, 4).map((p) => (
              <li key={p.tag_hash} className="text-th">
                <span className="text-ink">{p.path.map((h) => h.name).join(" → ")} → server</span>
                <span className="block text-secondary tabular-nums">
                  {dollars(p.amount_cents)} · {p.hops} {p.hops === 1 ? "hop" : "hops"} · {Math.max(0, Math.round(p.latency_s / 60))} min to the server
                </span>
              </li>
            ))}
            {through.length > 4 && <li className="text-th text-secondary">and {through.length - 4} more</li>}
          </ul>
        )}
      </Fact>
      <Fact label="Proven cases">
        {involved.length === 0 ? <span className="text-secondary">none</span> : (
          <ul className="space-y-1">
            {involved.slice(0, 4).map((c) => (
              <li key={c.case_id}><a href="#cases" className="text-th text-accent hover:underline">#{c.case_id} · {caseTitle(c)}</a></li>
            ))}
            {involved.length > 4 && <li className="text-th text-secondary">and {involved.length - 4} more</li>}
          </ul>
        )}
      </Fact>
    </div>
  );
}

function AreaPanel({ town, id, nodes, onClose, onSelect }: {
  town: Town;
  id: string;
  nodes: (Shop & { ids: string[] })[];
  onClose: () => void;
  onSelect: (s: Selection) => void;
}) {
  const r = town.regions.find((x) => x.region_id === id);
  if (!r) return null;
  const shops = nodes.filter((m) => m.region_id === id);
  const ups = town.uploads.filter((u) => u.region_id === id);
  const realUps = ups.filter((u) => !u.simulated);
  const al = town.alerts.filter((a) => a.region_id === id);
  const dark = town.dark_regions.includes(id);
  return (
    <div>
      <PanelHead eyebrow={`Area · ${(r as { county?: string }).county ?? ""} County`} title={r.display_name} onClose={onClose} />
      <Fact label="Coverage">
        {dark ? <Pill tone="warning">Dark: no uploads recently</Pill> : <Pill tone="success">Uploading</Pill>}
      </Fact>
      <Fact label="Weather">
        {al.length === 0 ? <span className="text-secondary">no active alerts</span> : (
          <ul className="space-y-1">
            {al.map((a) => (
              <li key={a.alert_id} className="flex flex-wrap items-center gap-2">
                <span className="text-warning">⚠ {a.event}</span>
                {a.severity && <span className="text-th text-secondary">{a.severity}</span>}
                <Source kind={a.source === "live" ? "real" : "replayed"} />
              </li>
            ))}
          </ul>
        )}
      </Fact>
      <Fact label="Uploads">
        {ups.length === 0 ? <span className="text-secondary">none in the latest 100</span> : (
          <span className="tabular-nums">
            {ups.length} in the latest 100 · {realUps.length} from real phones
            {ups[0] && <span className="block text-th text-secondary">last {clockTime(ups[0].at)}</span>}
          </span>
        )}
      </Fact>
      <Fact label={`Shops (${shops.length})`}>
        <ul className="-mx-1 grid grid-cols-1 gap-0.5 sm:grid-cols-2 lg:grid-cols-1">
          {shops.map((m) => (
            <li key={m.merchant_id}>
              <button onClick={() => onSelect({ kind: "shop", id: m.merchant_id })}
                className="flex min-h-9 w-full items-center gap-2 rounded px-1 text-left text-th hover:bg-raised pointer-coarse:min-h-11">
                <span className="inline-block h-2 w-2 shrink-0 rounded-full"
                  style={{ background: !m.simulated ? C.teal : m.pool_eligible ? C.sim : C.coral }} />
                <span className="truncate text-ink">{m.display_name}</span>
              </button>
            </li>
          ))}
        </ul>
      </Fact>
    </div>
  );
}

/** With nothing selected: the real phones, then each area at a glance. */
function NetworkSummary({ town, nodes, paths, onSelect }: {
  town: Town;
  nodes: (Shop & { ids: string[] })[];
  paths: RelayPath[];
  onSelect: (s: Selection) => void;
}) {
  const phones = new Map<string, { name: string; kind: string; at: number; carried: number }>();
  for (const p of paths) {
    for (const h of p.path) {
      if (h.simulated !== false) continue;
      const cur = phones.get(h.device) ?? { name: h.name, kind: h.kind, at: 0, carried: 0 };
      phones.set(h.device, { ...cur, at: Math.max(cur.at, h.at), carried: cur.carried + 1 });
    }
  }
  const real = nodes.filter((m) => !m.simulated);
  return (
    <div>
      <PanelHead eyebrow="Network" title="Real phones" badge={<Source kind="real" />} />
      {phones.size === 0 ? (
        <p className="border-b border-rule py-2 text-secondary">No relay paths from real phones yet.</p>
      ) : (
        <ul>
          {[...phones.entries()].map(([dev, p]) => (
            <li key={dev} className="grid grid-cols-[minmax(0,1fr)_auto] gap-3 border-b border-rule py-2">
              <span className="min-w-0">
                <span className="block truncate text-heading">{p.name}</span>
                <span className="block font-mono text-th text-secondary">{dev} · {p.kind === "merchant" ? "shop" : "resident"}</span>
              </span>
              <span className="text-right text-th tabular-nums text-secondary">
                on {p.carried} {p.carried === 1 ? "path" : "paths"}
                <span className="block">last {clockTime(p.at)}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
      {real.length > 0 && (
        <p className="py-2 text-th text-secondary">
          {real.length} real {real.length === 1 ? "shop is" : "shops are"} on the map:{" "}
          {real.map((m, i) => (
            <span key={m.merchant_id}>{i > 0 && ", "}
              <button className="text-accent hover:underline" onClick={() => onSelect({ kind: "shop", id: m.merchant_id })}>{m.display_name}</button>
            </span>
          ))}. Residents' phones have no place on the map, so every real phone is listed above.
        </p>
      )}
      <div className="mt-4 text-eyebrow font-semibold uppercase text-secondary">Areas</div>
      <ul className="mt-1">
        {[...town.regions].sort((a, b) => a.x - b.x).map((r) => {
          const dark = town.dark_regions.includes(r.region_id);
          const al = town.alerts.filter((a) => a.region_id === r.region_id);
          const n = nodes.filter((m) => m.region_id === r.region_id).length;
          return (
            <li key={r.region_id}>
              <button onClick={() => onSelect({ kind: "area", id: r.region_id })}
                className="grid min-h-11 w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-3 border-b border-rule py-1.5 text-left hover:bg-raised/50">
                <span className="truncate text-ink">{r.display_name}</span>
                <span className="flex items-center gap-2 text-th text-secondary">
                  {al.length > 0 && <span className="text-warning">⚠ {al.length}</span>}
                  {dark ? <span className="text-warning">dark</span> : <span>uploading</span>}
                  <span className="tabular-nums">{n} shops</span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
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
          <Th className="max-sm:hidden">Hops</Th>
          <Th num>To the server</Th>
        </tr>
      </thead>
      <tbody>
        {paths.map((p) => (
          <tr key={p.tag_hash}>
            <Td className="text-heading">{p.path.map((h) => h.name).join(" → ")} → server</Td>
            <Td className="text-ink">
              <span className="tabular-nums">{dollars(p.amount_cents)}</span> at {p.merchant}
              {" "}<Source kind={p.simulated ? "simulated" : "real"} />
            </Td>
            <Td className="whitespace-nowrap text-secondary max-sm:hidden">
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
              <Td><Bar value={b} max={max} color="#6F86A1" /></Td>
              <Td num className="font-medium text-heading">{m.show(c)}</Td>
              <Td><Bar value={c} max={max} color="#13B8A6" /></Td>
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

const pct = (v: number | null | undefined) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`);

function SimStats({ s }: { s: NonNullable<Town["town_stats"]> }) {
  const items: [string, ReactNode][] = [
    ["Double-spend attempts", s.double_spends.attempts],
    ["Refused offline", pct(s.double_spends.share_refused_offline)],
    ["Caught at settlement", pct(s.double_spends.share_caught_at_settlement)],
    ["Pool loss per cheater", s.mean_loss_per_cheater_cents == null ? "—" : dollars(s.mean_loss_per_cheater_cents)],
    ["Median to settlement", s.median_hours_to_settlement == null ? "—" : `${s.median_hours_to_settlement} h`],
    ["Payments", s.summary?.payments?.toLocaleString("en-US") ?? "—"],
  ];
  return (
    <div className="mb-5 overflow-hidden rounded-[10px] border border-rule bg-surface">
      <div className="flex flex-wrap items-center gap-2 border-b border-rule px-4 py-2 text-th text-secondary">
        <Source kind="simulated" />
        <span>Seeded run, seed {s.seed}{s.summary?.hours ? `, ${s.summary.hours} h` : ""}{s.summary?.residents ? `, ${s.summary.residents} residents` : ""}{s.summary?.shops ? `, ${s.summary.shops} shops` : ""}. Checked by the same code as the phones.</span>
      </div>
      <dl className="grid grid-cols-2 gap-px bg-rule sm:grid-cols-3 xl:grid-cols-6">
        {items.map(([k, v]) => (
          <div key={k} className="bg-surface px-4 py-2.5">
            <dt className="text-th text-secondary">{k}</dt>
            <dd className="text-[19px] leading-7 font-semibold tabular-nums text-heading">{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export function TownTab() {
  const [view, setView] = useState<View>("map");
  const [town, setTown] = useState<Town | null>(null);
  const [paths, setPaths] = useState<RelayPath[]>([]);
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [pulses, setPulses] = useState<Pulse[]>([]);
  const [sel, setSel] = useState<Selection>(null);
  const [error, setError] = useState<string | null>(null);
  const pulseId = useRef(0);

  const load = useCallback(() => {
    getJSON<Town>("/v1/town").then((t) => {
      setTown(t);
      setError(null);
    }).catch((e) => setError(String(e)));
    getJSON<RelayPath[]>("/v1/relay/paths?limit=200").then(setPaths).catch(() => undefined);
    getJSON<CaseSummary[]>("/v1/cases?limit=200").then(setCases).catch(() => undefined);
  }, []);
  useEffect(load, [load]);
  useEvents(["town", "candidate", "upload", "case_opened"], load);
  useEvents(["payment"], (data) => {
    if (prefersReducedMotion()) return;
    const p = data as { merchant_id: string };
    const m = town?.merchants.find((x) => x.merchant_id === p.merchant_id);
    if (!m) return;
    const id = ++pulseId.current;
    setPulses((cur) => [...cur, { id, x: m.x, y: m.y }]);
    setTimeout(() => setPulses((cur) => cur.filter((q) => q.id !== id)), 1800);
  });
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setSel(null);
    addEventListener("keydown", esc);
    return () => removeEventListener("keydown", esc);
  }, []);

  const nodes = useMemo(() => (town ? nodesOf(town) : []), [town]);
  const legs = useMemo(() => legsOf(nodes, paths), [nodes, paths]);
  const shop = sel?.kind === "shop" ? nodes.find((m) => m.merchant_id === sel.id) : undefined;
  const simulated = nodes.filter((m) => m.simulated).length;
  const real = nodes.length - simulated;

  const panel = !town ? null : shop ? (
    <ShopPanel town={town} shop={shop} paths={paths} cases={cases} onClose={() => setSel(null)} onSelect={setSel} />
  ) : sel?.kind === "area" ? (
    <AreaPanel town={town} id={sel.id} nodes={nodes} onClose={() => setSel(null)} onSelect={setSel} />
  ) : null;

  return (
    <div>
      <PageHeader title="Network"
        subtitle={town ? `${simulated} simulated shops in Buncombe County, NC, around ${real} real ${real === 1 ? "shop" : "shops"}, linked by the phones that carried payments` : undefined}>
        <Tabs tabs={VIEWS} value={view} onChange={setView} />
      </PageHeader>
      {!town ? (
        <Note tone={error ? "danger" : "neutral"}>{error ? `Can't reach the server: ${error}` : "Loading…"}</Note>
      ) : view === "map" ? (
        <>
          {town.town_stats ? <SimStats s={town.town_stats} /> : <p className="mb-5 text-secondary">No seeded town stats on this server yet.</p>}
          <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem] xl:grid-cols-[minmax(0,1fr)_24rem]">
            <div className="min-w-0">
              <TownMap town={town} nodes={nodes} legs={legs} pulses={pulses} sel={sel} onSelect={setSel} />
              <Legend />
              <p className="text-th text-secondary">
                Links are the last {paths.length} relay paths: shops a payment passed through on its way to the server.
                Select a shop or an area for details.
              </p>
            </div>
            {/* Wide: a side panel. Narrow: the summary below the map, the selection in a bottom sheet. */}
            <aside className="hidden min-w-0 self-start rounded-[10px] border border-rule bg-surface p-4 lg:sticky lg:top-20 lg:block lg:max-h-[calc(100vh-6rem)] lg:overflow-y-auto">
              {panel ?? <NetworkSummary town={town} nodes={nodes} paths={paths} onSelect={setSel} />}
            </aside>
            <div className="min-w-0 lg:hidden">
              <NetworkSummary town={town} nodes={nodes} paths={paths} onSelect={setSel} />
            </div>
          </div>
          {panel && (
            <div role="dialog" aria-modal="false" aria-label="Selection details"
              className="fixed inset-x-0 bottom-14 z-20 max-h-[55vh] overflow-y-auto rounded-t-[14px] border-t border-rule bg-surface px-4 pt-2 pb-4 shadow-[0_-8px_24px_rgba(0,0,0,0.35)] lg:hidden">
              <div className="mx-auto mb-2 h-1 w-10 rounded-full bg-rule" />
              <div className="mx-auto max-w-[720px]">{panel}</div>
            </div>
          )}
          <div className="pt-8">
            <Section title="Recent relay paths">
              <RelayTable paths={paths.slice(0, 6)} />
            </Section>
          </div>
        </>
      ) : view === "relay" ? (
        <RelayTable paths={paths} />
      ) : (
        <Sliders />
      )}
    </div>
  );
}
