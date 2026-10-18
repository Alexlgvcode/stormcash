// Plain words for the dashboard (issue #93): what a judge reads instead of our
// internal names. Detector kinds, proposed actions, severities, the agent's
// tool calls, and server-built labels that still carry an internal name.
// No imports, so `npm test` runs this file directly.

export const KIND_PLAIN: Record<string, string> = {
  merchant_silence: "Shop went quiet",
  cap_drain: "Wallet drained fast",
  region_dark: "Area went dark",
  none: "Dismissed",
};

export const ACTION_PLAIN: Record<string, string> = {
  hold_pool_payout: "Hold guarantee-pool payouts",
  lower_merchant_limit: "Lower the shop's per-payment limit",
  freeze_cert: "Freeze the wallet",
  dispatch_relay: "Send a relay",
  none: "No action",
};

export const SEVERITY_PLAIN: Record<string, string> = { urgent: "Urgent", review: "Needs review", info: "For information" };

// What each of the agent's tools does, in a few words.
const TOOL_PLAIN: Record<string, string> = {
  ToolSearch: "Loaded its tools",
  get_candidate: "Read the suspicion",
  get_case: "Read the case",
  get_cert_chain: "Read the wallet's certificates",
  get_contacts: "Read the contact log",
  get_device_log: "Read the device log",
  get_merchant_payments: "Read the shop's payments",
  get_messages: "Read the messages", // retired with Photon (spec v4.24); stored runs still show it
  get_nessie_balances: "Read the Nessie balances",
  get_region_status: "Checked the area's status",
  query_features: "Asked Chalk for features",
  verify_tags: "Re-checked the signatures",
  list_dir: "Listed the sandbox files",
  run_tests: "Ran the tests",
  run_eval: "Ran the eval",
  Create: "Wrote a file",
  Edit: "Edited a file",
  Read: "Read a file",
};

/** "Read the shop's payments" for get_merchant_payments; an unknown tool keeps its name. */
export function toolPlain(tool: string): string {
  return TOOL_PLAIN[tool] ?? TOOL_PLAIN[tool.split("___").at(-1) ?? ""] ?? tool;
}

/** A server-built label ("candidate #16 · merchant_silence · Corner Store") in plain words. */
export function plainText(text: string): string {
  return text
    .replace(/\bcandidate #/g, "suspicion #")
    .replace(/\b(merchant_silence|cap_drain|region_dark)\b/g, (k) => KIND_PLAIN[k].toLowerCase())
    .replace(/\b(hold_pool_payout|lower_merchant_limit|freeze_cert|dispatch_relay)\b/g, (a) => ACTION_PLAIN[a].toLowerCase());
}
