// Payment flows on top of the protocol and the stores (§8.1, §8.2).
// Keys and clocks are passed in so the flows run in tests without native modules.
import {
  detailsHash, fromQr, makeProof, merchantCheck, payerChecks, payFromWire, payToWire, randomHex,
  requestFromWire, requestToWire, signObject, tagHash, toQr, verifyObject,
  type CheckResult, type Det, type Hex, type MCert, type Pay, type PaymentRequest, type Req, type Tag,
} from './protocol';
import { appendLog } from './store/devicelog';
import { putItem, tagsForCert } from './store/items';
import { openRequest, setOpenRequest } from './store/merchant';
import { currentPolicy } from './store/policy';
import { commitPayment, latestCert, walletState } from './store/wallet';

export interface Keys { priv: Hex; pub: Hex }

export const REQ_TTL_S = 120;

// ---- Merchant: create a request (Charge screen) ----

export function createRequest(mc: MCert, amountCents: number, keys: Keys, now: number): PaymentRequest {
  const rq = signObject<Req>('REQ', {
    merchant_id: mc.merchant_id, amount_cents: amountCents, nonce: randomHex(16), req_expires_at: now + REQ_TTL_S,
  }, keys.priv);
  setOpenRequest(rq);
  return { mc, rq };
}

export const requestQr = (r: PaymentRequest): string => toQr(requestToWire(r));

// ---- Resident: check a request, then sign (Pay screen) ----

export type PayerPrep =
  | { ok: true; request: PaymentRequest }
  | { ok: false; message: string };

const PAYER_COPY: Record<string, string> = {
  MCERT_INVALID: 'This shop is not registered with StormCash.',
  MCERT_EXPIRED: "This shop's registration has expired.",
  REQ_INVALID: "This request wasn't signed by the shop.",
  REQ_EXPIRED: 'This request has expired. Ask the shop for a new code.',
  OVER_LIMIT: 'Over your limit',
};

export function preparePayment(qr: string, serverPub: Hex, now: number): PayerPrep {
  let request: PaymentRequest;
  try {
    request = requestFromWire(fromQr(qr));
  } catch {
    return { ok: false, message: 'Not a StormCash payment request.' };
  }
  const cert = latestCert();
  const state = walletState();
  if (!cert || !state) return { ok: false, message: 'No certificate on this phone.' };
  const r = payerChecks(request.mc, request.rq, serverPub, now, cert.cap_cents, state.cumCents);
  return r.ok ? { ok: true, request } : { ok: false, message: PAYER_COPY[r.reason] };
}

/** Builds DET, TAG and PAY and persists the wallet before returning (§8.1 step 4). */
export function signPayment(request: PaymentRequest, keys: Keys, now: number): Pay {
  const cert = latestCert();
  const before = walletState();
  if (!cert || !before) throw new Error('No certificate on this phone');
  const amount = request.rq.amount_cents;
  const d: Det = { merchant_pub: request.mc.merchant_pub, nonce: request.rq.nonce, ts: now };
  const t = signObject<Tag>('TAG', {
    cert_id: cert.cert_id,
    counter: before.counter + 1,
    prev_hash: before.chainHead,
    amount_cents: amount,
    cum_cents: before.cumCents + amount,
    details_hash: detailsHash(d),
  }, keys.priv);
  // The payer does not gossip its own tag: the shop must see this PAY first, or C6 would
  // refuse it as COUNTER_NOT_NEW. The shop's PAY travels on from there (§10.1).
  commitPayment(t, before);
  return { c: cert, t, d };
}

export const payQr = (p: Pay): string => toQr(payToWire(p));

// ---- Merchant: verify a scanned payment (Scan payment → Result) ----

export type Received =
  | { parsed: false; message: string }
  | { parsed: true; pay: Pay; result: CheckResult };

export function receivePayment(qr: string, mc: MCert, keys: Keys, serverPub: Hex, now: number): Received {
  let pay: Pay;
  try {
    pay = payFromWire(fromQr(qr));
  } catch {
    return { parsed: false, message: 'Not a StormCash payment code.' };
  }
  // Bare gossiped tags arrive without their cert, so only count those signed by this holder.
  const held = tagsForCert(pay.t.cert_id).filter((x) => verifyObject('TAG', x, pay.c.holder_pub));
  const req = openRequest();
  const result: CheckResult = req
    ? merchantCheck(pay, { serverPub, merchant: mc, req, policy: currentPolicy(), storedTags: held, now })
    : { ok: false, check: 'C4', reason: 'WRONG_NONCE', rule: null, conflict: null }; // no open request

  let th: Hex | null = null;
  try {
    th = tagHash(pay.t);
  } catch {
    th = null; // fields don't even render; nothing to log
  }

  if (result.ok) {
    putItem('PAY', pay, [], now);
    appendLog({
      kind: 'ACCEPT', tag_hash: th!, cert_id: pay.t.cert_id,
      held_ids: held.map(tagHash).filter((h) => h !== th),
    }, keys.pub, keys.priv, now);
    setOpenRequest(null);
  } else if (th) {
    if (result.check === 'C6') {
      putItem('PAY', pay, [], now); // evidence
      const proof = result.conflict ? makeProof(result.conflict, pay.t) : null;
      if (proof) putItem('PROOF', proof, [], now);
    }
    appendLog({ kind: 'REFUSE', tag_hash: th, cert_id: pay.t.cert_id, check: result.check }, keys.pub, keys.priv, now);
  }
  return { parsed: true, pay, result };
}
