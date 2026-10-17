// Cases tab (spec §18.3, Digital Trust add-on): hard cases with both tags side
// by side, the conflicting field in red, Verify it yourself, the Proof QR, the
// "merchant knew" view and StormDesk's case file; StormDesk flags; and certs
// their owners froze by texting FREEZE (§17.2).
import QRCode from "qrcode";
import { useCallback, useEffect, useState } from "react";
import { getJSON, type CaseDetail, type CaseSummary, type Health } from "../api";
import { RULE_TEXT, TagCard, TagPair, VerifyPanel } from "../components/Evidence";
import { OwnerFreezes } from "../components/OwnerFreeze";
import { CaseStormDesk, FlagsView } from "../components/StormDesk";
import { useEvents } from "../events";
import { clockTime, dollars } from "../format";

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
    <div className="flex flex-col items-center gap-2 rounded-2xl bg-white p-4">
      {img && <img src={img} alt={`QR code for ${url}`} className="h-64 w-64" />}
      <a href={url} target="_blank" rel="noreferrer" className="break-all text-center font-mono text-sm text-slate-700">
        {url}
      </a>
    </div>
  );
}

function CaseView({ caseId }: { caseId: number }) {
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [serverPub, setServerPub] = useState<string | null>(null);
  const [showQR, setShowQR] = useState(false);
  const reload = useCallback(() => {
    getJSON<CaseDetail>(`/v1/cases/${caseId}`).then(setDetail);
  }, [caseId]);

  useEffect(() => {
    setDetail(null);
    setShowQR(false);
    reload();
    getJSON<Health>("/v1/health").then((h) => setServerPub(h.server_pub));
  }, [caseId, reload]);

  if (!detail) return <p className="text-slate-400">Loading case…</p>;
  const { case: c, cert, tag_a: a, tag_b: b, log_entries } = detail;
  const text = RULE_TEXT[c.rule] ?? { title: c.rule, why: "" };
  const accept = c.rule === "MERCHANT_KNEW" ? log_entries.find((e) => e.fields.kind === "ACCEPT") : undefined;

  return (
    <div className="space-y-5">
      <div>
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-3xl font-bold text-white">{text.title}</h2>
          <span className="rounded-full bg-slate-800 px-3 py-1 font-mono text-sm text-slate-300">{c.rule}</span>
          <span
            className={`rounded-full px-3 py-1 text-sm font-semibold ${
              c.detected_where === "offline" ? "bg-emerald-500/15 text-emerald-300" : "bg-sky-500/15 text-sky-300"
            }`}
          >
            {c.detected_where === "offline" ? "found offline by a phone" : "caught at settlement"}
          </span>
        </div>
        <p className="mt-2 text-lg text-slate-300">{text.why}</p>
        {c.exposure_cents > 0 && <p className="text-slate-400">Exposure: {dollars(c.exposure_cents)}</p>}
      </div>

      {a && b && <TagPair rule={c.rule === "MERCHANT_KNEW" ? "" : c.rule} a={a} b={b} />}
      {a && !b && <TagCard title="Settled payment" tag={a} red={["cum_cents"]} />}

      {accept && (
        <div className="rounded-2xl border border-amber-500/40 bg-amber-500/5 p-4">
          <h3 className="text-lg font-semibold text-amber-200">The merchant's own signed log</h3>
          <p className="text-slate-300">
            ACCEPT entry #{String(accept.fields.seq)} for payment B lists what the shop already held:
          </p>
          <ul className="mt-2 font-mono text-sm">
            {(accept.fields.held_ids as string[]).map((h) => (
              <li key={h} className={h === a?.digest ? "font-bold text-rose-300" : "text-slate-400"}>
                {h.slice(0, 24)}… {h === a?.digest && "← payment A"}
              </li>
            ))}
          </ul>
          <p className="mt-2 truncate font-mono text-xs text-slate-500">signature {String(accept.json.sig).slice(0, 32)}…</p>
        </div>
      )}

      {c.rule === "LOG_TAMPER" && (
        <div className="rounded-2xl border border-slate-700 p-4">
          <h3 className="text-lg font-semibold text-white">
            {String(c.evidence.kind)} at entry #{String(c.evidence.seq)}
          </h3>
          {log_entries.map((e) => (
            <p key={e.digest} className="font-mono text-sm text-slate-300">
              #{String(e.fields.seq)} {String(e.fields.kind)} entry {e.digest.slice(0, 16)}… after{" "}
              {String(e.fields.prev_hash).slice(0, 16)}…
            </p>
          ))}
        </div>
      )}

      {cert && a && b && serverPub && (
        <div className="grid gap-4 lg:grid-cols-[1fr_auto]">
          <VerifyPanel input={{ rule: c.rule, cert, tagA: a, tagB: b, serverPubB64: serverPub, accept }} />
          <div className="flex flex-col gap-3">
            <button
              onClick={() => setShowQR((v) => !v)}
              className="rounded-xl bg-slate-800 px-5 py-3 text-lg font-semibold text-white hover:bg-slate-700"
            >
              {showQR ? "Hide Proof QR" : "Proof QR"}
            </button>
            {showQR && <ProofQR caseId={c.case_id} />}
          </div>
        </div>
      )}

      <CaseStormDesk caseId={c.case_id} onFiled={reload} />

      <div className="rounded-2xl border border-slate-800 bg-slate-900 p-4">
        <h3 className="mb-2 text-lg font-semibold text-white">Case file (StormDesk)</h3>
        {c.case_file_md ? (
          <pre className="whitespace-pre-wrap font-sans text-base text-slate-200">{c.case_file_md}</pre>
        ) : (
          <p className="text-slate-400">No case file yet.</p>
        )}
      </div>
    </div>
  );
}

