// StormCash design system: tokens and the few components every screen is built from.
// Judges stand about a metre away (spec §18), so type is large and contrast is high.
import * as Haptics from 'expo-haptics';
import type { ReactNode } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View, type ViewStyle } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

export const colors = {
  bg: '#F3F5F9', // app surface
  card: '#FFFFFF',
  ink: '#0B1B2B', // storm navy: headings, amounts
  text: '#1D2939',
  muted: '#667085',
  faint: '#98A2B3',
  line: '#E4E7EC',
  primary: '#1849F5', // bank blue
  primarySoft: '#E8EEFF',
  green: '#0E9F4F',
  greenSoft: '#E6F6EC',
  red: '#D92D20',
  redSoft: '#FDECEA',
  amber: '#B54708',
  amberSoft: '#FEF3E2',
  navy: '#0B1B2B',
};

export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 };
export const radius = { sm: 10, md: 14, lg: 20, pill: 999 };

const shadow: ViewStyle = {
  shadowColor: '#0B1B2B',
  shadowOpacity: 0.06,
  shadowRadius: 16,
  shadowOffset: { width: 0, height: 6 },
  elevation: 2,
};

// ---- Layout ----

export function Screen({
  children, scroll = true, style, tone = 'default',
}: { children: ReactNode; scroll?: boolean; style?: ViewStyle; tone?: 'default' | 'dark' }) {
  const bg = tone === 'dark' ? colors.navy : colors.bg;
  const body = <View style={[s.screen, style]}>{children}</View>;
  return (
    <SafeAreaView style={[s.fill, { backgroundColor: bg }]} edges={['top', 'bottom']}>
      {scroll ? (
        <ScrollView style={s.fill} contentContainerStyle={s.grow} keyboardShouldPersistTaps="handled">
          {body}
        </ScrollView>
      ) : (
        body
      )}
    </SafeAreaView>
  );
}

export function Card({ children, style, tone = 'default' }: { children: ReactNode; style?: ViewStyle; tone?: 'default' | 'navy' }) {
  return <View style={[s.card, tone === 'navy' && s.cardNavy, style]}>{children}</View>;
}

export function Row({ children, style }: { children: ReactNode; style?: ViewStyle }) {
  return <View style={[s.row, style]}>{children}</View>;
}

export function Spacer({ size = space.sm }: { size?: number }) {
  return <View style={{ height: size }} />;
}

// ---- Type ----

export const Title = ({ children, color }: { children: ReactNode; color?: string }) => (
  <Text style={[s.title, color ? { color } : null]} accessibilityRole="header">{children}</Text>
);
export const Big = ({ children, color }: { children: ReactNode; color?: string }) => (
  <Text style={[s.big, color ? { color } : null]} adjustsFontSizeToFit numberOfLines={1}>{children}</Text>
);
export const Body = ({ children, color }: { children: ReactNode; color?: string }) => (
  <Text style={[s.body, color ? { color } : null]}>{children}</Text>
);
export const Muted = ({ children, selectable, color }: { children: ReactNode; selectable?: boolean; color?: string }) => (
  <Text style={[s.muted, color ? { color } : null]} selectable={selectable}>{children}</Text>
);
export const Label = ({ children, color }: { children: ReactNode; color?: string }) => (
  <Text style={[s.label, color ? { color } : null]}>{children}</Text>
);

/** A titled group of content on the grey surface. */
export function Section({ title, children, right }: { title: string; children: ReactNode; right?: ReactNode }) {
  return (
    <View style={{ gap: space.sm }}>
      <Row style={{ justifyContent: 'space-between' }}>
        <Label>{title}</Label>
        {right}
      </Row>
      {children}
    </View>
  );
}

/** label ······ value, for records and details. */
export function Field({ label, value, last, light }: { label: string; value: ReactNode; last?: boolean; light?: boolean }) {
  return (
    <View style={[s.field, last && { borderBottomWidth: 0 }, light && { borderBottomColor: '#FFFFFF22' }]}>
      <Text style={[s.fieldLabel, light && { color: '#9DB4FF' }]}>{label}</Text>
      {typeof value === 'string' || typeof value === 'number'
        ? <Text style={[s.fieldValue, light && { color: '#fff' }]}>{value}</Text>
        : value}
    </View>
  );
}

// ---- Status ----

type Tone = 'neutral' | 'blue' | 'green' | 'red' | 'amber';
const TONES: Record<Tone, [string, string]> = {
  neutral: ['#EEF0F3', colors.muted],
  blue: [colors.primarySoft, colors.primary],
  green: [colors.greenSoft, colors.green],
  red: [colors.redSoft, colors.red],
  amber: [colors.amberSoft, colors.amber],
};

export function Pill({ text, tone = 'neutral', dot }: { text: string; tone?: Tone; dot?: boolean }) {
  const [bg, fg] = TONES[tone];
  return (
    <View style={[s.pill, { backgroundColor: bg }]}>
      {dot ? <View style={[s.dot, { backgroundColor: fg }]} /> : null}
      <Text style={[s.pillText, { color: fg }]}>{text}</Text>
    </View>
  );
}

