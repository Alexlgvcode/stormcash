// The store's iPad checkout, counter-POS style: ring up on the left, the check on the right
// (total → customer's code → scan → stamp → new sale), today's sales under the check. Same
// request signing, scanner, C1–C6 and takings as the phone flow (Charge → Result), one screen.
import * as Haptics from 'expo-haptics';
import { useEffect, useReducer, useState, type ReactNode } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Header } from '../components/Header';
import { Icon } from '../components/Icon';
import { QrCode } from '../components/QrCode';
import { Radar } from '../components/Radar';
import { Scanner } from '../components/Scanner';
import { Evidence, VerificationRail } from '../components/Verification';
import { Button, colors, ErrorNote, font, isDark, Label, Meter, Muted, radius, wholeDollars } from '../components/ui';
import { useTick } from '../hooks';
import { deviceKey } from '../keys';
import { useNav } from '../nav';
import { createRequest, receivePayment, REQ_TTL_S, requestQr } from '../payments';
import type { CheckResult, Pay, PaymentRequest } from '../protocol';
import { getServerPub } from '../settings';
import { nowS } from '../store/items';
import { merchantCert, setOpenRequest } from '../store/merchant';
import { takings, takingsTotals } from '../store/takings';
import { syncManager } from '../sync/manager';
import { refusalCopy } from './ResultScreen';

type Stage =
  | { s: 'entry' }
  | { s: 'request'; request: PaymentRequest; qr: string }
  | { s: 'scan'; request: PaymentRequest }
  | { s: 'result'; result: CheckResult; pay: Pay; checkedAt: number };

const KEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', 'C', '0', '⌫'];
const QUICK = [5, 10, 12, 20];
const MAX_DOLLARS = 999;

