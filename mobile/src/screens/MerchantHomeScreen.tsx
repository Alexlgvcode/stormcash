// Merchant home: the shop as the hero over the radar, today's tally, Charge.
import { useEffect, useReducer } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Header } from '../components/Header';
import { Radar } from '../components/Radar';
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
      <View style={styles.hero}>
        <Radar blips={syncManager.status.connected.length} />
        <Text style={styles.heroLabel}>Taking payments offline in {region.replace(/\b\w/g, (c) => c.toUpperCase())}</Text>
        <Text style={styles.heroName} adjustsFontSizeToFit numberOfLines={2}>{mc.display_name}</Text>
        <Status text="Verified by StormCash" tone="green" />
      </View>

      <View style={styles.strip} accessible accessibilityLabel={`${accepted} accepted, ${refused} refused, ${contacts} phones met`}>
        <Stat value={accepted} label="accepted" />
        <Stat value={refused} label="refused" alert={refused > 0} />
        <Stat value={contacts} label="phones met" />
      </View>

      <Button title="Charge a customer" subtitle="Enter an amount, show your code" big onPress={() => nav.go({ name: 'charge' })} />

      <Group>
        <Cell title="Records carried" detail="Delivered phone to phone" value={String(carrying)} onPress={() => nav.go({ name: 'records' })} />
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
  hero: { paddingTop: 28, paddingBottom: 8, minHeight: 230, gap: 10 },
  heroLabel: { fontFamily: font.medium, fontSize: 17, color: colors.muted },
  heroName: { fontFamily: font.heavy, fontSize: 64, lineHeight: 66, color: colors.ink, letterSpacing: -2.5 },
  strip: { flexDirection: 'row', paddingVertical: 4 },
  statValue: { fontFamily: font.heavy, fontSize: 34, lineHeight: 38, color: colors.ink, fontVariant: ['tabular-nums'] },
  statLabel: { fontFamily: font.medium, fontSize: 15, color: colors.muted },
});
