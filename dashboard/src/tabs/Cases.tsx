// Cases tab (spec §18.3, Digital Trust add-on): proven fraud (both tags in one
// table with the conflicting row tinted, Verify it yourself, the Proof QR, the
// "merchant knew" view and StormDesk's case file), the review queue of
// StormDesk flags, and certs their owners froze by texting FREEZE (§17.2).
import QRCode from "qrcode";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { getJSON, type CaseDetail, type CaseSummary, type Health, type RelayPath } from "../api";
import { RULE_TEXT, TagTable, useVerify, VerifyResult } from "../components/Evidence";
import { OwnerFreezes } from "../components/OwnerFreeze";
import { CaseStormDesk, FlagsView } from "../components/StormDesk";
import { Button, Eyebrow, Facts, Note, PageHeader, Pill, Section, Strip, Tabs } from "../components/ui";
import { useEvents } from "../events";
import { clockTime, dollars } from "../format";

const VIEWS = [
  { id: "cases", label: "Proven fraud" },
  { id: "flags", label: "Review queue" },
  { id: "freezes", label: "Owner freezes" },
] as const;
type CasesView = (typeof VIEWS)[number]["id"];

// What the amount in the headline is, per rule.
const RULE_VERB: Record<string, string> = {
  SAME_COUNTER: "spent twice",
  BROKEN_LINK: "spent twice",
  TOTAL_BACKWARDS: "spent twice",
  OVER_CAP: "over the cap",
  MERCHANT_KNEW: "accepted knowingly",
};

// payments.status (schema.sql) in words.
const PAYMENT_STATUS: Record<string, string> = {
  pending: "pending settlement",
  settled: "settled",
  held: "held",
  denied_knowing: "denied: the shop knew",
  refused_evidence: "refused offline, kept as evidence",
  invalid: "invalid",
};

const detectedText = (c: CaseSummary) => (c.detected_where === "offline" ? "Found offline by a phone" : "Caught at settlement");

function ProofQR({ caseId }: { caseId: number }) {
  const [url, setUrl] = useState<string | null>(null);
  const [img, setImg] = useState<string | null>(null);

  useEffect(() => {
    getJSON<Health>("/v1/health")
      .then((h) => (h.public_base_url || location.origin).replace(/\/$/, ""))
      .catch(() => location.origin)
      .then((base) => {
        const target = `${base}/proof/${caseId}`;
        setUrl(target);
        return QRCode.toDataURL(target, { margin: 1, width: 320, errorCorrectionLevel: "M" });
      })
      .then(setImg)
      .catch(() => setImg(null));
  }, [caseId]);

  if (!url) return null;
  return (
    <div className="flex flex-wrap items-center gap-6 border-b border-rule py-4">
      {img && <img src={img} alt={`QR code for ${url}`} className="h-56 w-56" />}
      <div>
        <div className="text-th text-secondary">Scan to verify on your own phone</div>
        <a href={url} target="_blank" rel="noreferrer" className="break-all font-mono text-th text-accent hover:underline">
          {url}
        </a>
      </div>
    </div>
  );
}

/** What happened, in time order, from the case, its certificate and the payments' relay paths. */
function timeline(c: CaseDetail["case"], cert: CaseDetail["cert"], pa?: RelayPath, pb?: RelayPath): [number, string][] {
  const out: [number, string][] = [];
  if (cert) {
    out.push([Number(cert.fields.issued_at), `Certificate v${cert.fields.cert_ver} issued, cap ${dollars(Number(cert.fields.cap_cents))}`]);
  }
  for (const [label, p] of [["A", pa], ["B", pb]] as const) {
    if (!p?.paid_at) continue;
    out.push([p.paid_at, p.status === "refused_evidence"
      ? `${p.merchant} refused payment ${label} offline`
      : `${p.merchant} accepted payment ${label}, ${dollars(p.amount_cents)}`]);
  }
  // The upload that carried the accepted payment to the server (the refused one only proves the conflict).
  const carried = [pa, pb].find((p) => p && p.status !== "refused_evidence") ?? pa;
  if (carried?.received_at) {
    const via = carried.path.map((h) => h.name).join(" → ");
    out.push([carried.received_at,
      `Uploaded by ${carried.uploaded_by ?? "a phone"}, ${carried.hops} ${carried.hops === 1 ? "hop" : "hops"}: ${via} → server`]);
  }
  out.push([c.created_at, `Case #${c.case_id} opened: ${detectedText(c).toLowerCase()}`]);
  return out.sort((x, y) => x[0] - y[0]);
}