/** Horizontal meter, e.g. spent of cap. */
export function Meter({ value, max, color = colors.primary, track = '#E4E7EC' }: { value: number; max: number; color?: string; track?: string }) {
  const pct = max > 0 ? Math.min(1, Math.max(0, value / max)) : 0;
  return (
    <View style={[s.meter, { backgroundColor: track }]}>
      <View style={[s.meterFill, { width: `${pct * 100}%`, backgroundColor: color }]} />
    </View>
  );
}

// ---- Controls ----

type ButtonKind = 'primary' | 'secondary' | 'danger' | 'ghost' | 'light';

export function Button({
  title, onPress, kind = 'primary', disabled, big, subtitle,
}: { title: string; onPress: () => void; kind?: ButtonKind; disabled?: boolean; big?: boolean; subtitle?: string }) {
  const palette: Record<ButtonKind, [string, string, string?]> = {
    primary: [colors.primary, '#fff'],
    secondary: [colors.card, colors.ink, colors.line],
    danger: [colors.red, '#fff'],
    ghost: ['transparent', colors.primary],
    light: ['#FFFFFF22', '#fff', '#FFFFFF44'],
  };
  const [bg, fg, border] = palette[kind];
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled: !!disabled }}
      onPress={() => {
        Haptics.selectionAsync().catch(() => {});
        onPress();
      }}
      disabled={disabled}
      style={({ pressed }) => [
        s.button,
        big && s.buttonBig,
        { backgroundColor: bg, opacity: disabled ? 0.4 : 1, transform: [{ scale: pressed ? 0.98 : 1 }] },
        border ? { borderWidth: 1, borderColor: border } : null,
      ]}
    >
      <Text style={[s.buttonText, big && s.buttonTextBig, { color: fg }]}>{title}</Text>
      {subtitle ? <Text style={[s.buttonSub, { color: fg }]}>{subtitle}</Text> : null}
    </Pressable>
  );
}

export function Chip({ text, active, onPress }: { text: string; active: boolean; onPress: () => void }) {
  return (
    <Pressable
      onPress={() => {
        Haptics.selectionAsync().catch(() => {});
        onPress();
      }}
      style={[s.chip, active && s.chipActive]}
      accessibilityRole="button"
      accessibilityState={{ selected: active }}
    >
      <Text style={[s.chipText, active && { color: '#fff' }]}>{text}</Text>
    </Pressable>
  );
}

// ---- Money ----

export const dollars = (cents: number): string => `$${(cents / 100).toFixed(2)}`;
export const wholeDollars = (cents: number): string => (cents % 100 === 0 ? `$${cents / 100}` : dollars(cents));

const s = StyleSheet.create({
  fill: { flex: 1 },
  grow: { flexGrow: 1 },
  screen: { flexGrow: 1, paddingHorizontal: space.xl - 4, paddingTop: space.md, paddingBottom: space.xl, gap: space.lg },
  card: { backgroundColor: colors.card, borderRadius: radius.lg, padding: space.xl - 4, gap: space.md, ...shadow },
  cardNavy: { backgroundColor: colors.navy },
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: space.sm, alignItems: 'center' },
  title: { fontSize: 28, fontWeight: '800', color: colors.ink, letterSpacing: -0.4 },
  big: { fontSize: 52, fontWeight: '800', color: colors.ink, letterSpacing: -1.5, fontVariant: ['tabular-nums'] },
  body: { fontSize: 17, lineHeight: 24, color: colors.text },
  muted: { fontSize: 15, lineHeight: 21, color: colors.muted },
  label: { fontSize: 13, fontWeight: '700', color: colors.muted, letterSpacing: 0.8, textTransform: 'uppercase' },
  field: {
    flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: space.md,
    paddingVertical: space.md, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.line,
  },
  fieldLabel: { fontSize: 16, color: colors.muted },
  fieldValue: { fontSize: 16, fontWeight: '600', color: colors.ink, flexShrink: 1, textAlign: 'right', fontVariant: ['tabular-nums'] },
  pill: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 10, paddingVertical: 5, borderRadius: radius.pill, alignSelf: 'flex-start' },
  pillText: { fontSize: 13, fontWeight: '700' },
  dot: { width: 7, height: 7, borderRadius: 4 },
  meter: { height: 10, borderRadius: radius.pill, overflow: 'hidden' },
  meterFill: { height: '100%', borderRadius: radius.pill },
  button: { minHeight: 54, paddingVertical: 14, paddingHorizontal: space.lg, borderRadius: radius.md, alignItems: 'center', justifyContent: 'center' },
  buttonBig: { minHeight: 68, borderRadius: radius.lg },
  buttonText: { fontSize: 17, fontWeight: '700' },
  buttonTextBig: { fontSize: 20 },
  buttonSub: { fontSize: 13, opacity: 0.8, marginTop: 2 },
  chip: { paddingHorizontal: 16, paddingVertical: 10, borderRadius: radius.pill, backgroundColor: colors.card, borderWidth: 1, borderColor: colors.line },
  chipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipText: { fontSize: 15, fontWeight: '600', color: colors.text },
});
