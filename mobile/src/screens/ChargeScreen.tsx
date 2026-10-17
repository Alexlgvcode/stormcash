// Merchant charges (§19.2): keypad → REQ QR with a 2-minute countdown → scan the customer's code.
// Demo payments are whole dollars (Nessie moves whole dollars, §11.4), so the keypad enters dollars.
import * as Haptics from 'expo-haptics';
import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Icon } from '../components/Icon';
import { Ticket } from '../components/Ticket';
import { Scanner } from '../components/Scanner';
import { Button, Chip, colors, ErrorNote, font, Label, Meter, Muted, Row, Screen, Title, radius, TopBar } from '../components/ui';
import { useTick } from '../hooks';
import { deviceKey } from '../keys';
import { useNav } from '../nav';
import { createRequest, receivePayment, REQ_TTL_S, requestQr } from '../payments';
import type { PaymentRequest } from '../protocol';
import { getServerPub } from '../settings';
import { nowS } from '../store/items';
import { merchantCert, setOpenRequest } from '../store/merchant';

type Step = { s: 'amount' } | { s: 'request'; request: PaymentRequest; qr: string } | { s: 'scan' };

const KEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', 'C', '0', '⌫'];
const QUICK = [5, 10, 12, 20];
const MAX_DOLLARS = 999;

export function ChargeScreen() {
  const nav = useNav();
  const [amount, setAmount] = useState(0); // whole dollars
  const [step, setStep] = useState<Step>({ s: 'amount' });
  const [error, setError] = useState<string | null>(null);
  const [scanKey, setScanKey] = useState(0);
  const now = Math.floor(useTick(1000) / 1000);
  const mc = merchantCert();
  if (!mc) return null;

  const press = (k: string) => {
    Haptics.selectionAsync().catch(() => {});
    if (k === '⌫') setAmount(Math.floor(amount / 10));
    else if (k === 'C') setAmount(0);
    else setAmount(Math.min(MAX_DOLLARS, Number(String(amount) + k)));
  };

  const cancel = () => {
    setOpenRequest(null);
    nav.home();
  };

  const onScan = (data: string) => {
    const r = receivePayment(data, mc, deviceKey(), getServerPub(), nowS());
    if (!r.parsed) {
      setError(r.message);
      setScanKey((k) => k + 1);
      return;
    }
    setError(null);
    nav.go({ name: 'result', result: r.result, pay: r.pay, capCents: r.pay.c.cap_cents });
  };

  if (step.s === 'amount') {
    return (
      <Screen>
        <TopBar onBack={cancel} />
        <Title>Charge</Title>
        <View style={{ alignItems: 'center', paddingVertical: 12 }}>
          <Label>{mc.display_name} charges</Label>
          <Text style={[styles.amount, amount === 0 && { color: colors.faint }]} adjustsFontSizeToFit numberOfLines={1}>${amount}</Text>
          <Muted>Whole dollars</Muted>
        </View>
        <Row style={{ justifyContent: 'center' }}>
          {QUICK.map((d) => <Chip key={d} text={`$${d}`} active={amount === d} onPress={() => setAmount(d)} />)}
        </Row>
        <View style={styles.pad}>
          {KEYS.map((k) => (
            <Pressable
              key={k}
              onPress={() => press(k)}
              style={({ pressed }) => [styles.key, pressed && { backgroundColor: colors.primarySoft }]}
              accessibilityLabel={k === '⌫' ? 'Delete' : k === 'C' ? 'Clear' : k}
            >
              {k === '⌫'
                ? <Icon name="delete" size={28} color={colors.ink} />
                : <Text style={[styles.keyText, k === 'C' && { color: colors.muted }]}>{k}</Text>}
            </Pressable>
          ))}
        </View>
        <Button
          title={amount ? `Show code for $${amount}` : 'Enter an amount'}
          big
          disabled={amount === 0}
          onPress={() => {
            const request = createRequest(mc, amount * 100, deviceKey(), nowS());
            setStep({ s: 'request', request, qr: requestQr(request) });
          }}
        />
      </Screen>
    );
  }

  if (step.s === 'request') {
    const left = Math.max(0, step.request.rq.req_expires_at - now);
    const expired = left === 0;
    return (
      <Screen>
        <TopBar onBack={cancel} />
        <Title>Customer scans this</Title>
        <Ticket
          value={step.qr}
          kicker="Payment request"
          title={mc.display_name}
          amount={`$${step.request.rq.amount_cents / 100}`}
          footnote="Signed by this shop. Works with no internet."
          dim={expired}
        />
        <Meter value={left} max={REQ_TTL_S} color={left > 30 ? colors.primary : colors.amber} />
        <Muted>{expired ? 'This code expired. Start again.' : `Expires in ${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}`}</Muted>
        <Button title="Scan customer's code" big onPress={() => setStep({ s: 'scan' })} disabled={expired} />
      </Screen>
    );
  }

  return (
    <Screen>
      <TopBar onBack={cancel} />
      <Title>Scan customer's code</Title>
      <Muted>Every check runs on this phone. No internet needed.</Muted>
      {error ? <ErrorNote text={error} /> : null}
      <Scanner key={scanKey} onScan={onScan} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  amount: { fontFamily: font.display, fontSize: 104, lineHeight: 110, color: colors.ink, letterSpacing: -3, fontVariant: ['tabular-nums'] },
  pad: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'space-between', rowGap: 10 },
  key: { width: '31.5%', height: 64, borderRadius: radius.pill, backgroundColor: colors.card, alignItems: 'center', justifyContent: 'center' },
  keyText: { fontFamily: font.semibold, fontSize: 28, color: colors.ink, fontVariant: ['tabular-nums'] },
});
