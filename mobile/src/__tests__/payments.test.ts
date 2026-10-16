// End-to-end offline flow over one shared test database: register-equivalent setup,
// pay the pharmacy, roll back (judge mode), carry the tag, pay the gas station → refused.
import { beforeEach, describe, expect, it } from 'vitest';
import {
  publicKeyOf, signObject, tagHash, type Cert, type MCert,
} from '../protocol';
import { createRequest, payQr, preparePayment, receivePayment, requestQr, signPayment } from '../payments';
import { resetDb } from '../store/db';
import { itemsOfKind, putItem } from '../store/items';
import { logEntries } from '../store/devicelog';
import { rollBack, saveCertVersion } from '../store/wallet';
import { saveMerchantCert, setOpenRequest } from '../store/merchant';

const SERVER = '11'.repeat(32);
const serverPub = publicKeyOf(SERVER);
const maya = { priv: '22'.repeat(32), pub: publicKeyOf('22'.repeat(32)) };
const pharm = { priv: '33'.repeat(32), pub: publicKeyOf('33'.repeat(32)) };
const gas = { priv: '44'.repeat(32), pub: publicKeyOf('44'.repeat(32)) };
const NOW = 1760000000;

const cert = signObject<Cert>('CERT', {
  cert_id: 'ab'.repeat(16), cert_ver: 2, holder_pub: maya.pub, cap_cents: 5000,
  issued_at: NOW, expires_at: NOW + 72 * 3600, escrow_ref: 'escrow-maya',
}, SERVER);
const mcert = (id: string, pub: string, name: string) => signObject<MCert>('MCERT', {
  merchant_id: id.repeat(16), merchant_ver: 1, merchant_pub: pub, display_name: name,
  region_id: 'asheville-downtown', expires_at: NOW + 30 * 86400,
}, SERVER);
const pharmCert = mcert('a1', pharm.pub, 'Pharmacy');
const gasCert = mcert('b2', gas.pub, 'Gas Station');

// The tests share one database, so each "phone" is simulated by swapping state in order.
beforeEach(() => resetDb());

describe('offline payment', () => {
  it('pays, then a rolled-back wallet is refused with SAME_COUNTER', () => {
    saveCertVersion(cert, 'k');

    // Pharmacy charges $12; Maya pays.
    const req1 = createRequest(pharmCert, 1200, pharm, NOW);
    const prep = preparePayment(requestQr(req1), serverPub, NOW + 5);
    expect(prep.ok).toBe(true);
    const pay1 = signPayment((prep as { request: typeof req1 }).request, maya, NOW + 10);
    const r1 = receivePayment(payQr(pay1), pharmCert, pharm, serverPub, NOW + 15);
    expect(r1).toMatchObject({ parsed: true, result: { ok: true } });
    expect(logEntries()[0]).toMatchObject({ kind: 'ACCEPT', tag_hash: tagHash(pay1.t) });

    // Judge mode: reuse the money, then pay the gas station, which holds the pharmacy's tag.
    expect(rollBack('reuse')).toBe(true);
    setOpenRequest(null);
    const req2 = createRequest(gasCert, 1500, gas, NOW + 60);
    const pay2 = signPayment(req2, maya, NOW + 65);
    expect(pay2.t.counter).toBe(1);
    putItem('TAG', pay1.t); // gossip delivered it (already held here)
    const r2 = receivePayment(payQr(pay2), gasCert, gas, serverPub, NOW + 70);
    expect(r2).toMatchObject({ parsed: true, result: { ok: false, check: 'C6', rule: 'SAME_COUNTER' } });
    expect(itemsOfKind('PROOF')).toHaveLength(1);
    expect(logEntries()[0]).toMatchObject({ kind: 'REFUSE', check: 'C6' });
  });

  it('be clever: skipping the counter is refused with BROKEN_LINK', () => {
    saveCertVersion(cert, 'k');
    const pay1 = signPayment(createRequest(pharmCert, 1200, pharm, NOW), maya, NOW);
    expect(rollBack('clever')).toBe(true);
    const req2 = createRequest(gasCert, 1500, gas, NOW + 60);
    const pay2 = signPayment(req2, maya, NOW + 65);
    expect(pay2.t.counter).toBe(2);
    putItem('TAG', pay1.t);
    const r2 = receivePayment(payQr(pay2), gasCert, gas, serverPub, NOW + 70);
    expect(r2).toMatchObject({ parsed: true, result: { ok: false, check: 'C6', rule: 'BROKEN_LINK' } });
  });

  it('the payer refuses an over-limit request', () => {
    saveCertVersion(cert, 'k');
    const req = createRequest(pharmCert, 6000, pharm, NOW);
    expect(preparePayment(requestQr(req), serverPub, NOW)).toEqual({ ok: false, message: 'Over your limit' });
  });

  it('a payment for a different request is refused with C4', () => {
    saveCertVersion(cert, 'k');
    saveMerchantCert(pharmCert);
    const pay = signPayment(createRequest(pharmCert, 1200, pharm, NOW), maya, NOW);
    createRequest(pharmCert, 1200, pharm, NOW + 1); // a newer request replaced it
    const r = receivePayment(payQr(pay), pharmCert, pharm, serverPub, NOW + 2);
    expect(r).toMatchObject({ parsed: true, result: { ok: false, check: 'C4' } });
  });
});
