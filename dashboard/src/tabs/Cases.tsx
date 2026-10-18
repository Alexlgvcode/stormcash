// Cases tab (spec §18.3, Digital Trust add-on): proven fraud (both tags in one
// table with the conflicting row tinted, Verify it yourself, the Proof QR, the
// "merchant knew" view and StormDesk's case file), the review queue of
// StormDesk flags, and certs their owners froze by texting FREEZE (§17.2).
import QRCode from "qrcode";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { getJSON, type CaseDetail, type CaseSummary, type Health, type RelayPath } from "../api";
import { caseTitle, casesTakeaway } from "../cases";
import { RULE_TEXT, TagTable, useVerify, VerifyResult } from "../components/Evidence";
import { CaseStormDesk } from "../components/StormDesk";
import { Button, CopyId, Facts, Note, PageHeader, Pill, Section, Source, Strip } from "../components/ui";
import { useEvents } from "../events";
import { clockTime, dollars } from "../format";

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
    out.push([Number(cert.fields.issued_at), `The bank certified the wallet for ${dollars(Number(cert.fields.cap_cents))}`]);
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

function CaseView({ row, paths }: { row: CaseSummary; paths: Map<string, RelayPath> }) {
  const caseId = row.case_id;
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
  // Each payment's shop and status come with the case list; the relay paths add when and how it travelled.
  const shopA = row.payment_a?.merchant ?? pa?.merchant;
  const shopB = row.payment_b?.merchant ?? pb?.merchant;
  const amount = (b ?? a)?.fields.amount_cents as number | undefined;
  const refusedAt = [row.payment_b, row.payment_a].find((p) => p?.status === "refused_evidence");
  const rulesFired = (c.evidence.rules_fired as string[] | undefined) ?? [c.rule];
  const events = timeline(c, cert, pa, pb);

  return (
    <div className="min-w-0 space-y-8">
      <header>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <h2 className="text-[22px] leading-8 font-semibold text-heading sm:text-title">
            {amount !== undefined && RULE_VERB[c.rule] ? (
              <><span className="tabular-nums">{dollars(amount)}</span> {RULE_VERB[c.rule]}</>
            ) : text.title}
          </h2>
          <Pill tone="danger">{detectedText(c)}</Pill>
          <Source kind={row.simulated ? "simulated" : "real"} />
        </div>
        <p className="mt-1 text-secondary">Case #{c.case_id} · {text.title} · opened {clockTime(c.created_at)}</p>
        <Strip
          items={[
            { label: "Rule", value: text.title },
            { label: "Detected", value: c.detected_where === "offline" ? `Offline${refusedAt ? `, ${refusedAt.merchant}` : ""}` : "At settlement" },
            { label: "Exposure", value: dollars(c.exposure_cents), sub: "the guarantee pool stands behind it" },
            ...(cert ? [{ label: "Wallet limit", value: dollars(Number(cert.fields.cap_cents)) }] : []),
          ]}
        />
      </header>

      <div className="grid gap-6 2xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        {/* Left: the proof. Signed records and the checks anyone can re-run. No model involved. */}
        <section aria-labelledby="proof-h" className="min-w-0 rounded-[10px] border border-teal/40 bg-surface">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-rule px-4 py-2.5">
            <h3 id="proof-h" className="flex items-center gap-2 text-ui font-semibold text-heading">
              <span className="rounded border border-teal/60 px-1.5 text-[11px] leading-[18px] font-semibold uppercase tracking-wide text-success">Cryptographic proof</span>
              Signed by the wallet, certified by the bank's server
            </h3>
          </div>
          <div className="space-y-4 px-4 py-4">
            <p className="max-w-[80ch] text-ink">{text.why}</p>
            {a && (
              <TagTable
                rule={c.rule === "MERCHANT_KNEW" ? "" : c.rule}
                a={a}
                b={b}
                titleA={b ? `Payment A${shopA ? ` · ${shopA}` : ""}` : "Settled payment"}
                titleB={`Payment B${shopB ? ` · ${shopB}` : ""}`}
                checks={checks}
              />
            )}
            {canVerify && (
              <div className="flex flex-wrap items-center gap-2.5">
                <Button primary disabled={busy} onClick={verify}>
                  {busy ? "Verifying…" : checks ? "Verify again" : "Verify it yourself"}
                </Button>
                <Button onClick={() => setShowQR((v) => !v)} aria-expanded={showQR}>{showQR ? "Hide Proof QR" : "Proof QR"}</Button>
                <span className="text-th text-secondary">Runs in this browser with WebCrypto. Nothing is sent anywhere.</span>
              </div>
            )}
            {showQR && <ProofQR caseId={c.case_id} />}
            <VerifyResult checks={checks} error={error} />
            {accept && (
              <div>
                <h4 className="border-b border-rule pb-1.5 font-semibold text-heading">The merchant's own signed log</h4>
                <p className="py-2 text-ink">ACCEPT entry #{String(accept.fields.seq)} for payment B lists what the shop already held:</p>
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
              </div>
            )}
            {c.rule === "LOG_TAMPER" && (
              <div>
                <h4 className="border-b border-rule pb-1.5 font-semibold text-heading">{`${String(c.evidence.kind)} at entry #${String(c.evidence.seq)}`}</h4>
                <ul>
                  {detail.log_entries.map((e) => (
                    <li key={e.digest} className="border-b border-rule py-2 font-mono text-th text-ink">
                      #{String(e.fields.seq)} {String(e.fields.kind)} entry {e.digest.slice(0, 16)}… after{" "}
                      {String(e.fields.prev_hash).slice(0, 16)}…
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </section>

        {/* Right: what the agent made of it. Advisory; the proof stands without it. */}
        <section aria-labelledby="ai-h" className="min-w-0 self-start rounded-[10px] border border-dashed border-accent/40">
          <div className="border-b border-rule px-4 py-2.5">
            <h3 id="ai-h" className="flex flex-wrap items-center gap-2 text-ui font-semibold text-heading">
              <span className="rounded border border-accent/50 px-1.5 text-[11px] leading-[18px] font-semibold uppercase tracking-wide text-accent">AI interpretation</span>
              StormDesk's reading
            </h3>
            <p className="mt-1 text-th text-secondary">
              Advisory only. It can't change the proof, move money or close the case; anything it proposes waits for a person.
            </p>
          </div>
          <div className="space-y-6 px-4 py-3">
            <CaseStormDesk caseId={c.case_id} onFiled={reload} />
            <div ref={caseFile}>
              <Section title="Case file">
                {c.case_file_md ? (
                  <p className="max-w-[90ch] whitespace-pre-wrap py-2.5 text-ink">{c.case_file_md}</p>
                ) : (
                  <p className="py-2.5 text-secondary">No case file yet.</p>
                )}
              </Section>
            </div>
          </div>
        </section>
      </div>

      <div className="grid gap-8 xl:grid-cols-2">
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
            rows={([["Payment A", row.payment_a], ["Payment B", row.payment_b]] as const)
              .filter(([, p]) => p)
              .map(([label, p]) => [label, `${dollars(p!.amount_cents)} at ${p!.merchant ?? "a shop"}, ${
                PAYMENT_STATUS[p!.status ?? ""] ?? p!.status ?? "not paid"}`] as [string, string])}
          />
          {(cert || c.cert_id) && (
            <details className="mt-2">
              <summary className="cursor-pointer py-2 text-accent">Technical details</summary>
              <Facts rows={[
                ...(cert ? [["Escrow account", <CopyId value={String(cert.fields.escrow_ref)} chars={14} />] as [string, ReactNode]] : []),
                ...(cert ? [["Certificate version", String(cert.fields.cert_ver)] as [string, ReactNode]] : []),
                ...(c.cert_id ? [["Certificate id", <CopyId value={c.cert_id} chars={14} />] as [string, ReactNode]] : []),
                ...(rulesFired.length ? [["Rules fired", <span className="font-mono text-th">{rulesFired.join(", ")}</span>] as [string, ReactNode]] : []),
              ]} />
            </details>
          )}
        </Section>
      </div>
    </div>
  );
}

function CaseButton({ c, on, onPick }: { c: CaseSummary; on: boolean; onPick: () => void }) {
  return (
    <li>
      <button onClick={onPick} aria-current={on ? "true" : undefined}
        className={`min-h-11 w-full border-b border-l-2 border-b-rule px-3 py-2.5 text-left ${on ? "border-l-accent bg-accent-tint" : "border-l-transparent hover:bg-surface"}`}>
        <div className={`font-medium ${on ? "text-accent" : "text-heading"}`}>{caseTitle(c)}</div>
        <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-th text-secondary">
          <span>{clockTime(c.created_at)}</span>
          <span>· {c.detected_where === "offline" ? "found offline" : "at settlement"}</span>
          <span>· #{c.case_id}</span>
          <Source kind={c.simulated ? "simulated" : "real"} />
        </div>
      </button>
    </li>
  );
}

/** Your phones' cases first; the simulated town's below, collapsed. */
function HardCases({ cases, paths }: { cases: CaseSummary[] | null; paths: Map<string, RelayPath> }) {
  const [selected, setSelected] = useState<number | null>(null);
  const [townOpen, setTownOpen] = useState<boolean | null>(null);

  if (!cases) return <Note>Loading…</Note>;
  if (cases.length === 0) return <Note>No proven cases yet.</Note>;
  const real = cases.filter((c) => !c.simulated);
  const town = cases.filter((c) => c.simulated);
  const open = townOpen ?? real.length === 0; // with nothing from the phones, show the town's cases
  const current = cases.find((c) => c.case_id === selected) ?? real[0] ?? town[0];
  return (
    <div className="grid gap-8 lg:grid-cols-[18rem_minmax(0,1fr)] xl:grid-cols-[20rem_minmax(0,1fr)]">
      <div className="max-h-[40vh] self-start overflow-y-auto rounded-[10px] border border-rule bg-surface/50 p-2 lg:sticky lg:top-20 lg:max-h-[calc(100vh-7rem)] lg:border-0 lg:bg-transparent lg:p-0">
        <div className="border-b border-rule pb-1.5 text-eyebrow font-semibold uppercase text-secondary">Your phones</div>
        {real.length === 0 ? (
          <p className="border-b border-rule px-3 py-2.5 text-secondary">No proven cases from your phones yet.</p>
        ) : (
          <ol>
            {real.map((c) => <CaseButton key={c.case_id} c={c} on={current?.case_id === c.case_id} onPick={() => setSelected(c.case_id)} />)}
          </ol>
        )}
        {town.length > 0 && (
          <>
            <button onClick={() => setTownOpen(!open)} aria-expanded={open}
              className="mt-6 flex w-full items-center justify-between border-b border-rule pb-1.5 text-left text-eyebrow font-semibold uppercase text-secondary hover:text-heading">
              Simulated town ({town.length})
              <span aria-hidden="true">{open ? "−" : "+"}</span>
            </button>
            {open && (
              <ol>
                {town.map((c) => <CaseButton key={c.case_id} c={c} on={current?.case_id === c.case_id} onPick={() => setSelected(c.case_id)} />)}
              </ol>
            )}
          </>
        )}
      </div>
      {current && <CaseView key={current.case_id} row={current} paths={paths} />}
    </div>
  );
}

export function CasesTab() {
  const [cases, setCases] = useState<CaseSummary[] | null>(null);
  const [paths, setPaths] = useState<Map<string, RelayPath>>(new Map());
  const load = useCallback(() => {
    getJSON<CaseSummary[]>("/v1/cases?limit=200").then(setCases).catch(() => setCases((cur) => cur ?? []));
    getJSON<RelayPath[]>("/v1/relay/paths?limit=200")
      .then((rows) => setPaths(new Map(rows.map((p) => [p.tag_hash, p]))))
      .catch(() => undefined);
  }, []);
  useEffect(load, [load]);
  useEvents(["case_opened", "town", "upload"], load);

  return (
    <div className="pb-12">
      <PageHeader title="Cases" subtitle="Double spends proven by signed records"
        takeaway={cases ? casesTakeaway(cases) : undefined} />
      <HardCases cases={cases} paths={paths} />
    </div>
  );
}
