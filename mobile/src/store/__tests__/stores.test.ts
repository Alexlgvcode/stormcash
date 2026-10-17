import { beforeEach, describe, expect, it } from 'vitest';
import {
  detailsHash, genesis, publicKeyOf, signObject, tagHash, verifyDlog, logTamper,
  type Cert, type Pay, type Tag,
} from '../../protocol';
import { resetDb } from '../db';
import { commitPayment, latestCert, rollBack, saveCertVersion, walletState } from '../wallet';
import { countsByKind, inventory, markReceipted, putItem, tagsForCert } from '../items';
import { appendLog, logEntries } from '../devicelog';
import { currentPolicy, savePolicyIfNewer } from '../policy';

const MAYA = '22'.repeat(32);
const mayaPub = publicKeyOf(MAYA);
const CERT_ID = 'ab'.repeat(16);
const cert: Cert = {
  cert_id: CERT_ID, cert_ver: 1, holder_pub: mayaPub, cap_cents: 5000,
  issued_at: 0, expires_at: 9e9, escrow_ref: 'e', sig: '00'.repeat(64),
};

function spend(amount: number): Tag {
  const s = walletState()!;
  const tag = signObject<Tag>('TAG', {
    cert_id: CERT_ID, counter: s.counter + 1, prev_hash: s.chainHead, amount_cents: amount,
    cum_cents: s.cumCents + amount,
    details_hash: detailsHash({ merchant_pub: mayaPub, nonce: '01'.repeat(16), ts: 1 }),
  }, MAYA);
  commitPayment(tag, s);
  return tag;
}

beforeEach(() => resetDb());

describe('wallet', () => {
  it('starts at genesis and advances', () => {
    saveCertVersion(cert, 'k');
    expect(walletState()).toMatchObject({ counter: 0, cumCents: 0, chainHead: genesis(CERT_ID) });
    const t = spend(1200);
    expect(walletState()).toMatchObject({ counter: 1, cumCents: 1200, chainHead: tagHash(t) });
    saveCertVersion({ ...cert, cert_ver: 2 }, 'k');
    expect(latestCert()?.cert_ver).toBe(2);
    expect(walletState()?.counter).toBe(1);
  });

  it('judge mode reuse restores the same counter and total', () => {
    saveCertVersion(cert, 'k');
    spend(500);
    const before = walletState()!;
    spend(1200);
    expect(rollBack('reuse')).toBe(true);
    expect(walletState()).toMatchObject({ counter: 1, cumCents: 500, chainHead: before.chainHead });
  });

  it('judge mode clever skips the counter', () => {
    saveCertVersion(cert, 'k');
    spend(1200);
    expect(rollBack('clever')).toBe(true);
    expect(walletState()).toMatchObject({ counter: 1, cumCents: 0, chainHead: genesis(CERT_ID) });
    const next = spend(800);
    expect(next.counter).toBe(2);
    expect(next.prev_hash).toBe(genesis(CERT_ID));
  });

  it('rollback with nothing spent is a no-op', () => {
    saveCertVersion(cert, 'k');
    expect(rollBack('reuse')).toBe(false);
  });
});

describe('items', () => {
  it('dedupes, upgrades TAG to PAY, collects tags for a cert, and receipts', () => {
    saveCertVersion(cert, 'k');
    const t = spend(1200);
    const pay: Pay = { c: cert, t, d: { merchant_pub: mayaPub, nonce: '01'.repeat(16), ts: 1 } };
    expect(putItem('TAG', t).isNew).toBe(true);
    expect(putItem('TAG', t).isNew).toBe(false);
    const { id } = putItem('PAY', pay);
    expect(countsByKind()).toEqual({ PAY: 1 });
    expect(tagsForCert(CERT_ID)).toHaveLength(1);
    expect(inventory()).toEqual([id.slice(0, 16)]);
    markReceipted([id]);
    expect(countsByKind()).toEqual({});
  });
});

describe('device log and policy', () => {
  it('chains entries and stores them as items', () => {
    const e1 = appendLog({ kind: 'REFUSE', tag_hash: 'aa'.repeat(32), cert_id: CERT_ID, check: 'C6' }, mayaPub, MAYA, 10);
    const e2 = appendLog({ kind: 'ACCEPT', tag_hash: 'bb'.repeat(32), cert_id: CERT_ID, held_ids: [] }, mayaPub, MAYA, 11);
    expect(e2.seq).toBe(2);
    expect(verifyDlog(e1) && verifyDlog(e2)).toBe(true);
    expect(logTamper(logEntries())).toBeNull();
    expect(countsByKind()).toEqual({ DLOG: 2 });
  });

  it('keeps only the highest policy version', () => {
    const p = { policy_ver: 2, issued_at: 0, frozen_certs: [], merchant_limits: [] };
    expect(savePolicyIfNewer(p)).toBe(true);
    expect(savePolicyIfNewer({ ...p, policy_ver: 1 })).toBe(false);
    expect(currentPolicy()?.policy_ver).toBe(2);
  });
});
