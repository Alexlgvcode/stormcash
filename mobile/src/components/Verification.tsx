// The merchant's six offline checks (§8.2, protocol/rules.ts merchantCheck), shown as a rail,
// plus the evidence they were run on. merchantCheck stops at the first failure, so checks after
// a failure are shown as "not run", never as passed.
import { StyleSheet, Text, View } from 'react-native';
import type { CheckId, CheckResult, Hex, Pay, Tag } from '../protocol';
import { tagHash } from '../protocol';
import { Icon } from './Icon';
import { colors, font, Label, radius, wholeDollars } from './ui';

const CHECKS: { id: CheckId; title: string; what: string }[] = [
  { id: 'C1', title: 'Issued by StormCash', what: "The certificate carries the StormCash server's signature." },
  { id: 'C2', title: 'Certificate is current', what: 'Not expired (10 min clock tolerance) and not on the freeze list this phone holds.' },
  { id: 'C3', title: 'Signed by the wallet', what: "The payment is for this certificate and signed by its holder's key." },
  { id: 'C4', title: 'Answers this request', what: "Matches this shop, this request's code and amount, before the request expired." },
  { id: 'C5', title: 'Within limits', what: "Amount is positive and the wallet's running total stays within its cap and this shop's limit." },
  { id: 'C6', title: 'History is consistent', what: 'No conflict with any payment from this certificate that this phone already holds. A conflict it has not received yet cannot be seen here.' },
];

type State = 'pass' | 'fail' | 'skip';

export function VerificationRail({ result }: { result: CheckResult }) {
  const failedAt = result.ok ? -1 : CHECKS.findIndex((c) => c.id === result.check);
  const state = (i: number): State => (result.ok || i < failedAt ? 'pass' : i === failedAt ? 'fail' : 'skip');
  return (
    <View style={{ gap: 8 }}>
      <Label>Checked on this phone, offline</Label>
      <View style={styles.rail}>
        {CHECKS.map((c, i) => {
          const st = state(i);
          const color = st === 'pass' ? colors.green : st === 'fail' ? colors.red : colors.faint;
          return (
            <View
              key={c.id}
              style={styles.step}
              accessible
              accessibilityLabel={`${c.id}, ${c.title}: ${st === 'pass' ? 'passed' : st === 'fail' ? `failed, ${result.ok ? '' : result.reason}` : 'not run'}`}
            >
              <View style={styles.markCol}>
                <View style={[styles.mark, { borderColor: color, backgroundColor: st === 'skip' ? 'transparent' : color }]}>
                  {st === 'pass' ? <Icon name="check" size={14} color={colors.card} strokeWidth={3} /> : null}
                  {st === 'fail' ? <Icon name="x" size={14} color={colors.card} strokeWidth={3} /> : null}
                </View>
                {i < CHECKS.length - 1 ? <View style={[styles.line, { backgroundColor: st === 'pass' ? colors.green : colors.line }]} /> : null}
              </View>
              <View style={styles.text}>
                <Text style={[styles.title, st === 'skip' && { color: colors.faint }]}>
                  <Text style={styles.id}>{c.id}  </Text>{c.title}
                  {st === 'fail' && !result.ok ? <Text style={{ color: colors.red }}>  ·  {result.reason}</Text> : null}
                  {st === 'skip' ? <Text style={{ color: colors.faint }}>  ·  not run</Text> : null}
                </Text>
                <Text style={styles.what}>{c.what}</Text>
              </View>
            </View>
          );
        })}
      </View>
    </View>
  );
}

const short = (h: Hex | undefined) => (h ? `${h.slice(0, 10)}…${h.slice(-6)}` : '—');

