// Merchant home: shop name, today's tally from the device log, Charge.
import { StyleSheet, Text } from 'react-native';
import { Header } from '../components/Header';
import { Big, Button, Card, colors, Field, Label, Muted, Pill, Row, Screen } from '../components/ui';
import { useNav } from '../nav';
import { logCounts } from '../store/devicelog';
import { countsByKind } from '../store/items';
import { merchantCert } from '../store/merchant';

export function MerchantHomeScreen() {
  const nav = useNav();
  const mc = merchantCert();
  if (!mc) return null;
  const carrying = Object.values(countsByKind()).reduce((a, b) => a + (b ?? 0), 0);
  const { accepted, refused, contacts } = logCounts();
  return (
    <Screen>
      <Header />
      <Card tone="navy" style={{ gap: 12 }}>
        <Row style={{ justifyContent: 'space-between' }}>
          <Label color="#9DB4FF">Shop · {mc.region_id.replace(/-/g, ' ')}</Label>
          <Pill text="Verified by StormCash" tone="green" dot />
        </Row>
        <Big color="#fff">{mc.display_name}</Big>
        <Muted color="#C7D2FE">Takes StormCash payments with no internet. Every payment is checked on this phone.</Muted>
      </Card>

      <Button title="Charge a customer" subtitle="Enter an amount, show your code" big onPress={() => nav.go({ name: 'charge' })} />

      <Row style={{ flexWrap: 'nowrap' }}>
        <Stat label="Accepted" value={accepted} />
        <Stat label="Refused" value={refused} tone={refused ? 'red' : undefined} />
        <Stat label="Met" value={contacts} />
      </Row>

      <Card>
        <Field label="Records carried" value={String(carrying)} last />
        <Button title="Records & sync" kind="ghost" onPress={() => nav.go({ name: 'records' })} />
      </Card>
    </Screen>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: 'red' }) {
  return (
    <Card style={{ flex: 1, gap: 2, padding: 16, alignItems: 'center' }}>
      <Text style={[styles.stat, tone === 'red' && value > 0 && { color: colors.red }]}>{value}</Text>
      <Label>{label}</Label>
    </Card>
  );
}

const styles = StyleSheet.create({
  stat: { fontSize: 36, fontWeight: '800', color: colors.ink, fontVariant: ['tabular-nums'] },
});
