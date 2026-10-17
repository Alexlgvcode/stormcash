import { describe, expect, it } from 'vitest';
import { FrameCollector, toFrames } from '../qrframes';
import type { SyncMessage } from '../session';

describe('QR frames', () => {
  it('reassembles a batch scanned in any order, ignoring repeats', () => {
    const msgs: SyncMessage[] = [{ t: 'WANT', ids: Array.from({ length: 200 }, (_, i) => `id${i}`) }, { t: 'DONE' }];
    const frames = toFrames('b1', msgs);
    expect(frames.length).toBeGreaterThan(2);
    const c = new FrameCollector();
    const order = [...frames].reverse();
    let out: SyncMessage[] | null = null;
    for (const f of [order[0], ...order]) out = c.add(f) ?? out;
    expect(out).toEqual(msgs);
  });
});