/** The fields the checks read, as selectable text (press and hold to copy). */
export function Evidence({ pay, serverPub, checkedAt, conflict }: { pay: Pay; serverPub: Hex; checkedAt: number; conflict: Tag | null }) {
  const t = pay.t;
  const c = pay.c;
  let th: Hex | undefined;
  try {
    th = tagHash(t);
  } catch {
    th = undefined;
  }
  const time = (s: number) => new Date(s * 1000).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
  const rows: [string, string][] = [
    ['Certificate', `${short(c.cert_id)} · v${c.cert_ver}`],
    ['Issued by (server key)', short(serverPub)],
    ['Wallet key', short(c.holder_pub)],
    ['Cap', wholeDollars(c.cap_cents)],
    ['Expires', time(c.expires_at)],
    ['Amount', wholeDollars(t.amount_cents)],
    ['Running total', wholeDollars(t.cum_cents)],
    ['Copy no.', String(t.counter)],
    ['Previous copy', short(t.prev_hash)],
    ['This copy', short(th)],
    ['Checked at', `${time(checkedAt)} · phone clock`],
  ];
  return (
    <View style={{ gap: 8 }}>
      <Label>Evidence</Label>
      <View style={styles.table}>
        {rows.map(([k, v]) => (
          <View key={k} style={styles.tr}>
            <Text style={styles.k}>{k}</Text>
            <Text selectable style={styles.v}>{v}</Text>
          </View>
        ))}
      </View>
      {conflict ? <Conflict held={conflict} scanned={t} /> : null}
    </View>
  );
}

/** Two signed copies from the same certificate that can't both be honest. */
function Conflict({ held, scanned }: { held: Tag; scanned: Tag }) {
  const col = (label: string, x: Tag) => (
    <View style={styles.conflictCol}>
      <Text style={styles.conflictHead}>{label}</Text>
      <Text style={styles.conflictLine}>Copy no. <Text style={styles.mono}>{x.counter}</Text></Text>
      <Text style={styles.conflictLine}>Amount <Text style={styles.mono}>{wholeDollars(x.amount_cents)}</Text></Text>
      <Text style={styles.conflictLine}>Running total <Text style={styles.mono}>{wholeDollars(x.cum_cents)}</Text></Text>
      <Text selectable style={styles.conflictLine}>Previous <Text style={styles.mono}>{short(x.prev_hash)}</Text></Text>
    </View>
  );
  return (
    <View style={{ gap: 8 }}>
      <Label>Conflicting signed copies</Label>
      <View style={styles.conflict}>
        {col('Already held by this phone', held)}
        {col('Just scanned', scanned)}
      </View>
      <Text style={styles.what}>
        Both copies are signed by the same wallet key. That's proof the money was spent twice, not a risk score. It
        travels with the next phone online, and anyone can check it.
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  rail: { paddingTop: 8 },
  step: { flexDirection: 'row', gap: 12 },
  markCol: { alignItems: 'center', width: 24 },
  mark: { width: 22, height: 22, borderRadius: 11, borderWidth: 2, alignItems: 'center', justifyContent: 'center' },
  line: { width: 2, flex: 1, minHeight: 10, marginVertical: 2 },
  text: { flex: 1, minWidth: 0, paddingBottom: 14, gap: 2 },
  id: { fontFamily: font.bold, color: colors.muted },
  title: { fontFamily: font.bold, fontSize: 16, lineHeight: 22, color: colors.ink },
  what: { fontFamily: font.regular, fontSize: 14, lineHeight: 20, color: colors.muted },
  table: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.line },
  tr: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'space-between', columnGap: 12, paddingVertical: 8, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.line },
  k: { fontFamily: font.regular, fontSize: 14, color: colors.muted },
  v: { fontFamily: 'Menlo', fontSize: 13, color: colors.ink, marginLeft: 'auto', textAlign: 'right' },
  mono: { fontFamily: 'Menlo', fontSize: 13, color: colors.ink },
  conflict: { flexDirection: 'row', gap: 10 },
  conflictCol: { flex: 1, minWidth: 0, backgroundColor: colors.redSoft, borderRadius: radius.lg, padding: 12, gap: 4 },
  conflictHead: { fontFamily: font.bold, fontSize: 14, color: colors.red },
  conflictLine: { fontFamily: font.regular, fontSize: 14, color: colors.ink },
});
