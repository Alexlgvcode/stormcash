// Merchant home: the shop as the hero over the radar, today's tally, Charge.
import { useEffect, useReducer } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Header } from '../components/Header';
import { Button, Cell, colors, font, Group, Screen, Status } from '../components/ui';
import { useNav } from '../nav';
import { logCounts } from '../store/devicelog';
import { countsByKind } from '../store/items';
import { merchantCert } from '../store/merchant';
import { syncManager } from '../sync/manager';

export function MerchantHomeScreen() {
  const nav = useNav();
  const [, rerender] = useReducer((x: number) => x + 1, 0);
  useEffect(() => syncManager.subscribe(rerender), []);
  const mc = merchantCert();
  if (!mc) return null;
  const carrying = Object.values(countsByKind()).reduce((a, b) => a + (b ?? 0), 0);
  const { accepted, refused, contacts } = logCounts();
  const region = mc.region_id.replace(/-/g, ' ');

  return (
    <Screen>
      <Header />
      <View style={styles.sheet}>
        <Text style={styles.heroLabel}>Takes StormCash with no internet in {region.replace(/\b\w/g, (c) => c.toUpperCase())}</Text>
        <Text style={styles.heroName} adjustsFontSizeToFit numberOfLines={2}>{mc.display_name}</Text>
        <Status text="Registered with StormCash" tone="green" />
      </View>

      <View style={styles.strip} accessible accessibilityLabel={`${accepted} accepted, ${refused} refused, ${contacts} phones met`}>
        <Stat value={accepted} label="accepted" />
        <Stat value={refused} label="refused" alert={refused > 0} />
        <Stat value={contacts} label="phones met" />
      </View>

      <Button title="Charge a customer" subtitle="Enter an amount, show your code" big onPress={() => nav.go({ name: 'charge' })} />

      <Group>
        <Cell title="Records to deliver" detail="Phones pass them on until one is online" value={String(carrying)} onPress={() => nav.go({ name: 'records' })} />
      </Group>
    </Screen>
  );
}

function Stat({ value, label, alert }: { value: number; label: string; alert?: boolean }) {
  return (
    <View style={{ flex: 1 }}>
      <Text style={[styles.statValue, alert && { color: colors.red }]}>{value}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  sheet: {
    backgroundColor: colors.sheet, borderRadius: 8, padding: 20, gap: 10,
    borderBottomWidth: 4, borderBottomColor: colors.sheetEdge,
  },
  heroLabel: { fontFamily: font.regular, fontSize: 17, lineHeight: 23, color: colors.ink },
  heroName: { fontFamily: font.display, fontSize: 88, lineHeight: 84, color: colors.carbon },
  strip: { flexDirection: 'row', paddingVertical: 4 },
  statValue: { fontFamily: font.display, fontSize: 48, lineHeight: 48, color: colors.carbon, fontVariant: ['tabular-nums'] },
  statLabel: { fontFamily: font.medium, fontSize: 15, color: colors.muted },
});
