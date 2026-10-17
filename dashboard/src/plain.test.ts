// Plain words instead of internal names.
import assert from "node:assert/strict";
import { test } from "node:test";
import { plainText, toolPlain } from "./plain.ts";

test("server-built labels lose their internal names", () => {
  assert.equal(plainText("candidate #16 · merchant_silence · Corner Store"), "suspicion #16 · shop went quiet · Corner Store");
  assert.equal(plainText("detector for region_dark"), "detector for area went dark");
  assert.equal(plainText("propose hold_pool_payout"), "propose hold guarantee-pool payouts");
  assert.equal(plainText("case #82"), "case #82");
});

test("tool calls in a few words; unknown tools keep their name", () => {
  assert.equal(toolPlain("get_merchant_payments"), "Read the shop's payments");
  assert.equal(toolPlain("query_features"), "Asked Chalk for features");
  assert.equal(toolPlain("mcp__stormdesk___verify_tags"), "Re-checked the signatures");
  assert.equal(toolPlain("something_new"), "something_new");
});
