// Resident FREEZE by text (spec §17.2): the owner of a stolen phone texts FREEZE through Photon,
// the server freezes the cert (no agent) and publishes a new POLICY. Shown next to a cap_drain
// flag on that cert, and as a list on the Cases tab with the resident's thread.
import { useCallback, useEffect, useState } from "react";
import { getJSON, type Message, type OwnerFreeze } from "../api";
import { useEvents } from "../events";
import { clockTime } from "../format";
import { Note, Pill, Section, StatusItem, Table, Td, Th } from "./ui";

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
    <div className="border-y border-rule py-3">
      <StatusItem tone="neutral">
        <span className="font-medium text-heading">Owner asked for the freeze by text.</span> {freezeLine(row)}
      </StatusItem>
      <p className="mt-1 pl-6 text-th text-secondary">
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
    <Section title="Photon thread">
      {messages.length === 0 && <p className="py-2.5 text-secondary">No messages with this resident.</p>}
      <ol>
        {messages.map((m) => {
          const out = m.direction === "out";
          return (
            <li key={m.message_id} className="grid grid-cols-[8.5rem_minmax(0,1fr)] gap-4 border-b border-rule py-3">
              <div className="text-th text-secondary">
                <div className={`font-medium ${out ? "text-accent" : "text-heading"}`}>{out ? "StormCash" : "Resident"}</div>
                <div className="tabular-nums">{clockTime(m.created_at)}</div>
                <div>{m.channel}</div>
              </div>
              <div className="min-w-0">
                <p className="whitespace-pre-wrap break-words text-ink">{m.body}</p>
                {m.delivered === false && <p className="mt-1 text-th text-secondary">not delivered</p>}
              </div>
            </li>
          );
        })}
      </ol>
    </Section>
  );
}

/** Cases tab: every cert frozen at its owner's request. */
export function OwnerFreezes() {
  const rows = useOwnerFreezes();
  const [selected, setSelected] = useState<string | null>(null);
  const current = rows?.find((r) => r.cert_id === selected) ?? rows?.[0];

  if (!rows) return <Note>Loading…</Note>;
  if (rows.length === 0) {
    return <Note>No owner freezes yet. A resident texts FREEZE from their registered handle to freeze their wallet.</Note>;
  }
  return (
    <div className="space-y-10">
      <Table>
        <thead>
          <tr>
            <Th className="pl-3">Resident</Th>
            <Th>Texted FREEZE</Th>
            <Th>Certificate</Th>
            <Th>Status</Th>
            <Th>Freeze list</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const on = current?.cert_id === r.cert_id;
            return (
              <tr key={r.cert_id} onClick={() => setSelected(r.cert_id)} aria-selected={on}
                className={`cursor-pointer ${on ? "bg-accent-tint" : "hover:bg-accent-tint/50"}`}>
                <Td className="pl-3 font-medium text-heading">{r.display_name}</Td>
                <Td className="tabular-nums">{clockTime(r.owner_freeze_at)}</Td>
                <Td className="font-mono text-th">{r.cert_id.slice(0, 16)}…</Td>
                <Td>
                  <Pill tone={r.status === "frozen" ? "danger" : "neutral"}>{r.status}</Pill>
                </Td>
                <Td className="pr-3 text-secondary">{r.policy_ver != null ? `POLICY v${r.policy_ver}` : "not listed yet"}</Td>
              </tr>
            );
          })}
        </tbody>
      </Table>
      {current && (
        <div className="space-y-8">
          <div>
            <h2 className="text-[22px] leading-8 font-semibold text-heading">Frozen by its owner</h2>
            <p className="mt-2 text-ink">{freezeLine(current)}</p>
            <p className="mt-1 text-secondary">
              No agent involved: the server froze the certificate and signed a new freeze list. Shops refuse it as the
              list spreads phone to phone.
            </p>
          </div>
          <ResidentThread residentId={current.resident_id} />
        </div>
      )}
    </div>
  );
}
