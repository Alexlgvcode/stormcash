// The shop's register: who it is, its takings by status (accepted offline on this device, then
// received by the StormCash server once a device uploads them) and its payments. On a phone it's
// the home with Charge; on an iPad it's the Sales view behind Checkout, which does all charging.
import { useEffect, useReducer } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Header } from '../components/Header';
import { Button, Cell, colors, Columns, font, Group, Label, MoneyRow, Muted, Screen, Status, Title, TopBar, useWide, wholeDollars } from '../components/ui';
import { useNav } from '../nav';
import { logCounts } from '../store/devicelog';
import { countsByKind } from '../store/items';
import { merchantCert } from '../store/merchant';
import { takings, takingsTotals, type Taking } from '../store/takings';
import { syncManager } from '../sync/manager';

export function MerchantHomeScreen() {
  const nav = useNav();
  const wide = useWide();
  const [, rerender] = useReducer((x: number) => x + 1, 0);
  useEffect(() => syncManager.subscribe(rerender), []);
  const mc = merchantCert();
  if (!mc) return null;
  const carrying = Object.values(countsByKind()).reduce((a, b) => a + (b ?? 0), 0);
  const { contacts } = logCounts();
  const region = mc.region_id.replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
  const list = takings(30);
  const totals = takingsTotals(list);
  const acceptedCount = list.filter((t) => t.accepted).length;

  const register = (
    <View style={{ gap: 16 }}>
      {wide ? null : (<View style={styles.sheet}>
        <Text style={styles.heroLabel}>Takes StormCash with no internet · {region}</Text>
        <Text maxFontSizeMultiplier={1.15} style={styles.heroName} adjustsFontSizeToFit numberOfLines={2}>{mc.display_name}</Text>
        <Status text="Registered with StormCash" tone="green" />
      </View>)}
      {wide ? null : <Button title="Charge a customer" subtitle="Amount, then show code" big onPress={() => nav.go({ name: 'charge' })} />}
      <Group>
        <View style={{ paddingHorizontal: 18, paddingVertical: 4 }}>
          <MoneyRow
            label="Accepted offline"
            note={`${acceptedCount} ${acceptedCount === 1 ? 'payment' : 'payments'}`}
            value={wholeDollars(totals.acceptedCents)}
            strong
          />
          <MoneyRow label="Received by the bank server" note="Uploaded for settlement" value={wholeDollars(totals.uploadedCents)} tone="green" />
          <MoneyRow label="Waiting to upload" note="Uploads when a phone finds signal" value={wholeDollars(totals.waitingCents)} tone={totals.waitingCents ? 'amber' : undefined} />
          {totals.refused ? <MoneyRow label="Refused" note="Evidence kept" value={String(totals.refused)} tone="red" /> : null}
        </View>
      </Group>
    </View>
  );

  const history = (
    <View style={{ gap: 16 }}>
      <View style={{ gap: 4 }}>
        <Label>Payments</Label>
        {list.length === 0 ? <Muted>No payments yet. Charge a customer to start.</Muted> : list.map((t) => <TakingRow key={t.tagHash + t.ts} t={t} />)}
      </View>
      <Group>
        <Cell title="Records to deliver" detail="Phones pass them on until one is online" value={String(carrying)} onPress={() => nav.go({ name: 'records' })} />
        <Cell title="Phones met" detail="Record swaps with nearby phones" value={String(contacts)} />
      </Group>
    </View>
  );

  return (
    <Screen>
      {wide ? (
        <>
          <TopBar onBack={nav.home} />
          <Title>{`${mc.display_name} · sales`}</Title>
        </>
      ) : <Header />}
      <Columns left={register} right={history} ratio={1.1} />
    </Screen>
  );
}

function TakingRow({ t }: { t: Taking }) {
  const time = new Date(t.ts * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  const status = !t.accepted
    ? { text: `Refused · check ${t.check}`, color: colors.red }
    : t.receipted
      ? { text: 'Received by the bank server', color: colors.green }
      : { text: 'Accepted offline · waiting to upload', color: colors.amber };
  return (
    <View style={styles.row} accessible accessibilityLabel={`${t.amountCents !== null ? wholeDollars(t.amountCents) : 'Payment'}, ${status.text}, ${time}`}>
      <View style={{ flex: 1, minWidth: 0, gap: 2 }}>
        <Text style={[styles.rowStatus, { color: status.color }]}>{status.text}</Text>
        <Text style={styles.rowMeta}>{t.counter !== null ? `Copy ${t.counter} · ` : ''}{time}</Text>
      </View>
      <Text maxFontSizeMultiplier={1.15} style={[styles.rowAmount, !t.accepted && { color: colors.faint, textDecorationLine: 'line-through' }]}>
        {t.amountCents !== null ? wholeDollars(t.amountCents) : '—'}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  sheet: {
    backgroundColor: colors.sheet, borderRadius: 8, padding: 20, gap: 10,
    borderBottomWidth: 4, borderBottomColor: colors.sheetEdge,
  },
  heroLabel: { fontFamily: font.regular, fontSize: 16, lineHeight: 22, color: colors.sheetInk },
  heroName: { fontFamily: font.display, fontSize: 72, lineHeight: 82, color: colors.sheetFigure },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 10 },
  rowStatus: { fontFamily: font.bold, fontSize: 16 },
  rowMeta: { fontFamily: font.regular, fontSize: 14, color: colors.muted, fontVariant: ['tabular-nums'] },
  rowAmount: { fontFamily: font.display, fontSize: 30, lineHeight: 36, color: colors.carbon, fontVariant: ['tabular-nums'] },
});
