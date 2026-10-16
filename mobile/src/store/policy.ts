// Latest verified policy (§7.4 POLICY). Callers verify the server signature first.
import type { Policy } from '../protocol';
import { getDb } from './db';
import { putItem } from './items';

export function currentPolicy(): Policy | null {
  const r = getDb().getFirstSync<{ policy_json: string }>('SELECT policy_json FROM policy WHERE id = 1');
  return r ? (JSON.parse(r.policy_json) as Policy) : null;
}

/** Keeps the highest policy_ver seen. Returns true if this one replaced the stored one. */
export function savePolicyIfNewer(p: Policy): boolean {
  const cur = currentPolicy();
  if (cur && cur.policy_ver >= p.policy_ver) return false;
  getDb().runSync(
    'INSERT OR REPLACE INTO policy (id, policy_ver, policy_json) VALUES (1, ?, ?)',
    p.policy_ver, JSON.stringify(p),
  );
  putItem('POLICY', p);
  return true;
}