function CaseView({ caseId, paths }: { caseId: number; paths: Map<string, RelayPath> }) {
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [serverPub, setServerPub] = useState<string | null>(null);
  const [showQR, setShowQR] = useState(false);
  const caseFile = useRef<HTMLDivElement>(null);
  const reload = useCallback(() => {
    getJSON<CaseDetail>(`/v1/cases/${caseId}`).then(setDetail);
  }, [caseId]);

  useEffect(() => {
    setDetail(null);
    setShowQR(false);
    reload();
    getJSON<Health>("/v1/health").then((h) => setServerPub(h.server_pub));
  }, [caseId, reload]);

  const c = detail?.case;
  const accept = c?.rule === "MERCHANT_KNEW" ? detail?.log_entries.find((e) => e.fields.kind === "ACCEPT") : undefined;
  const { cert, tag_a: a, tag_b: b } = detail ?? { cert: null, tag_a: null, tag_b: null };
  const canVerify = !!(c && cert && a && b && serverPub);
  const { checks, busy, error, verify } = useVerify(
    canVerify ? { rule: c!.rule, cert: cert!, tagA: a!, tagB: b!, serverPubB64: serverPub!, accept } : null,
  );

  if (!detail || !c) return <Note>Loading case…</Note>;
  const text = RULE_TEXT[c.rule] ?? { title: c.rule, why: "" };
  const pa = c.tag_a ? paths.get(c.tag_a) : undefined;
  const pb = c.tag_b ? paths.get(c.tag_b) : undefined;
  const amount = (b ?? a)?.fields.amount_cents as number | undefined;
  const refusedAt = [pa, pb].find((p) => p?.status === "refused_evidence");
  const rulesFired = (c.evidence.rules_fired as string[] | undefined) ?? [c.rule];
  const events = timeline(c, cert, pa, pb);

  return (
    <div className="min-w-0 space-y-10">
      <div className="space-y-4">
        <div>
          <Eyebrow>Case #{c.case_id}</Eyebrow>
          <div className="mt-1 flex flex-wrap items-center gap-3">
            {amount !== undefined && RULE_VERB[c.rule] ? (
              <>
                <span className="text-[30px] leading-9 font-semibold tabular-nums text-heading">{dollars(amount)}</span>
                <span className="text-section text-secondary">{RULE_VERB[c.rule]}</span>
              </>
            ) : (
              <span className="text-[30px] leading-9 font-semibold text-heading">{text.title}</span>
            )}
            <Pill tone="danger">{detectedText(c)}</Pill>
            {canVerify && (
              <div className="ml-auto flex gap-2">
                <Button onClick={() => setShowQR((v) => !v)}>{showQR ? "Hide Proof QR" : "Proof QR"}</Button>
                <Button primary disabled={busy} onClick={verify}>
                  {busy ? "Verifying…" : "Verify it yourself"}
                </Button>
              </div>
            )}
          </div>
          <p className="mt-2 max-w-[80ch] text-ink">
            <span className="font-medium text-heading">{text.title}.</span> {text.why}
          </p>
        </div>
        <Strip
          items={[
            { label: "Rule", value: rulesFired.map((r) => RULE_TEXT[r]?.title ?? r).join(" + ") },
            { label: "Detected", value: c.detected_where === "offline" ? `Offline${refusedAt ? `, ${refusedAt.merchant}` : ""}` : "At settlement" },
            { label: "Exposure", value: <span className="tabular-nums">{dollars(c.exposure_cents)}</span> },
            ...(cert
              ? [{ label: "Certificate", value: `v${cert.fields.cert_ver} · ${dollars(Number(cert.fields.cap_cents))} cap` }]
              : []),
          ]}
        />
        {showQR && <ProofQR caseId={c.case_id} />}
        <VerifyResult checks={checks} error={error} />
      </div>

      {a && (
        <Section title="Conflicting signatures">
          <TagTable
            rule={c.rule === "MERCHANT_KNEW" ? "" : c.rule}
            a={a}
            b={b}
            titleA={b ? `Payment A${pa ? ` · ${pa.merchant}` : ""}` : "Settled payment"}
            titleB={`Payment B${pb ? ` · ${pb.merchant}` : ""}`}
          />
        </Section>
      )}

      {accept && (
        <Section title="The merchant's own signed log">
          <p className="py-2.5 text-ink">
            ACCEPT entry #{String(accept.fields.seq)} for payment B lists what the shop already held:
          </p>
          <ul className="border-t border-rule">
            {(accept.fields.held_ids as string[]).map((h) => {
              const isA = h === a?.digest;
              return (
                <li key={h} className={`flex justify-between gap-4 border-b border-rule px-3 py-2 font-mono text-th ${
                  isA ? "bg-danger-tint font-semibold text-danger" : "text-secondary"}`}>
                  <span className="truncate">{h.slice(0, 24)}…</span>
                  {isA && <span className="font-sans">payment A</span>}
                </li>
              );
            })}
          </ul>
          <p className="truncate py-2 font-mono text-th text-secondary">signature {String(accept.json.sig).slice(0, 32)}…</p>
        </Section>
      )}

      {c.rule === "LOG_TAMPER" && (
        <Section title={`${String(c.evidence.kind)} at entry #${String(c.evidence.seq)}`}>
          <ul>
            {detail.log_entries.map((e) => (
              <li key={e.digest} className="border-b border-rule py-2 font-mono text-th text-ink">
                #{String(e.fields.seq)} {String(e.fields.kind)} entry {e.digest.slice(0, 16)}… after{" "}
                {String(e.fields.prev_hash).slice(0, 16)}…
              </li>
            ))}
          </ul>
        </Section>
      )}

      <div className="grid gap-10 lg:grid-cols-2">
        <Section title="Timeline">
          <ol>
            {events.map(([t, what], i) => (
              <li key={i} className="flex justify-between gap-4 border-b border-rule py-2.5">
                <span className="text-ink">{what}</span>
                <span className="whitespace-nowrap tabular-nums text-secondary">{clockTime(t)}</span>
              </li>
            ))}
          </ol>
        </Section>
        <Section title="Payment details">
          <Facts
            rows={[
              ...(pa ? [["Payment A", `${dollars(pa.amount_cents)} at ${pa.merchant}, ${PAYMENT_STATUS[pa.status] ?? pa.status}`] as [string, string]] : []),
              ...(pb ? [["Payment B", `${dollars(pb.amount_cents)} at ${pb.merchant}, ${PAYMENT_STATUS[pb.status] ?? pb.status}`] as [string, string]] : []),
              ...(cert ? [["Escrow account", <span className="font-mono text-th">{String(cert.fields.escrow_ref)}</span>] as [string, ReactNode]] : []),
              ...(c.cert_id ? [["Certificate id", <span className="font-mono text-th">{c.cert_id}</span>] as [string, ReactNode]] : []),
              ["Case file", (
                <button onClick={() => caseFile.current?.scrollIntoView({ behavior: "smooth" })} className="text-accent hover:underline">
                  StormDesk report
                </button>
              )],
            ]}
          />
          {!pa && !pb && (
            <p className="py-2 text-th text-secondary">The payments' relay paths aren't among the latest 200 uploads.</p>
          )}
        </Section>
      </div>

      <CaseStormDesk caseId={c.case_id} onFiled={reload} />

      <div ref={caseFile}>
        <Section title="Case file (StormDesk)">
          {c.case_file_md ? (
            <p className="max-w-[90ch] whitespace-pre-wrap py-2.5 text-ink">{c.case_file_md}</p>
          ) : (
            <p className="py-2.5 text-secondary">No case file yet.</p>
          )}
        </Section>
      </div>
    </div>
  );
}

