// Resident pays (§19.2): scan REQ → "Pay <shop> $X.XX" → Face ID → show PAY QR.
import { useState } from 'react';
import { View } from 'react-native';
import { confirmWithFaceId } from '../auth';
import { Ticket } from '../components/Ticket';
import { Scanner } from '../components/Scanner';
import { Big, Button, Cell, ErrorNote, Group, Muted, Screen, Status, Title, wholeDollars, TopBar } from '../components/ui';
import { deviceKey } from '../keys';
import { useNav } from '../nav';
import { payQr, preparePayment, signPayment } from '../payments';
import type { PaymentRequest } from '../protocol';
import { getDisplayName, getServerPub } from '../settings';
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
      <Screen width="narrow">
        <TopBar onBack={nav.home} />
        <Title>Scan the shop's code</Title>
        <Muted>No internet needed.</Muted>
        {error ? <ErrorNote text={error} /> : null}
        <Scanner key={scanKey} onScan={onScan} />
      </Screen>
    );
  }

  if (step.s === 'confirm') {
    const { mc, rq } = step.request;
    return (
      <Screen width="narrow">
        <TopBar onBack={nav.home} />
        <Title>Confirm payment</Title>
        <View style={{ paddingVertical: 24, gap: 8 }}>
          <Muted>Pay {mc.display_name}</Muted>
          <Big>{wholeDollars(rq.amount_cents)}</Big>
          <Status text="Shop verified by StormCash" tone="green" />
        </View>
        <Group>
          <Cell title="Left now" value={wholeDollars(left)} />
          <Cell title="Left after this" value={wholeDollars(left - rq.amount_cents)} />
        </Group>
        <Button title="Pay with Face ID" big onPress={() => pay(step.request)} />
      </Screen>
    );
  }

  return (
    <Screen width="narrow">
      <Title>Show this to {step.shop}</Title>
      <Ticket
          value={step.qr}
          copy
          kicker={getDisplayName() ? `${getDisplayName()}'s copy` : 'Your copy'}
          title={step.shop}
          amount={wholeDollars(step.amount)}
          footnote={`Signed on this phone at ${new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`}
        />
      <View style={{ alignItems: 'center', gap: 6 }}>
        <Status text="Waiting for the shop to scan" tone="amber" />
        <Muted>Already counted: {wholeDollars(step.leftAfter)} left to spend. If no shop scans it, you're never charged.</Muted>
      </View>
      <Button title="Done" onPress={nav.home} />
    </Screen>
  );
}
