// Ledger workspace: the transaction explorer (every payment the server holds,
// real and simulated, with filters), then #124's Balances, Reconciliation and
// Nessie log views. Rows are the server's own; nothing is computed but sums.
import { useMemo, useState } from "react";
import type { RelayPath, Town } from "../api";
import { CopyId, Note, PageHeader, Pill, Select, Source, Tabs, TextInput, type Tone } from "../components/ui";
import { clockTime, dollars } from "../format";
import { useLive } from "../live";
import { AccountsTab, type AccountsView } from "./Accounts";

const VIEWS = [
  { id: "transactions", label: "Transactions" },
  { id: "balances", label: "Balances" },
  { id: "reconciliation", label: "Reconciliation" },
  { id: "log", label: "Nessie log" },
] as const;
type View = (typeof VIEWS)[number]["id"];

// payments.status (schema.sql) in words and state colors.
export const PAYMENT_STATUS: Record<string, { text: string; tone: Tone }> = {
  pending: { text: "Uploaded, unsettled", tone: "warning" },
  held: { text: "Held", tone: "warning" },
  settled: { text: "Settled", tone: "success" },
  refused_evidence: { text: "Refused offline", tone: "danger" },
  denied_knowing: { text: "Denied: shop knew", tone: "danger" },
  invalid: { text: "Invalid", tone: "danger" },
};

interface Row {
  tag: string;
  shop: string;
  simulated: boolean;
  amount: number;
  status: string;
  paidAt: number;
  hops: number | null;
  uploadedBy: string | null;
  latency: number | null;
  path: string | null;
}

function rows(town: Town, paths: RelayPath[]): Row[] {
  const shops = new Map(town.merchants.map((m) => [m.merchant_id, m]));
  const byTag = new Map(paths.map((p) => [p.tag_hash, p]));
  const out = new Map<string, Row>();
  for (const p of town.recent_payments) {
    const m = shops.get(p.merchant_id);
    const r = byTag.get(p.tag_hash);
    out.set(p.tag_hash, {
      tag: p.tag_hash, shop: m?.display_name ?? r?.merchant ?? "Unknown shop", simulated: m?.simulated ?? r?.simulated ?? true,
      amount: p.amount_cents, status: p.status, paidAt: p.device_ts, hops: p.hops,
      uploadedBy: r?.uploaded_by ?? null, latency: r ? r.latency_s : null,
      path: r ? `${r.path.map((h) => h.name).join(" → ")} → server` : null,
    });
  }
  for (const r of paths) {
    if (out.has(r.tag_hash)) continue;
    out.set(r.tag_hash, {
      tag: r.tag_hash, shop: r.merchant, simulated: r.simulated, amount: r.amount_cents, status: r.status,
      paidAt: r.paid_at ?? r.received_at ?? 0, hops: r.hops, uploadedBy: r.uploaded_by, latency: r.latency_s,
      path: `${r.path.map((h) => h.name).join(" → ")} → server`,
    });
  }
  return [...out.values()].sort((a, b) => b.paidAt - a.paidAt);
}

const minutes = (s: number | null) => (s == null ? "—" : s < 90 ? `${Math.max(0, s)} s` : s < 5400 ? `${Math.round(s / 60)} min` : `${(s / 3600).toFixed(1)} h`);

