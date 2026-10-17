// Resident pays (§19.2): scan REQ → "Pay <shop> $X.XX" → Face ID → show PAY QR.
import { useState } from 'react';
import { View } from 'react-native';
import { confirmWithFaceId } from '../auth';
import { QrCode } from '../components/QrCode';
import { Scanner } from '../components/Scanner';
import { Big, Body, Button, Card, ErrorNote, Field, Muted, Screen, Status, Title, wholeDollars } from '../components/ui';
import { deviceKey } from '../keys';
import { useNav } from '../nav';
import { payQr, preparePayment, signPayment } from '../payments';
import type { PaymentRequest } from '../protocol';
import { getServerPub } from '../settings';
import { nowS } from '../store/items';
import { latestCert, walletState } from '../store/wallet';

type Step =
  | { s: 'scan' }
  | { s: 'confirm'; request: PaymentRequest }
  | { s: 'show'; qr: string; amount: number; shop: string; leftAfter: number };

export function PayScreen() {
  const nav = useNav();
  const [step, setStep] = useState<Step>({ s: 'scan' });
  const [error, setError] = useState<string | null>(null);
  const [scanKey, setScanKey] = useState(0); // remounts the scanner for another try
  const cert = latestCert();
  const state = walletState();
  const left = cert && state ? cert.cap_cents - state.cumCents : 0;

  const onScan = (data: string) => {
    const prep = preparePayment(data, getServerPub(), nowS());
    if (!prep.ok) {
      setError(prep.message);
      setScanKey((k) => k + 1);
      return;
    }
    setError(null);
    setStep({ s: 'confirm', request: prep.request });
  };

  const pay = async (request: PaymentRequest) => {
    const amount = request.rq.amount_cents;
    if (!(await confirmWithFaceId(`Pay ${request.mc.display_name} ${wholeDollars(amount)}`))) return;
    const p = signPayment(request, deviceKey(), nowS()); // wallet is persisted before the QR shows
    setStep({ s: 'show', qr: payQr(p), amount, shop: request.mc.display_name, leftAfter: left - amount });
  };

  if (step.s === 'scan') {
    return (
      <Screen>
        <Title>Scan the shop's code</Title>
        <Muted>Point the camera at the code on the shop's phone. No internet needed.</Muted>
        {error ? <ErrorNote text={error} /> : null}
        <Scanner key={scanKey} onScan={onScan} />
        <Button title="Cancel" kind="secondary" onPress={nav.home} />
      </Screen>
    );
  }

  if (step.s === 'confirm') {
    const { mc, rq } = step.request;
    return (
      <Screen>
        <Title>Confirm payment</Title>
        <Card style={{ alignItems: 'center', paddingVertical: 28 }}>
          <Body>Pay {mc.display_name}</Body>
          <Big>{wholeDollars(rq.amount_cents)}</Big>
          <Status text="Shop verified by StormCash" tone="green" />
        </Card>
        <Card>
          <Field label="Left now" value={wholeDollars(left)} />
          <Field label="Left after" value={wholeDollars(left - rq.amount_cents)} />
        </Card>
        <Button title="Pay with Face ID" big onPress={() => pay(step.request)} />
        <Button title="Cancel" kind="secondary" onPress={nav.home} />
      </Screen>
    );
  }

  return (
    <Screen>
      <Title>Show this to {step.shop}</Title>
      <Card style={{ alignItems: 'center', padding: 12 }}>
        <QrCode value={step.qr} />
      </Card>
      <View style={{ alignItems: 'center', gap: 4 }}>
        <Big>{wholeDollars(step.amount)}</Big>
        <Status text="Signed on this phone" tone="green" />
        <Muted>{wholeDollars(step.leftAfter)} left in your wallet</Muted>
      </View>
      <Button title="Done" onPress={nav.home} />
    </Screen>
  );
}
