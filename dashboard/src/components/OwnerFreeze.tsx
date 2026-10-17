// Resident FREEZE by text (spec §17.2): the owner of a stolen phone texts FREEZE through Photon,
// the server freezes the cert (no agent) and publishes a new POLICY. Shown next to a cap_drain
// flag on that cert, and as a list on the Cases tab with the resident's thread.
import { useCallback, useEffect, useState } from "react";
import { getJSON, type Message, type OwnerFreeze } from "../api";
import { useEvents } from "../events";
import { clockTime } from "../format";

function useOwnerFreezes(certId?: string) {
  const [rows, setRows] = useState<OwnerFreeze[] | null>(null);
  const load = useCallback(() => {
    getJSON<OwnerFreeze[]>(`/v1/photon/freezes${certId ? `?cert_id=${certId}` : ""}`)
      .then(setRows)
      .catch(() => setRows([]));
  }, [certId]);
  useEffect(load, [load]);
  useEvents(["owner_freeze", "policy"], load);
  return rows;
}

function freezeLine(f: OwnerFreeze): string {
  const policy = f.policy_ver != null ? `, listed in POLICY v${f.policy_ver}` : "";
  return `${f.display_name} texted FREEZE at ${clockTime(f.owner_freeze_at)}: certificate ${f.status}${policy}.`;
}

/** Under a flag whose subject is a cert: did the owner ask for the freeze by text? */
export function OwnerFreezeNote({ certId, seenByDetector }: { certId: string; seenByDetector: boolean }) {
  const [row] = useOwnerFreezes(certId) ?? [];
  if (!row) return null;
  return (
    <div className="rounded-xl border border-sky-500/40 bg-sky-500/5 p-4">
      <h4 className="text-base font-semibold text-sky-200">Owner asked for the freeze by text</h4>
      <p className="text-slate-200">{freezeLine(row)}</p>
      <p className="text-sm text-slate-400">
        {seenByDetector
          ? "The detector saw it: owner_freeze_request is true in this candidate's features."
          : "It came after this candidate was created, so its features say owner_freeze_request: false."}
      </p>
    </div>
  );
}

export function ResidentThread({ residentId }: { residentId: string }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const load = useCallback(() => {
    getJSON<{ messages: Message[] }>(`/v1/photon/messages?resident_id=${residentId}`)
      .then((r) => setMessages(r.messages))
      .catch(() => setMessages([]));
  }, [residentId]);
  useEffect(load, [load]);
  useEvents(["message"], (data) => {
    if ((data as Message).resident_id === residentId) setMessages((cur) => [...cur, data as Message]);
  });
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950 p-4">
      <h4 className="mb-2 text-base font-semibold text-slate-200">Photon thread</h4>
      {messages.length === 0 && <p className="text-slate-500">No messages with this resident.</p>}
      <ol className="space-y-2">
        {messages.map((m) => (
          <li key={m.message_id} className={`flex ${m.direction === "out" ? "justify-end" : "justify-start"}`}>
            <div className={`max-w-[85%] rounded-2xl px-3 py-2 text-base ${
              m.direction === "out" ? "bg-sky-600/30 text-sky-50" : "bg-slate-800 text-slate-100"}`}>
              {m.body}
              <div className="mt-1 text-xs text-slate-400">
                {m.direction === "out" ? "StormCash" : "Resident"} · {m.channel} · {clockTime(m.created_at)}
                {m.delivered === false && " · not delivered"}
              </div>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

/** Cases tab: every cert frozen at its owner's request. */
export function OwnerFreezes() {
  const rows = useOwnerFreezes();
  const [selected, setSelected] = useState<string | null>(null);
  const current = rows?.find((r) => r.cert_id === selected) ?? rows?.[0];

  if (!rows) return <p className="p-8 text-xl text-slate-300">Loading…</p>;
  if (rows.length === 0) {
    return (
      <p className="p-8 text-xl text-slate-400">
        No owner freezes yet. A resident texts FREEZE from their registered handle to freeze their wallet.
      </p>
    );
  }
  return (
    <div className="grid gap-6 p-6 lg:grid-cols-[22rem_1fr]">
      <ol className="max-h-[80vh] space-y-2 overflow-y-auto">
        {rows.map((r) => (
          <li key={r.cert_id}>
            <button onClick={() => setSelected(r.cert_id)}
              className={`w-full rounded-xl border p-3 text-left ${
                current?.cert_id === r.cert_id ? "border-sky-400 bg-slate-800" : "border-slate-800 bg-slate-900 hover:bg-slate-800"}`}>
              <div className="flex justify-between gap-2">
                <span className="font-semibold text-white">{r.display_name}</span>
                <span className="text-sm text-slate-400">{clockTime(r.owner_freeze_at)}</span>
              </div>
              <div className="truncate font-mono text-sm text-slate-400">cert {r.cert_id.slice(0, 16)}…</div>
            </button>
          </li>
        ))}
      </ol>
      {current && (
        <div className="space-y-4">
          <h2 className="text-3xl font-bold text-white">Frozen by its owner</h2>
          <p className="text-lg text-slate-200">{freezeLine(current)}</p>
          <p className="text-slate-400">
            No agent involved: the server froze the certificate and signed a new freeze list. Shops refuse it as the
            list spreads phone to phone.
          </p>
          <ResidentThread residentId={current.resident_id} />
        </div>
      )}
    </div>
  );
}