type CasesView = "cases" | "flags" | "freezes";
const VIEW_TITLE: Record<CasesView, string> = { cases: "Hard cases", flags: "StormDesk flags", freezes: "Owner freezes" };

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
    <div>
      <div className="flex gap-2 px-6 pt-4">
        {(["cases", "flags", "freezes"] as const).map((v) => (
          <button key={v} onClick={() => pick(v)}
            className={`rounded-full px-4 py-2 text-base font-semibold ${
              view === v ? "bg-sky-500 text-slate-950" : "bg-slate-800 text-slate-300 hover:bg-slate-700"}`}>
            {VIEW_TITLE[v]}
          </button>
        ))}
      </div>
      {view === "cases" ? <HardCases /> : view === "flags" ? <FlagsView /> : <OwnerFreezes />}
    </div>
  );
}

function HardCases() {
  const [cases, setCases] = useState<CaseSummary[] | null>(null);
  const [selected, setSelected] = useState<number | null>(null);

  const load = useCallback(() => {
    getJSON<CaseSummary[]>("/v1/cases?limit=200").then((rows) => {
      setCases(rows);
      setSelected((cur) => cur ?? rows[0]?.case_id ?? null);
    });
  }, []);
  useEffect(load, [load]);
  useEvents(["case_opened", "town"], load);

  if (!cases) return <p className="p-8 text-xl text-slate-300">Loading…</p>;
  if (cases.length === 0) return <p className="p-8 text-xl text-slate-400">No hard cases yet.</p>;
  return (
    <div className="grid gap-6 p-6 lg:grid-cols-[22rem_1fr]">
      <ol className="max-h-[80vh] space-y-2 overflow-y-auto">
        {cases.map((c) => (
          <li key={c.case_id}>
            <button
              onClick={() => setSelected(c.case_id)}
              className={`w-full rounded-xl border p-3 text-left ${
                selected === c.case_id ? "border-sky-400 bg-slate-800" : "border-slate-800 bg-slate-900 hover:bg-slate-800"
              }`}
            >
              <div className="flex justify-between gap-2">
                <span className="font-semibold text-white">{RULE_TEXT[c.rule]?.title ?? c.rule}</span>
                <span className="text-sm text-slate-400">#{c.case_id}</span>
              </div>
              <div className="text-sm text-slate-400">
                {clockTime(c.created_at)} · {c.detected_where === "offline" ? "offline" : "settlement"}
                {c.exposure_cents > 0 && ` · ${dollars(c.exposure_cents)}`}
              </div>
            </button>
          </li>
        ))}
      </ol>
      {selected !== null && <CaseView caseId={selected} />}
    </div>
  );
}
