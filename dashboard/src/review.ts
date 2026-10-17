// The reviewer's second opinion on a StormDesk flag, as the flag panel shows it
// (spec §14.7b). Only a valid review by an agent counts: the fake reviewer's
// rules-only comparison is shown, labelled, and never escalates a flag.
// No imports, so `npm test` runs this file directly.

/** flags.review: the reviewer's structured output plus what its run recorded. */
export interface FlagReview {
  run_id: number;
  runner: string;
  status: "succeeded" | "invalid" | "failed";
  verdict: "agree" | "disagree" | "insufficient_evidence" | null;
  reasons?: string[];
  evidence_ids?: string[];
  suggested_kind?: string | null;
  suggested_severity?: string | null;
  suggested_action?: string | null;
  citations_valid: boolean;
  missing_citations: string[];
  error: string | null;
  fallback_from_droid?: string | null;
  model?: string | null;
  model_requested?: string | null;
  usage?: { factory_credits?: number; input_tokens?: number; output_tokens?: number; cache_read_tokens?: number } | null;
  prompt_version?: number | null;
  duration_s?: number | null;
}

export interface VerdictView {
  label: string;
  tone: "agree" | "disagree" | "void";
  /** Whether this review can move the flag (a valid agent review). */
  counted: boolean;
  note: string | null;
}

export function reviewVerdict(review: FlagReview): VerdictView {
  if (review.status !== "succeeded" || !review.verdict) {
    return {
      label: review.status === "invalid" ? "Reviewer cited a record that doesn't exist" : "Reviewer gave no answer",
      tone: "void",
      counted: false,
      note: "Not counted: the flag stays as StormDesk proposed it.",
    };
  }
  const fake = review.runner === "fake";
  const who = fake ? "Stand-in reviewer (rules only)" : "Reviewer";
  const label = review.verdict === "agree" ? `${who} agrees`
    : review.verdict === "disagree" ? `${who} disagrees` : `${who}: not enough evidence`;
  return {
    label,
    tone: review.verdict === "agree" ? "agree" : "disagree",
    counted: !fake,
    note: fake && review.verdict !== "agree" ? "Not counted: a rules-only comparison isn't a second opinion." : null,
  };
}

/** "Suggests: Shop went quiet · Hold guarantee-pool payouts · urgent", only when the reviewer proposed something else. */
export function suggestion(review: FlagReview, kindTitle: Record<string, string>,
  actionTitle: Record<string, string>): string | null {
  if (review.verdict === "agree") return null;
  const parts = [
    review.suggested_kind ? (kindTitle[review.suggested_kind] ?? review.suggested_kind) : null,
    review.suggested_action ? (actionTitle[review.suggested_action] ?? review.suggested_action) : null,
    review.suggested_severity ?? null,
  ].filter(Boolean);
  return parts.length ? `Suggests: ${parts.join(" · ")}` : null;
}
