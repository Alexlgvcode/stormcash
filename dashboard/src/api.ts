// Thin client for the StormCash API (spec §12). In dev the Vite proxy serves
// /v1; a deployed build sets VITE_API_BASE to the server's URL.
import type { CasePayment } from "./cases";
import type { FlagReview } from "./review";

export const API_BASE: string = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(API_BASE + path, init);
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      detail = (await resp.json()).detail ?? detail;
    } catch {
      // not JSON
    }
    throw new ApiError(resp.status, detail);
  }
  return resp.json() as Promise<T>;
}

export const getJSON = <T>(path: string) => request<T>(path);

export const operatorPost = <T>(path: string, body: unknown = {}, operator = "dashboard") =>
  request<T>(path, {
    method: "POST",
    headers: { "content-type": "application/json", "X-SC-Operator": operator },
    body: JSON.stringify(body),
  });

export interface AccountCard {
  key: string;
  label: string;
  kind: "checking" | "escrow" | "merchant" | "pool";
  nessie_account_id: string | null;
  nessie_cents: number | null;
  nessie_error: string | null;
  ledger_cents: number;
}

export interface AccountsSnapshot {
  as_of: number;
  accounts: AccountCard[];
  simulated_town: { label: string; merchants: number; merchant_cents: number; escrow_cents: number };
  ledger: { balanced: boolean; unbalanced_txns: number; totals: Record<string, number> };
  nessie: { enabled: boolean; queued: number };
}

export interface NessieCall {
  call_id: number;
  method: string;
  path: string;
  status: number | null;
  summary: string | null;
  created_at: number;
}

export interface Health {
  public_base_url: string;
  ok: boolean;
  time: number;
  demo_mode: boolean;
  nessie_enabled: boolean;
  api_sig_required: boolean;
  server_pub: string;
}

export interface SignedObj {
  type: string;
  json: Record<string, unknown>;
  fields: Record<string, string | number | string[]>;
  canonical: string;
  digest: string;
}

export interface CaseSummary {
  case_id: number;
  rule: string;
  cert_id: string | null;
  merchant_id: string | null;
  device_pub: string | null;
  tag_a: string | null;
  tag_b: string | null;
  detected_where: "offline" | "server";
  exposure_cents: number;
  created_at: number;
  // GET /v1/cases only (§18.3 [v4.23]): the simulated town's or a real phone's, and each payment's shop.
  simulated?: boolean;
  merchant?: string | null;
  payment_a?: CasePayment | null;
  payment_b?: CasePayment | null;
}

export interface CaseDetail {
  case: CaseSummary & { evidence: Record<string, unknown>; case_file_md: string | null };
  cert: SignedObj | null;
  tag_a: SignedObj | null;
  tag_b: SignedObj | null;
  holder_pub: string | null;
  log_entries: SignedObj[];
}

export interface Proof {
  case_id: number;
  rule: string;
  server_pub: string;
  cert: SignedObj;
  tag_a: SignedObj;
  tag_b: SignedObj;
  holder_pub: string;
  log_entries: SignedObj[];
}

