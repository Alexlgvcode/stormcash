// Merchant charges (§19.2): keypad → REQ QR with a 2-minute countdown → scan the customer's code.
import { useState } from 'react';
import { Alert, Pressable, StyleSheet, Text, View } from 'react-native';
import { QrCode } from '../components/QrCode';
import { Scanner } from '../components/Scanner';
import { Big, Button, colors, Muted, Screen, Title, dollars } from '../components/ui';
import { useTick } from '../hooks';
import { deviceKey } from '../keys';
import { useNav } from '../nav';
import { createRequest, receivePayment, requestQr } from '../payments';
import type { PaymentRequest } from '../protocol';
import { getServerPub } from '../settings';
import { nowS } from '../store/items';
import { merchantCert, setOpenRequest } from '../store/merchant';

type Step = { s: 'amount' } | { s: 'request'; request: PaymentRequest; qr: string } | { s: 'scan' };

const KEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '00', '0', '⌫'];

export function ChargeScreen() {
  const nav = useNav();
  const [cents, setCents] = useState(0);
  const [step, setStep] = useState<Step>({ s: 'amount' });
  const now = Math.floor(useTick(1000) / 1000);
  const mc = merchantCert();
  if (!mc) return null;

  const press = (k: string) => {
    if (k === '⌫') setCents(Math.floor(cents / 10));
    else setCents(Math.min(99999, Number(String(cents) + k)));
  };

  const cancel = () => {
    setOpenRequest(null);
    nav.home();
  };

  const onScan = (data: string) => {
    const r = receivePayment(data, mc, deviceKey(), getServerPub(), nowS());
    if (!r.parsed) {
      Alert.alert('Not a payment', r.message, [{ text: 'Scan again', onPress: () => setStep({ s: 'scan' }) }]);
      return;
    }
    nav.go({ name: 'result', result: r.result, pay: r.pay, capCents: r.pay.c.cap_cents });
  };

  if (step.s === 'amount') {
    return (
      <Screen>
        <Title>Charge</Title>
        <Big>{dollars(cents)}</Big>
        <View style={styles.pad}>
          {KEYS.map((k) => (
            <Pressable key={k} style={styles.key} onPress={() => press(k)}>
              <Text style={styles.keyText}>{k}</Text>
            </Pressable>
          ))}
        </View>
        <Button
          title="Show code"
          disabled={cents === 0}
          onPress={() => {
            const request = createRequest(mc, cents, deviceKey(), nowS());
            setStep({ s: 'request', request, qr: requestQr(request) });
          }}
        />
        <Button title="Cancel" kind="secondary" onPress={cancel} />
      </Screen>
    );
  }
  if (step.s === 'request') {
    const left = step.request.rq.req_expires_at - now;
    return (
      <Screen>
        <Title>{mc.display_name} · {dollars(step.request.rq.amount_cents)}</Title>
        <QrCode value={step.qr} />
        <Muted>{left > 0 ? `Expires in ${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}` : 'Expired'}</Muted>
        <Button title="Scan customer's code" onPress={() => setStep({ s: 'scan' })} />
        <Button title="Cancel" kind="secondary" onPress={cancel} />
      </Screen>
    );
  }
  return (
    <Screen>
      <Title>Scan customer's code</Title>
      <Scanner onScan={onScan} />
      <Button title="Cancel" kind="secondary" onPress={cancel} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  pad: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'space-between', rowGap: 10 },
  key: { width: '31%', paddingVertical: 18, borderRadius: 12, backgroundColor: '#f1f1f1', alignItems: 'center' },
  keyText: { fontSize: 26, fontWeight: '600', color: colors.text },
});
