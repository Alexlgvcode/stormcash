// A shop's appeal as one conversation (spec §17.2): the StormDesk turns behind a
// Photon thread (GET /v1/photon/messages → turns). With appeal sessions on, every
// turn of a thread resumes the same Droid session; these helpers only describe
// what the stored runs say (§0 rule 3). No imports, so `npm test` runs this file directly.

export interface AppealTurn {
  run_id: number;
  runner: string;
  status: string;
  session_id: string | null;
  citations_valid: boolean | null;
  model: string | null;
  factory_credits: number | null;
  duration_s: number | null;
  fallback_from_droid: string | null;
  mode: "session" | "per_message" | null;
  flag_id: number | null;
  in_message_id: number | null;
  out_message_id: number | null;
  reply_sent: boolean | null;
  session: "started" | "resumed" | "restarted" | null;
  turn: number | null;
  resume_error: string | null;
}

export interface AppealSession {
  session_id: string;
  turns: number;
  credits: number | null;
}

/** "a1b2c3d4" from a Droid session id. */
export function shortSession(id: string): string {
  return id.replace(/-/g, "").slice(0, 8);
}

const n = (value: number) => Math.round(value).toLocaleString("en-US");

/** The turn that sent each outbound message, by message id. */
export function turnsByReply(turns: AppealTurn[]): Map<number, AppealTurn> {
  const out = new Map<number, AppealTurn>();
  for (const t of turns) if (t.out_message_id != null) out.set(t.out_message_id, t);
  return out;
}

/** The thread's Droid sessions, in the order they started. */
export function sessionsOf(turns: AppealTurn[]): AppealSession[] {
  const seen = new Map<string, AppealSession>();
  for (const t of turns) {
    if (t.runner !== "droid" || t.mode !== "session" || !t.session_id) continue;
    const s = seen.get(t.session_id) ?? { session_id: t.session_id, turns: 0, credits: null };
    s.turns += 1;
    if (t.factory_credits != null) s.credits = (s.credits ?? 0) + t.factory_credits;
    seen.set(t.session_id, s);
  }
  return [...seen.values()];
}

/** The thread's header: "One Droid session · 3 turns · 15,000 credits", or null when no Droid session answered. */
export function sessionSummary(turns: AppealTurn[]): string | null {
  const sessions = sessionsOf(turns);
  if (sessions.length === 0) return null;
  const count = sessions.reduce((sum, s) => sum + s.turns, 0);
  const credits = sessions.every((s) => s.credits == null) ? null : sessions.reduce((sum, s) => sum + (s.credits ?? 0), 0);
  const head = sessions.length === 1 ? "One Droid session" : `${sessions.length} Droid sessions`;
  return [head, `${count} turn${count === 1 ? "" : "s"}`, credits != null ? `${n(credits)} credits` : null]
    .filter(Boolean).join(" · ");
}

/** Who answered a message, in a few words: the Droid session and turn, or the labelled fake runner. */
export function turnLabel(t: AppealTurn): string {
  if (t.runner === "fake") return t.fallback_from_droid ? "Rules-only stand-in (Droid couldn't run)" : "Rules-only stand-in";
  if (t.runner !== "droid") return "StormDesk";
  const parts: string[] = [];
  if (t.mode !== "session" || !t.session_id) {
    parts.push("Droid · one run for this message");
  } else if (t.session === "resumed") {
    parts.push(`Droid · turn ${t.turn} · same Droid session ${shortSession(t.session_id)}`);
  } else if (t.session === "restarted") {
    parts.push(`Droid · new session ${shortSession(t.session_id)} from the stored thread (couldn't resume the last one)`);
  } else {
    parts.push(`Droid · turn ${t.turn ?? 1} · new session ${shortSession(t.session_id)}`);
  }
  if (t.factory_credits != null) parts.push(`${n(t.factory_credits)} credits`);
  return parts.join(" · ");
}

/** Why the agent's reply didn't go out (the shop got the neutral acknowledgement), or null when it did. */
export function heldBack(t: AppealTurn): string | null {
  if (t.reply_sent !== false) return null;
  if (t.runner === "fake") return null; // the fake runner never answers for itself
  if (t.status === "invalid") return "Droid's reply was held back: it cited a record that doesn't exist";
  if (t.status === "failed") return "Droid gave no valid answer";
  return "Droid's reply was held back: it cited no records";
}
