// Side effects of server-originated items arriving by gossip or upload (§10.1, §10.5).
import { KEY_REF } from '../config';
import type { Cert, Hex, ItemBody, ItemKind, Policy, Rcpt } from '../protocol';
import { putItem, markReceipted, type PathHop } from '../store/items';
import { savePolicyIfNewer } from '../store/policy';
import { latestCert, saveCertVersion } from '../store/wallet';

/** Stores a verified item and applies it. Returns the item id and whether it was new. */
export function storeVerified(kind: ItemKind, body: ItemBody, path: PathHop[], now: number): { id: Hex; isNew: boolean } {
  if (kind === 'POLICY') savePolicyIfNewer(body as Policy);
  if (kind === 'CERT') {
    const c = body as Cert;
    const mine = latestCert();
    if (mine && mine.cert_id === c.cert_id && c.cert_ver > mine.cert_ver) saveCertVersion(c, KEY_REF);
  }
  const r = putItem(kind, body, path, now);
  if (kind === 'RCPT') markReceipted((body as Rcpt).item_ids);
  return r;
}