export function CheckoutScreen() {
  const nav = useNav();
  const { width, height } = useWindowDimensions();
  const [amount, setAmount] = useState(0);
  const [stage, setStage] = useState<Stage>({ s: 'entry' });
  const [error, setError] = useState<string | null>(null);
  const [scanKey, setScanKey] = useState(0);
  const [, rerender] = useReducer((x: number) => x + 1, 0);
  useEffect(() => syncManager.subscribe(rerender), []);
  const now = Math.floor(useTick(1000) / 1000);
  const mc = merchantCert();
  if (!mc) return null;

  const busy = stage.s !== 'entry' && stage.s !== 'result';
  const checkW = Math.min(440, Math.round(width * 0.4));
  const qrSize = Math.round(Math.min(checkW - 2 * 24 - 32, height * 0.34)); // fits a landscape check with room to spare
  const totals = takingsTotals(takings(100));

  const press = (k: string) => {
    if (busy) return;
    Haptics.selectionAsync().catch(() => {});
    if (stage.s === 'result') setStage({ s: 'entry' });
    if (k === '⌫') setAmount((a) => Math.floor(a / 10));
    else if (k === 'C') setAmount(0);
    else setAmount((a) => Math.min(MAX_DOLLARS, Number(String(a) + k)));
  };
  const charge = () => {
    const request = createRequest(mc, amount * 100, deviceKey(), nowS());
    setError(null);
    setStage({ s: 'request', request, qr: requestQr(request) });
  };
  const cancel = () => {
    setOpenRequest(null);
    setStage({ s: 'entry' });
  };
  const newSale = () => {
    setAmount(0);
    setStage({ s: 'entry' });
  };
  const onScan = (data: string) => {
    const r = receivePayment(data, mc, deviceKey(), getServerPub(), nowS());
    if (!r.parsed) {
      setError(r.message);
      setScanKey((k) => k + 1);
      return;
    }
    setError(null);
    Haptics.notificationAsync(r.result.ok ? Haptics.NotificationFeedbackType.Success : Haptics.NotificationFeedbackType.Error).catch(() => {});
    setStage({ s: 'result', result: r.result, pay: r.pay, checkedAt: nowS() });
  };

  // ---- Left: ring up, or the checks behind the last result ----
  const left =
    stage.s === 'result' ? (
      <ScrollView contentContainerStyle={{ gap: 20, paddingBottom: 24 }}>
        <VerificationRail result={stage.result} />
        <Evidence pay={stage.pay} serverPub={getServerPub()} checkedAt={stage.checkedAt} conflict={stage.result.ok ? null : stage.result.conflict} />
      </ScrollView>
    ) : (
      <View style={[{ flex: 1, gap: 14 }, busy && { opacity: 0.35 }]} pointerEvents={busy ? 'none' : 'auto'}>
        <View style={styles.tiles}>
          {QUICK.map((d) => (
            <Pressable
              key={d}
              onPress={() => setAmount(d)}
              style={({ pressed }) => [styles.tile, amount === d && styles.tileOn, pressed && { opacity: 0.8 }]}
              accessibilityRole="button"
              accessibilityLabel={`${d} dollars`}
            >
              <Text style={[styles.tileText, amount === d && { color: colors.onPrimary }]}>${d}</Text>
            </Pressable>
          ))}
        </View>
        <View style={styles.pad}>
          {KEYS.map((k) => (
            <Pressable
              key={k}
              onPress={() => press(k)}
              style={({ pressed }) => [styles.key, pressed && { backgroundColor: colors.primarySoft }]}
              accessibilityRole="button"
              accessibilityLabel={k === '⌫' ? 'Delete' : k === 'C' ? 'Clear' : k}
            >
              {k === '⌫'
                ? <Icon name="delete" size={30} color={colors.ink} />
                : <Text style={[styles.keyText, k === 'C' && { color: colors.muted }]}>{k}</Text>}
            </Pressable>
          ))}
        </View>
      </View>
    );

  // ---- Right: the check ----
  const total = stage.s === 'entry' ? amount * 100 : stage.s === 'result' ? stage.pay.t.amount_cents : stage.request.rq.amount_cents;
  let check: ReactNode;
  if (stage.s === 'entry') {
    check = (
      <>
        <View style={{ flex: 1 }} />
        <Button title={amount ? `Charge $${amount}` : 'Enter an amount'} big disabled={amount === 0} onPress={charge} />
      </>
    );
  } else if (stage.s === 'request') {
    const left = Math.max(0, stage.request.rq.req_expires_at - now);
    check = (
      <>
        <Label>Customer scans this</Label>
        <QrCode value={stage.qr} size={qrSize} />
        <Meter value={left} max={REQ_TTL_S} color={left > 30 ? colors.ink : colors.amber} />
        <Muted>{left === 0 ? 'Code expired. Cancel and charge again.' : `Expires in ${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}`}</Muted>
        <View style={{ flex: 1 }} />
        <Button title="Scan customer's code" big disabled={left === 0} onPress={() => setStage({ s: 'scan', request: stage.request })} />
        <Button title="Cancel sale" kind="ghost" onPress={cancel} />
      </>
    );
  } else if (stage.s === 'scan') {
    check = (
      <>
        <Label>Scan the customer's code</Label>
        {error ? <ErrorNote text={error} /> : null}
        <View style={{ width: qrSize + 32, alignSelf: 'center' }}>
          <Scanner key={scanKey} onScan={onScan} />
        </View>
        <Muted>Checked on this iPad. No internet.</Muted>
        <View style={{ flex: 1 }} />
        <Button title="Back to code" kind="secondary" onPress={() => setStage({ s: 'request', request: stage.request, qr: requestQr(stage.request) })} />
        <Button title="Cancel sale" kind="ghost" onPress={cancel} />
      </>
    );
  } else {
    const ok = stage.result.ok;
    const ink = ok ? colors.green : colors.red;
    check = (
      <>
        <View style={[styles.stamp, { borderColor: ink }]} accessible accessibilityRole="header" accessibilityLabel={ok ? 'Verified' : 'Refused'}>
          <Text allowFontScaling={false} adjustsFontSizeToFit numberOfLines={1} style={[styles.stampText, { color: ink }]}>{ok ? 'VERIFIED' : 'REFUSED'}</Text>
        </View>
        <Text style={[styles.why, { color: ok ? colors.ink : colors.red }]}>
          {ok ? 'Accepted offline.' : refusalCopy(stage.result.reason, stage.result.rule)}
        </Text>
        <Muted>
          {ok
            ? `Backed by Capital One. ${wholeDollars(stage.pay.t.cum_cents)} of ${wholeDollars(stage.pay.c.cap_cents)} used. Paid when this shop's records reach the bank.`
            : 'Do not hand over the goods. The signed evidence goes with the next device online.'}
        </Muted>
        <View style={{ flex: 1 }} />
        <Button title="New sale" big onPress={newSale} />
      </>
    );
  }

  return (
    <View style={[styles.fill, { backgroundColor: colors.bg }]}>
      {isDark ? <Radar /> : null}
      <SafeAreaView style={styles.fill} edges={['top', 'bottom', 'left', 'right']}>
        <View style={styles.body}>
          <View style={styles.left}>
            <Header />
            {left}
          </View>
          <View style={[styles.check, { width: checkW }]}>
            <View style={styles.checkHead}>
              <View style={{ flex: 1, minWidth: 0 }}>
                <Text style={styles.shop} numberOfLines={1}>{mc.display_name}</Text>
                <Text style={styles.sub}>{stage.s === 'result' ? 'Last sale' : 'Current sale'}</Text>
              </View>
            </View>
            <Text maxFontSizeMultiplier={1.15} adjustsFontSizeToFit numberOfLines={1} style={[styles.total, stage.s !== 'entry' && styles.totalSmall, total === 0 && { color: colors.faint }]}>
              {wholeDollars(total)}
            </Text>
            <ScrollView style={styles.checkBody} contentContainerStyle={styles.checkBodyInner} showsVerticalScrollIndicator={false}>{check}</ScrollView>
            <Pressable onPress={() => nav.go({ name: 'register' })} style={({ pressed }) => [styles.today, pressed && { opacity: 0.7 }]} accessibilityRole="button" accessibilityLabel="Today's sales">
              <View style={{ flex: 1, minWidth: 0 }}>
                <Text style={styles.todayHead}>Today · {wholeDollars(totals.acceptedCents)} accepted offline</Text>
                <Text style={styles.todayLine}>
                  {wholeDollars(totals.uploadedCents)} received by the bank server · {wholeDollars(totals.waitingCents)} waiting to upload
                </Text>
              </View>
              <Icon name="chevron-right" size={20} color={colors.faint} />
            </Pressable>
          </View>
        </View>
      </SafeAreaView>
    </View>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  body: { flex: 1, flexDirection: 'row', gap: 24, paddingHorizontal: 28, paddingVertical: 20 },
  left: { flex: 1, minWidth: 0, gap: 20 },
  tiles: { flexDirection: 'row', gap: 12 },
  tile: { flex: 1, height: 72, borderRadius: 12, backgroundColor: colors.card, alignItems: 'center', justifyContent: 'center' },
  tileOn: { backgroundColor: colors.primary },
  tileText: { fontFamily: font.display, fontSize: 34, lineHeight: 40, color: colors.ink, fontVariant: ['tabular-nums'] },
  pad: { flex: 1, flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'space-between', alignContent: 'space-between', rowGap: 12 },
  key: { width: '32%', height: '23%', minHeight: 64, borderRadius: 12, backgroundColor: colors.card, alignItems: 'center', justifyContent: 'center' },
  keyText: { fontFamily: font.semibold, fontSize: 36, color: colors.ink, fontVariant: ['tabular-nums'] },
  check: { backgroundColor: colors.card, borderRadius: radius.lg, padding: 24, gap: 14 },
  checkHead: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  shop: { fontFamily: font.bold, fontSize: 20, color: colors.ink },
  sub: { fontFamily: font.regular, fontSize: 15, color: colors.muted },
  total: { fontFamily: font.display, fontSize: 96, lineHeight: 108, color: colors.carbon, fontVariant: ['tabular-nums'] },
  checkBody: { flex: 1 },
  checkBodyInner: { flexGrow: 1, gap: 12, paddingBottom: 4 },
  totalSmall: { fontSize: 64, lineHeight: 74 },
  stamp: { alignSelf: 'center', borderWidth: 5, borderRadius: 10, paddingHorizontal: 18, paddingTop: 4, transform: [{ rotate: '-6deg' }], marginVertical: 8 },
  stampText: { fontFamily: font.display, fontSize: 64, lineHeight: 74, letterSpacing: 2 },
  why: { fontFamily: font.bold, fontSize: 22, lineHeight: 29 },
  today: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingTop: 14, borderTopWidth: 1, borderTopColor: colors.line },
  todayHead: { fontFamily: font.bold, fontSize: 15, color: colors.ink },
  todayLine: { fontFamily: font.regular, fontSize: 13, lineHeight: 18, color: colors.muted },
});
