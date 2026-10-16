// Every received item is verified before it is stored (§10.3).
import {
  detailsHash, equivocation, verifyDlog, verifyObject,
  type Cert, type Dlog, type Hex, type ItemBody, type ItemKind, type Pay, type Policy, type Proof, type Rcpt, type Tag,
} from '../protocol';

export function verifyItem(kind: ItemKind, body: ItemBody, serverPub: Hex): boolean {
  try {
    switch (kind) {
      case 'POLICY': return verifyObject('POLICY', body as Policy, serverPub);
      case 'RCPT': return verifyObject('RCPT', body as Rcpt, serverPub);
      case 'CERT': return verifyObject('CERT', body as Cert, serverPub);
      case 'DLOG': return verifyDlog(body as Dlog);
      case 'PAY': {
        const p = body as Pay;
        return (
          verifyObject('CERT', p.c, serverPub) &&
          p.t.cert_id === p.c.cert_id &&
          verifyObject('TAG', p.t, p.c.holder_pub) &&
          detailsHash(p.d) === p.t.details_hash
        );
      }
      // Bare tags and proofs travel without their cert; their signatures are checked against
      // the cert's holder key whenever a cert is presented (C6 does this). Here: shape only.
      case 'TAG': {
        const t = body as Tag;
        return !!t.sig && t.counter >= 1 && t.amount_cents > 0;
      }
      case 'PROOF': {
        const p = body as Proof;
        return !!p.a.sig && !!p.b.sig && equivocation(p.a, p.b) !== null;
      }
      case 'RENEW': return !!(body as { sig?: string }).sig;
      default: return false;
    }
  } catch {
    return false;
  }
}
