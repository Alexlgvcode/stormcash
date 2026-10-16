// QR sync framing (§10.7): a batch of sync messages split into numbered QR frames.
import { QR_PREFIX } from '../protocol';
import type { SyncMessage } from './session';

const CHUNK = 500; // characters of payload per frame; small enough to scan quickly

interface Frame { q: 'qs'; b: string; i: number; n: number; d: string }

export function toFrames(batchId: string, msgs: SyncMessage[]): string[] {
  const payload = JSON.stringify(msgs);
  const n = Math.max(1, Math.ceil(payload.length / CHUNK));
  return Array.from({ length: n }, (_, i) =>
    QR_PREFIX + JSON.stringify({ q: 'qs', b: batchId, i, n, d: payload.slice(i * CHUNK, (i + 1) * CHUNK) } satisfies Frame),
  );
}

/** Collects frames of one batch; returns the messages once every frame is in. */
export class FrameCollector {
  private batch: string | null = null;
  private parts: string[] = [];
  private got = 0;
  total = 0;

  get received(): number { return this.got; }

  add(qr: string): SyncMessage[] | null {
    let f: Frame;
    try {
      f = JSON.parse(qr.slice(QR_PREFIX.length)) as Frame;
    } catch {
      return null;
    }
    if (f.q !== 'qs') return null;
    if (f.b !== this.batch) {
      this.batch = f.b;
      this.parts = new Array(f.n);
      this.got = 0;
      this.total = f.n;
    }
    if (this.parts[f.i] === undefined) {
      this.parts[f.i] = f.d;
      this.got++;
    }
    if (this.got < this.total) return null;
    return JSON.parse(this.parts.join('')) as SyncMessage[];
  }
}