function Transactions() {
  const town = useLive<Town>("/v1/town", ["town", "upload", "payment"]);
  const paths = useLive<RelayPath[]>("/v1/relay/paths?limit=200", ["town", "upload", "payment"]);
  const [source, setSource] = useState("all");
  const [status, setStatus] = useState("all");
  const [q, setQ] = useState("");
  const all = useMemo(() => (town.data ? rows(town.data, paths.data ?? []) : []), [town.data, paths.data]);
  const shown = all.filter((r) =>
    (source === "all" || (source === "real") === !r.simulated)
    && (status === "all" || r.status === status)
    && (!q || r.shop.toLowerCase().includes(q.toLowerCase()) || r.tag.startsWith(q) || (r.uploadedBy ?? "").toLowerCase().includes(q.toLowerCase())));
  const total = shown.reduce((s, r) => s + r.amount, 0);
  const statuses = [...new Set(all.map((r) => r.status))];

  if (!town.data) return <Note tone={town.error ? "danger" : "neutral"}>{town.error ? `Can't reach the server: ${town.error}` : "Loading…"}</Note>;
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Select label="Source" value={source} onChange={setSource}
          options={[{ id: "all", label: "All" }, { id: "real", label: "Your phones" }, { id: "sim", label: "Simulated town" }]} />
        <Select label="Status" value={status} onChange={setStatus}
          options={[{ id: "all", label: "All" }, ...statuses.map((s) => ({ id: s, label: PAYMENT_STATUS[s]?.text ?? s }))]} />
        <TextInput value={q} onChange={(e) => setQ(e.target.value)} placeholder="Shop, phone or tag id" aria-label="Search"
          className="w-full min-w-0 sm:w-64" />
        <span className="text-th tabular-nums text-secondary sm:ml-auto">
          {shown.length} of {all.length} payments
          {source !== "all" && ` · ${dollars(total)}`}
        </span>
      </div>
      {shown.length === 0 ? <Note>No payments match.</Note> : (
        <div className="max-h-[70vh] overflow-y-auto rounded-[10px] border border-rule">
          <table className="w-full table-fixed border-collapse text-left text-ui tabular-nums">
            <thead className="sticky top-0 z-10 bg-surface">
              <tr className="text-th text-secondary">
                <th className="w-[6.5rem] border-b border-rule px-3 py-2.5 font-semibold sm:w-[8.5rem]">Paid</th>
                <th className="border-b border-rule px-3 py-2.5 font-semibold">Shop</th>
                <th className="w-[7.5rem] border-b border-rule px-3 py-2.5 text-right font-semibold">Amount</th>
                <th className="hidden w-[11rem] border-b border-rule px-3 py-2.5 font-semibold sm:table-cell">Status</th>
                <th className="hidden w-[8.5rem] border-b border-rule px-3 py-2.5 font-semibold md:table-cell">Tag</th>
                <th className="hidden w-[4.5rem] border-b border-rule px-3 py-2.5 text-right font-semibold lg:table-cell">Hops</th>
                <th className="hidden w-[10rem] border-b border-rule px-3 py-2.5 font-semibold xl:table-cell">Uploaded by</th>
                <th className="hidden w-[6.5rem] border-b border-rule px-3 py-2.5 text-right font-semibold lg:table-cell">To server</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => {
                const st = PAYMENT_STATUS[r.status] ?? { text: r.status, tone: "neutral" as Tone };
                return (
                  <tr key={r.tag} className="hover:bg-surface/60">
                    <td className="border-b border-rule px-3 py-2.5 align-top text-th text-secondary">{clockTime(r.paidAt)}</td>
                    <td className="border-b border-rule px-3 py-2.5 align-top">
                      <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                        <span className="min-w-0 break-words text-heading">{r.shop}</span>
                        <Source kind={r.simulated ? "simulated" : "real"} />
                      </div>
                      {r.path && <div className="hidden truncate text-th text-secondary lg:block" title={r.path}>{r.path}</div>}
                      <div className="mt-1 sm:hidden"><Pill tone={st.tone}>{st.text}</Pill></div>
                    </td>
                    <td className="border-b border-rule px-3 py-2.5 text-right align-top font-semibold text-heading">{dollars(r.amount)}</td>
                    <td className="hidden border-b border-rule px-3 py-2.5 align-top sm:table-cell"><Pill tone={st.tone}>{st.text}</Pill></td>
                    <td className="hidden border-b border-rule px-3 py-2.5 align-top md:table-cell"><CopyId value={r.tag} chars={8} /></td>
                    <td className="hidden border-b border-rule px-3 py-2.5 text-right align-top lg:table-cell">{r.hops ?? "—"}</td>
                    <td className="hidden truncate border-b border-rule px-3 py-2.5 align-top text-secondary xl:table-cell">{r.uploadedBy ?? "—"}</td>
                    <td className="hidden border-b border-rule px-3 py-2.5 text-right align-top text-secondary lg:table-cell">{minutes(r.latency)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="mt-3 text-th text-secondary">
        The server's latest 200 payments by the paying phone's clock, joined with the relay path that carried each one.
        A payment only appears once a phone uploads it.
      </p>
    </div>
  );
}

export function LedgerTab({ initial }: { initial: string | null }) {
  const [view, setView] = useState<View>(() => (VIEWS.some((v) => v.id === initial) ? initial as View : "transactions"));
  const pick = (v: View) => {
    setView(v);
    history.replaceState(null, "", `#ledger/${v}`);
  };
  return (
    <div>
      <PageHeader title="Ledger" subtitle="Payments, balances and the bank reconciliation">
        <Tabs tabs={VIEWS} value={view} onChange={pick} />
      </PageHeader>
      {view === "transactions" ? <Transactions /> : <AccountsTab view={view as AccountsView} />}
    </div>
  );
}
