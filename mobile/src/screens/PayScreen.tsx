// Resident pays (§19.2): scan REQ → "Pay <shop> $X.XX" → Face ID → show PAY QR.
import { useState } from 'react';
import { Alert } from 'react-native';
import { confirmWithFaceId } from '../auth';
import { QrCode } from '../components/QrCode';
import { Scanner } from '../components/Scanner';
import { Big, Body, Button, Muted, Screen, Title, dollars } from '../components/ui';
import { deviceKey } from '../keys';
import { useNav } from '../nav';
import { payQr, preparePayment, signPayment } from '../payments';
import type { PaymentRequest } from '../protocol';
import { getServerPub } from '../settings';
import { nowS } from '../store/items';

type Step = { s: 'scan' } | { s: 'confirm'; request: PaymentRequest } | { s: 'show'; qr: string; amount: number; shop: string };

export function PayScreen() {
  const nav = useNav();
  const [step, setStep] = useState<Step>({ s: 'scan' });

  const onScan = (data: string) => {
    const prep = preparePayment(data, getServerPub(), nowS());
    if (!prep.ok) {
      Alert.alert('Cannot pay', prep.message, [{ text: 'OK', onPress: nav.home }]);
      return;
    }
    setStep({ s: 'confirm', request: prep.request });
  };

  const pay = async (request: PaymentRequest) => {
    const label = `Pay ${request.mc.display_name} ${dollars(request.rq.amount_cents)}`;
    if (!(await confirmWithFaceId(label))) return;
    const p = signPayment(request, deviceKey(), nowS()); // wallet is persisted before the QR shows
    setStep({ s: 'show', qr: payQr(p), amount: request.rq.amount_cents, shop: request.mc.display_name });
  };

  if (step.s === 'scan') {
    return (
      <Screen>
        <Title>Scan the shop's code</Title>
        <Scanner onScan={onScan} />
        <Button title="Cancel" kind="secondary" onPress={nav.home} />
      </Screen>
    );
  }
  if (step.s === 'confirm') {
    const { mc, rq } = step.request;
    return (
      <Screen>
        <Title>Pay {mc.display_name}</Title>
        <Big>{dollars(rq.amount_cents)}</Big>
        <Muted>Verified shop · {mc.region_id}</Muted>
        <Button title={`Pay ${dollars(rq.amount_cents)} with Face ID`} onPress={() => pay(step.request)} />
        <Button title="Cancel" kind="secondary" onPress={nav.home} />
      </Screen>
    );
  }
  return (
    <Screen>
      <Title>Show this to {step.shop}</Title>
      <QrCode value={step.qr} />
      <Body>{dollars(step.amount)}</Body>
      <Button title="Done" onPress={nav.home} />
    </Screen>
  );
}