function HardCases() {
  const [cases, setCases] = useState<CaseSummary[] | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [paths, setPaths] = useState<Map<string, RelayPath>>(new Map());

  const load = useCallback(() => {
    getJSON<CaseSummary[]>("/v1/cases?limit=200").then((rows) => {
      setCases(rows);
      setSelected((cur) => cur ?? rows[0]?.case_id ?? null);
    });
    getJSON<RelayPath[]>("/v1/relay/paths?limit=200")
      .then((rows) => setPaths(new Map(rows.map((p) => [p.tag_hash, p]))))
      .catch(() => undefined);
  }, []);
  useEffect(load, [load]);
  useEvents(["case_opened", "town", "upload"], load);

  if (!cases) return <Note>Loading…</Note>;
  if (cases.length === 0) return <Note>No hard cases yet.</Note>;
  return (
    <div className="grid gap-10 lg:grid-cols-[17rem_minmax(0,1fr)]">
      <ol className="max-h-[calc(100vh-12rem)] self-start overflow-y-auto border-t border-rule lg:sticky lg:top-6">
        {cases.map((c) => {
          const on = selected === c.case_id;
          return (
            <li key={c.case_id}>
              <button onClick={() => setSelected(c.case_id)} aria-current={on ? "true" : undefined}
                className={`w-full border-b border-rule px-3 py-2.5 text-left ${on ? "bg-accent-tint" : "hover:bg-accent-tint/50"}`}>
                <div className="flex justify-between gap-2">
                  <span className={`font-medium ${on ? "text-accent" : "text-heading"}`}>{RULE_TEXT[c.rule]?.title ?? c.rule}</span>
                  <span className="text-th text-secondary">#{c.case_id}</span>
                </div>
                <div className="text-th tabular-nums text-secondary">
                  {clockTime(c.created_at)} · {c.detected_where === "offline" ? "offline" : "settlement"}
                  {c.exposure_cents > 0 && ` · ${dollars(c.exposure_cents)}`}
                </div>
              </button>
            </li>
          );
        })}
      </ol>
      {selected !== null && <CaseView key={selected} caseId={selected} paths={paths} />}
    </div>
  );
}

export function CasesTab() {
  const [view, setView] = useState<CasesView>(() => {
    try {
      const saved = localStorage.getItem("sc-cases-view");
      return saved === "flags" || saved === "freezes" ? saved : "cases";
    } catch {
      return "cases";
    }
  });
  const pick = (v: CasesView) => {
    setView(v);
    try {
      localStorage.setItem("sc-cases-view", v);
    } catch {
      // private window: fine
    }
  };
  return (
    <div className="pb-12">
      <PageHeader title="Cases" subtitle="Proven fraud and the agent's review queue">
        <Tabs tabs={VIEWS} value={view} onChange={pick} />
      </PageHeader>
      {view === "cases" ? <HardCases /> : view === "flags" ? <FlagsView /> : <OwnerFreezes />}
    </div>
  );
}