export interface Region {
  region_id: string;
  display_name: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface TownMerchant {
  merchant_id: string;
  display_name: string;
  region_id: string | null;
  x: number;
  y: number;
  simulated: boolean;
  pool_eligible: boolean;
}

export interface Alert {
  alert_id: string;
  region_id: string | null;
  event: string;
  severity: string | null;
  source: "live" | "replayed";
  onset?: number | null;
  expires?: number | null;
}

export interface TownStats {
  seed: number;
  summary?: {
    hours?: number;
    shops?: number;
    residents?: number;
    payments?: number;
    accepted?: number;
    settled?: number;
    refused?: Record<string, number>;
    uploads?: number;
    contacts?: number;
    median_minutes_to_server?: number;
  };
  double_spends: {
    attempts: number;
    share_refused_offline: number | null;
    share_caught_at_settlement: number | null;
    refused_offline?: number;
    accepted_offline?: number;
    caught_at_settlement?: number;
    not_caught_by_end?: number;
  };
  cheaters?: number;
  mean_loss_per_cheater_cents: number | null;
  median_hours_to_settlement: number | null;
  hops_histogram?: Record<string, number>;
  cases?: Record<string, number>;
}

/** GET /v1/town's latest 200 payments, newest first (by the phone's clock). */
export interface TownPayment {
  tag_hash: string;
  merchant_id: string;
  device_ts: number;
  status: string;
  hops: number | null;
  amount_cents: number;
}

export interface TownUpload {
  upload_id: number;
  region_id: string | null;
  item_count: number;
  simulated: boolean;
  at: number;
}

export interface Town {
  grid: { w: number; h: number };
  regions: Region[];
  merchants: TownMerchant[];
  recent_payments: TownPayment[];
  uploads: TownUpload[];
  alerts: Alert[];
  dark_regions: string[];
  town_stats: TownStats | null;
}

export interface RelayPath {
  tag_hash: string;
  merchant: string;
  simulated: boolean;
  amount_cents: number;
  status: string;
  hops: number;
  path: { device: string; at: number; name: string; kind: string; simulated?: boolean }[];
  uploaded_by: string | null;
  paid_at?: number;
  received_at?: number;
  latency_s: number;
}

export interface QuickResult {
  share_refused_offline: number | null;
  share_caught_at_settlement: number | null;
  mean_loss_per_cheater_cents: number | null;
  median_hours_to_settlement: number | null;
  double_spend_attempts: number;
  residents: number;
}

export interface Quick {
  baseline: QuickResult;
  current: QuickResult;
  seconds: number;
}

export interface FlagRow {
  flag_id: number;
  candidate_id: number;
  kind: string;
  severity: "info" | "review" | "urgent";
  subject_id: string;
  subject_name: string | null;
  evidence_ids: string[];
  exposure_cents: number;
  summary: string;
  proposed_action: string;
  citations_valid: boolean;
  status: "open" | "approved" | "rejected" | "dismissed" | "invalid";
  runner: string | null;
  run_id: number | null;
  created_at: number;
  review?: FlagReview | null; // the reviewer's second opinion (§14.7b)
  agents_disagree?: boolean; // a valid agent review didn't agree: open for a person
}

/** What a Droid run cost (droid-sdk Usage), stored with its transcript. */
export interface Usage {
  input_tokens?: number;
  output_tokens?: number;
  cache_read_tokens?: number;
  cache_creation_tokens?: number;
  thinking_tokens?: number;
  factory_credits?: number;
}

export interface Step {
  index: number;
  tool: string;
  input_summary: string;
  ok: boolean | null;
}

export interface FlagDetail {
  flag: FlagRow;
  candidate: { kind: string; window_start: number; window_end: number; features: Record<string, unknown> };
  agent: {
    runner: string;
    run_id: number;
    steps: Step[];
    reasoning: string | null;
    action_params: Record<string, string | number>;
    merchant_notice: string | null;
    missing_citations: string[];
    error: string | null;
    model?: string | null;
    model_requested?: string | null;
    usage?: Usage | null;
  } | null;
}

export interface Run {
  run_id: number;
  job: string;
  runner: string;
  status: string;
  citations_valid: boolean | null;
  started_at: number;
  finished_at: number | null;
  error: string | null;
  transcript?: {
    runner: string;
    steps: Step[];
    missing_citations: string[];
    error: string | null;
    model?: string | null;
    model_requested?: string | null;
    usage?: Usage | null;
  };
}

export interface Message {
  message_id: number;
  merchant_id: string | null;
  resident_id?: string | null; // a resident's thread (FREEZE by text, §17.2)
  flag_id: number | null;
  direction: "in" | "out";
  channel: string;
  body: string;
  created_at: number;
  delivered?: boolean;
}

/** GET /v1/photon/freezes: a cert frozen because its owner texted FREEZE (§17.2). */
export interface OwnerFreeze {
  cert_id: string;
  status: string;
  frozen_at: number | null;
  owner_freeze_at: number;
  resident_id: string;
  display_name: string;
  policy_ver: number | null;
}
