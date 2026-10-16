// Thin client for the StormCash API (spec §12). In dev the Vite proxy serves
// /v1; a deployed build sets VITE_API_BASE to the server's URL.
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

export const operatorPost = <T>(path: string, body: unknown = {}) =>
  request<T>(path, {
    method: "POST",
    headers: { "content-type": "application/json", "X-SC-Operator": "dashboard" },
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
