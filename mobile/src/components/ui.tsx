import type { ReactNode } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View, type ViewStyle } from 'react-native';

export const colors = {
  bg: '#ffffff', text: '#111111', muted: '#666666', line: '#e5e5e5',
  primary: '#0b5fff', green: '#0a8f3c', red: '#c62828', amber: '#b26a00',
};

export function Screen({ children, scroll = true, style }: { children: ReactNode; scroll?: boolean; style?: ViewStyle }) {
  if (!scroll) return <View style={[s.screen, style]}>{children}</View>;
  return <ScrollView style={s.scroll} contentContainerStyle={[s.screen, style]}>{children}</ScrollView>;
}

export const Title = ({ children }: { children: ReactNode }) => <Text style={s.title}>{children}</Text>;
export const Big = ({ children, color }: { children: ReactNode; color?: string }) => (
  <Text style={[s.big, color ? { color } : null]}>{children}</Text>
);
export const Body = ({ children, color }: { children: ReactNode; color?: string }) => (
  <Text style={[s.body, color ? { color } : null]}>{children}</Text>
);
export const Muted = ({ children }: { children: ReactNode }) => <Text style={s.muted}>{children}</Text>;

export function Button({
  title, onPress, kind = 'primary', disabled,
}: { title: string; onPress: () => void; kind?: 'primary' | 'secondary' | 'danger'; disabled?: boolean }) {
  const bg = kind === 'primary' ? colors.primary : kind === 'danger' ? colors.red : '#f1f1f1';
  const fg = kind === 'secondary' ? colors.text : '#fff';
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      style={({ pressed }) => [s.button, { backgroundColor: bg, opacity: disabled ? 0.4 : pressed ? 0.7 : 1 }]}
    >
      <Text style={[s.buttonText, { color: fg }]}>{title}</Text>
    </Pressable>
  );
}

export function Chip({ text, active, onPress }: { text: string; active: boolean; onPress: () => void }) {
  return (
    <Pressable onPress={onPress} style={[s.chip, active && s.chipActive]}>
      <Text style={[s.chipText, active && { color: '#fff' }]}>{text}</Text>
    </Pressable>
  );
}

export function Row({ children }: { children: ReactNode }) {
  return <View style={s.row}>{children}</View>;
}

export const dollars = (cents: number): string => `$${(cents / 100).toFixed(2)}`;
export const wholeDollars = (cents: number): string =>
  cents % 100 === 0 ? `$${cents / 100}` : dollars(cents);

const s = StyleSheet.create({
  scroll: { flex: 1, backgroundColor: colors.bg },
  screen: { flexGrow: 1, padding: 20, paddingTop: 64, gap: 14, backgroundColor: colors.bg },
  title: { fontSize: 28, fontWeight: '700', color: colors.text },
  big: { fontSize: 40, fontWeight: '800', color: colors.text },
  body: { fontSize: 18, color: colors.text },
  muted: { fontSize: 15, color: colors.muted },
  button: { paddingVertical: 16, borderRadius: 12, alignItems: 'center' },
  buttonText: { fontSize: 18, fontWeight: '600' },
  chip: { paddingHorizontal: 14, paddingVertical: 10, borderRadius: 20, backgroundColor: '#f1f1f1' },
  chipActive: { backgroundColor: colors.primary },
  chipText: { fontSize: 16, color: colors.text },
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: 10, alignItems: 'center' },
});
