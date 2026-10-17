// Three phones, each with its own database: Pharmacy ↔ Maya ↔ Gas Station (§10.6).
// The pharmacy's tag reaches the gas station only through Maya, and a rolled-back payment is refused.
import { describe, expect, it } from 'vitest';
import { deviceShortId, logTamper, publicKeyOf, signObject, tagHash, type Cert, type MCert } from '../../protocol';
import { createRequest, payQr, receivePayment, signPayment } from '../../payments';
import { __useDatabase, resetDb } from '../../store/db';
import { logEntries } from '../../store/devicelog';
import { getItem, itemsOfKind, putItem } from '../../store/items';
import { rollBack, saveCertVersion } from '../../store/wallet';
import { SyncSession, type SessionResult, type SyncMessage } from '../session';

const SERVER = '11'.repeat(32);
const serverPub = publicKeyOf(SERVER);
const key = (b: string) => ({ priv: b.repeat(32), pub: publicKeyOf(b.repeat(32)) });
const maya = key('22'), pharm = key('33'), gas = key('44');
const NOW = 1760000000;
let clock = NOW;

const cert = signObject<Cert>('CERT', {
  cert_id: 'ab'.repeat(16), cert_ver: 1, holder_pub: maya.pub, cap_cents: 5000,
  issued_at: NOW, expires_at: NOW + 72 * 3600, escrow_ref: 'e',
}, SERVER);
const mcert = (id: string, pub: string, name: string) => signObject<MCert>('MCERT', {
  merchant_id: id.repeat(16), merchant_ver: 1, merchant_pub: pub, display_name: name,
  region_id: 'asheville-downtown', expires_at: NOW + 86400,
}, SERVER);

function on<T>(phone: string, f: () => T): T {
  __useDatabase(phone);
  return f();
}

/** Runs one session between two phones over an in-memory message queue. */
function sync(a: { db: string; k: typeof maya; label: string }, b: { db: string; k: typeof maya; label: string }) {
  const queue: { to: 'a' | 'b'; msg: SyncMessage }[] = [];
  const results: Record<string, SessionResult | null> = {};
  const mk = (side: 'a' | 'b', p: typeof a) =>
    new SyncSession(
      { send: (msg) => queue.push({ to: side === 'a' ? 'b' : 'a', msg: JSON.parse(JSON.stringify(msg)) }) },
      { ...p.k, role: 'x', label: p.label }, serverPub, () => clock, (r) => { results[side] = r; },
    );
  const sa = mk('a', a), sb = mk('b', b);
  on(a.db, () => sa.start());
  on(b.db, () => sb.start());
  while (queue.length) {
    const { to, msg } = queue.shift()!;
    on(to === 'a' ? a.db : b.db, () => (to === 'a' ? sa : sb).handle(msg));
  }
  return results;
}

describe('sync session', () => {
  it('relays the pharmacy tag through Maya and the gas station refuses the rollback', () => {
    for (const p of ['maya', 'pharm', 'gas']) on(p, () => resetDb());
    const pharmCert = mcert('a1', pharm.pub, 'Pharmacy');
    const gasCert = mcert('b2', gas.pub, 'Gas Station');
    const M = { db: 'maya', k: maya, label: 'MAYA' };
    const P = { db: 'pharm', k: pharm, label: 'PHARMACY' };
    const G = { db: 'gas', k: gas, label: 'GAS_STATION' };

    // Maya pays the pharmacy.
    on('maya', () => saveCertVersion(cert, 'k'));
    const req1 = on('pharm', () => createRequest(pharmCert, 1200, pharm, clock));
    const pay1 = on('maya', () => signPayment(req1, maya, clock));
    expect(on('pharm', () => receivePayment(payQr(pay1), pharmCert, pharm, serverPub, clock))).toMatchObject({
      result: { ok: true },
    });

    // Maya walks past the pharmacy, then the gas station (they never link directly).
    clock += 60;
    const r1 = sync(M, P);
    expect(r1.a?.contactId).toBe(r1.b?.contactId);
    expect(r1.a?.received).toBeGreaterThan(0);
    clock += 60;
    sync(M, G);
    const th = tagHash(pay1.t);
    const atGas = on('gas', () => getItem(th));
    expect(atGas?.kind).toBe('PAY');
    // path: pharmacy created it, Maya carried it, the gas station received it
    expect(atGas?.path.map((h) => h[0])).toEqual([pharm.pub, maya.pub, gas.pub].map(deviceShortId));

    // Judge rolls Maya back and tries to spend the same money at the gas station.
    on('maya', () => rollBack('reuse'));
    const req2 = on('gas', () => createRequest(gasCert, 1500, gas, clock));
    const pay2 = on('maya', () => signPayment(req2, maya, clock));
    expect(on('gas', () => receivePayment(payQr(pay2), gasCert, gas, serverPub, clock))).toMatchObject({
      result: { ok: false, check: 'C6', rule: 'SAME_COUNTER' },
    });
    expect(on('gas', () => itemsOfKind('PROOF'))).toHaveLength(1);

    // Every phone logged its contacts in a valid chain.
    for (const p of ['maya', 'pharm', 'gas']) {
      expect(on(p, () => logTamper(logEntries(100)))).toBeNull();
    }
    expect(on('maya', () => logEntries().filter((e) => e.kind === 'CONTACT'))).toHaveLength(2);
  });

  it('drops invalid items and stops trusting the peer', () => {
    on('x', () => resetDb());
    on('y', () => resetDb());
    const forged = signObject<Cert>('CERT', { ...cert, cert_ver: 9, sig: undefined }, maya.priv); // not the server
    on('x', () => { saveCertVersion(cert, 'k'); });
    on('y', () => { saveCertVersion(cert, 'k'); });
    // put the forged cert straight into y's items table as if it were carried
    on('y', () => putItem('CERT', forged));
    const r = sync({ db: 'x', k: maya, label: 'MAYA' }, { db: 'y', k: gas, label: 'GAS_STATION' });
    expect(r.a?.rejected).toBe(1);
    expect(on('x', () => itemsOfKind('CERT'))).toHaveLength(0);
  });
});
