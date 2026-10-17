// Header with the logo (long-press opens the hidden demo menu, §19.2) and an online/offline badge.
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useOnline } from '../hooks';
import { useNav } from '../nav';
import { getDemoLabel } from '../settings';
import { colors } from './ui';

export function Header() {
  const nav = useNav();
  const online = useOnline();
  const label = getDemoLabel();
  return (
    <View style={styles.row}>
      <Pressable onLongPress={() => nav.go({ name: 'demo' })} delayLongPress={600}>
        <Text style={styles.logo}>StormCash</Text>
      </Pressable>
      <View style={styles.right}>
        {label ? <Text style={styles.label}>{label}</Text> : null}
        <View style={[styles.badge, { backgroundColor: online ? colors.green : colors.muted }]}>
          <Text style={styles.badgeText}>{online ? 'Online' : 'Offline'}</Text>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  logo: { fontSize: 22, fontWeight: '800', color: colors.primary },
  right: { flexDirection: 'row', gap: 8, alignItems: 'center' },
  label: { fontSize: 12, color: colors.muted },
  badge: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 10 },
  badgeText: { color: '#fff', fontSize: 13, fontWeight: '600' },
});
