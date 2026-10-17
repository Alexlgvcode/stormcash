// Merchant home: shop name, today's tally from the device log, Charge.
import { StyleSheet, Text, View } from 'react-native';
import { Header } from '../components/Header';
import { Big, Button, Card, colors, Field, font, Label, Muted, Screen, Status } from '../components/ui';
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
  const region = mc.region_id.replace(/-/g, ' ');
  return (
    <Screen>
      <Header />
      <Card tone="navy" style={{ gap: 12 }}>
        <Label color={colors.onNavyMuted}>Shop in {region.charAt(0).toUpperCase() + region.slice(1)}</Label>
        <Big color={colors.onNavy}>{mc.display_name}</Big>
        <Muted color={colors.onNavyMuted}>Takes StormCash payments with no internet. Every payment is checked on this phone.</Muted>
        <Status text="Verified by StormCash" tone="green" light />
      </Card>

      <Button title="Charge a customer" subtitle="Enter an amount, show your code" big onPress={() => nav.go({ name: 'charge' })} />

      <Card style={{ flexDirection: 'row', paddingVertical: 18 }}>
        <Tally label="Accepted" value={accepted} />
        <Tally label="Refused" value={refused} alert={refused > 0} />
        <Tally label="Phones met" value={contacts} />
      </Card>

      <Card>
        <Field label="Records carried" value={String(carrying)} />
        <Button title="Records and sync" kind="secondary" onPress={() => nav.go({ name: 'records' })} />
      </Card>
    </Screen>
  );
}

function Tally({ label, value, alert }: { label: string; value: number; alert?: boolean }) {
  return (
    <View style={styles.tally} accessible accessibilityLabel={`${label}: ${value}`}>
      <Text style={[styles.value, alert && { color: colors.red }]}>{value}</Text>
      <Text style={styles.label} numberOfLines={1}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  tally: { flex: 1, alignItems: 'center', gap: 2 },
  value: { fontFamily: font.heavy, fontSize: 36, lineHeight: 40, color: colors.ink, fontVariant: ['tabular-nums'] },
  label: { fontFamily: font.medium, fontSize: 14, color: colors.muted },
});
