// Photon sender (spec §17, WS7). Spectrum's messaging SDK is TypeScript-only, so the Python server
// asks this small process to send; inbound webhooks go straight to POST /v1/photon/inbound.
//
//   POST /send   {channel: "telegram", handle: "<telegram user id>", text}   → {ok: true}
//   GET  /health → {ok: true}
//
// Auth: header `Authorization: Bearer $PHOTON_BRIDGE_TOKEN`. Listens on 127.0.0.1 only.
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import { Spectrum } from 'spectrum-ts';
import { telegram } from 'spectrum-ts/providers/telegram';

const PORT = Number(process.env.PHOTON_BRIDGE_PORT ?? 8787);
const TOKEN = process.env.PHOTON_BRIDGE_TOKEN ?? '';
const MAX_BODY = 16 * 1024;

if (!TOKEN) throw new Error('PHOTON_BRIDGE_TOKEN is required');

const app = await Spectrum({
  projectId: process.env.PROJECT_ID!,
  projectSecret: process.env.PROJECT_SECRET!,
  providers: [telegram.config({ botToken: process.env.TELEGRAM_BOT_TOKEN! })],
});
const tg = telegram(app);

async function send(channel: string, handle: string, text: string): Promise<void> {
  if (channel !== 'telegram') throw new Error(`unsupported channel ${channel}`);
  const user = await tg.user(String(handle)); // Telegram ids are stringified (Photon docs)
  const space = await tg.space.create(user);
  await space.send(text);
}

function readBody(req: IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks: Buffer[] = [];
    req.on('data', (c: Buffer) => {
      size += c.length;
      if (size > MAX_BODY) reject(new Error('body too large'));
      else chunks.push(c);
    });
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    req.on('error', reject);
  });
}

function reply(res: ServerResponse, status: number, body: object): void {
  res.writeHead(status, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(body));
}

createServer(async (req, res) => {
  try {
    if (req.method === 'GET' && req.url === '/health') return reply(res, 200, { ok: true });
    if (req.method !== 'POST' || req.url !== '/send') return reply(res, 404, { ok: false, error: 'not found' });
    if (req.headers.authorization !== `Bearer ${TOKEN}`) return reply(res, 401, { ok: false, error: 'unauthorized' });
    const { channel, handle, text } = JSON.parse(await readBody(req)) as Record<string, unknown>;
    if (typeof channel !== 'string' || typeof handle !== 'string' || typeof text !== 'string' || !text) {
      return reply(res, 400, { ok: false, error: 'channel, handle and text are required strings' });
    }
    await send(channel, handle, text);
    return reply(res, 200, { ok: true });
  } catch (e) {
    return reply(res, 502, { ok: false, error: e instanceof Error ? e.message : String(e) });
  }
}).listen(PORT, '127.0.0.1', () => console.log(`photon bridge on 127.0.0.1:${PORT}`));
