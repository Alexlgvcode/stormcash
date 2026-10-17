// StormCash design system: tokens and the few components every screen is built from.
// Judges stand about a metre away (spec §18), so type is large and contrast is high.
// House rules (taste-skill): one typeface (Geist), one accent, surfaces separated by tone steps
// (no shadows at rest, no hairlines, no outlined boxes), round buttons, sentence-case labels.
import * as Haptics from 'expo-haptics';
import type { ReactNode } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View, type ViewStyle } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Icon } from './Icon';

export const font = {
  regular: 'Geist_400Regular',
  medium: 'Geist_500Medium',
  semibold: 'Geist_600SemiBold',
  bold: 'Geist_700Bold',
  heavy: 'Geist_800ExtraBold',
};

export const colors = {
  bg: '#F1F3F6', // ground
  card: '#FFFFFF', // one tone step up
  well: '#E6EAF0', // one tone step down: secondary buttons, keys, chips
  ink: '#0B1B2B', // storm navy: headings, amounts, running text
  text: '#0B1B2B',
  muted: '#566173', // secondary notes only
  faint: '#8A94A6',
  line: '#D5DBE4', // form fields only
  primary: '#1747E6', // the one accent: actions
  primarySoft: '#E3E9FD',
  green: '#0B8F47',
  greenSoft: '#E1F3E8',
  red: '#D3261B',
  redSoft: '#FBE6E4',
  amber: '#A74B05',
  amberSoft: '#FDF0DE',
  navy: '#0B1B2B',
  navyRaised: '#15283C',
  onNavy: '#FFFFFF',
  onNavyMuted: '#AFC0DA',
};

export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 };
export const radius = { sm: 12, md: 16, lg: 24, pill: 999 };

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
/** A small heading for a group: sentence case, readable size. */
export const Label = ({ children, color }: { children: ReactNode; color?: string }) => (
  <Text style={[s.label, color ? { color } : null]}>{children}</Text>
);

/** A titled group of content on the ground. */
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

/** label ······ value, for records and details. Separated by space, not rules. */
export function Field({ label, value, light }: { label: string; value: ReactNode; last?: boolean; light?: boolean }) {
  return (
    <View style={s.field}>
      <Text style={[s.fieldLabel, light && { color: colors.onNavyMuted }]}>{label}</Text>
      {typeof value === 'string' || typeof value === 'number'
        ? <Text style={[s.fieldValue, light && { color: colors.onNavy }]}>{value}</Text>
        : value}
    </View>
  );
}

// ---- Status ----

type Tone = 'neutral' | 'blue' | 'green' | 'red' | 'amber';
const TONES: Record<Tone, [string, string]> = {
  neutral: [colors.well, colors.muted],
  blue: [colors.primarySoft, colors.primary],
  green: [colors.greenSoft, colors.green],
  red: [colors.redSoft, colors.red],
  amber: [colors.amberSoft, colors.amber],
};

/** A compact status tag. Use beside or below content, never as an eyebrow above a heading. */
export function Pill({ text, tone = 'neutral', dot }: { text: string; tone?: Tone; dot?: boolean }) {
  const [bg, fg] = TONES[tone];
  return (
    <View style={[s.pill, { backgroundColor: bg }]}>
      {dot ? <View style={[s.dot, { backgroundColor: fg }]} /> : null}
      <Text style={[s.pillText, { color: fg }]}>{text}</Text>
    </View>
  );
}

/** A plain status line: coloured dot and text. */
export function Status({ text, tone = 'neutral', light }: { text: string; tone?: Tone; light?: boolean }) {
  const fg = TONES[tone][1];
  const dotColor = light && tone === 'green' ? '#4ADE80' : light && tone === 'red' ? '#FF8A80' : fg;
  return (
    <View style={s.status}>
      <View style={[s.dot, { backgroundColor: dotColor }]} />
      <Text style={[s.statusText, { color: light ? colors.onNavy : colors.ink }]}>{text}</Text>
    </View>
  );
}

/** Horizontal meter, e.g. spent of cap. */
export function Meter({ value, max, color = colors.primary, track = colors.well }: { value: number; max: number; color?: string; track?: string }) {
  const pct = max > 0 ? Math.min(1, Math.max(0, value / max)) : 0;
  return (
    <View style={[s.meter, { backgroundColor: track }]} accessibilityRole="progressbar"
      accessibilityValue={{ min: 0, max, now: value }}>
      <View style={[s.meterFill, { width: `${pct * 100}%`, backgroundColor: color }]} />
    </View>
  );
}

/** Inline error, next to what failed (instead of a popup). */
export function ErrorNote({ text }: { text: string }) {
  return (
    <View style={s.error} accessibilityRole="alert">
      <Icon name="x" size={18} color={colors.red} strokeWidth={2.5} />
      <Text style={s.errorText}>{text}</Text>
    </View>
  );
}

// ---- Controls ----

type ButtonKind = 'primary' | 'secondary' | 'danger' | 'ghost' | 'light';

export function Button({
  title, onPress, kind = 'primary', disabled, big, subtitle, busy,
}: { title: string; onPress: () => void; kind?: ButtonKind; disabled?: boolean; big?: boolean; subtitle?: string; busy?: boolean }) {
  const palette: Record<ButtonKind, [string, string]> = {
    primary: [colors.primary, '#fff'],
    secondary: [colors.well, colors.ink],
    danger: [colors.red, '#fff'],
    ghost: ['transparent', colors.primary],
    light: ['#FFFFFF1F', '#fff'],
  };
  const [bg, fg] = palette[kind];
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={subtitle ? `${title}. ${subtitle}` : title}
      accessibilityState={{ disabled: !!disabled || !!busy, busy: !!busy }}
      onPress={() => {
        Haptics.selectionAsync().catch(() => {});
        onPress();
      }}
      disabled={disabled || busy}
      style={({ pressed }) => [
        s.button,
        big && s.buttonBig,
        { backgroundColor: bg, opacity: disabled ? 0.4 : pressed ? 0.85 : 1, transform: [{ scale: pressed ? 0.98 : 1 }] },
      ]}
    >
      {busy ? <ActivityIndicator color={fg} /> : <Text style={[s.buttonText, big && s.buttonTextBig, { color: fg }]}>{title}</Text>}
      {subtitle && !busy ? <Text style={[s.buttonSub, { color: fg }]}>{subtitle}</Text> : null}
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
      style={({ pressed }) => [s.chip, active && s.chipActive, pressed && { opacity: 0.8 }]}
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
  screen: { flexGrow: 1, paddingHorizontal: 20, paddingTop: space.md, paddingBottom: space.xl, gap: space.lg },
  card: { backgroundColor: colors.card, borderRadius: radius.lg, padding: 20, gap: space.md },
  cardNavy: { backgroundColor: colors.navy },
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: space.sm, alignItems: 'center' },
  title: { fontFamily: font.bold, fontSize: 30, lineHeight: 34, color: colors.ink, letterSpacing: -0.8 },
  big: { fontFamily: font.heavy, fontSize: 56, lineHeight: 60, color: colors.ink, letterSpacing: -2, fontVariant: ['tabular-nums'] },
  body: { fontFamily: font.medium, fontSize: 17, lineHeight: 24, color: colors.ink },
  muted: { fontFamily: font.regular, fontSize: 15, lineHeight: 21, color: colors.muted },
  label: { fontFamily: font.semibold, fontSize: 15, lineHeight: 20, color: colors.muted },
  field: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: space.md, paddingVertical: 6 },
  fieldLabel: { fontFamily: font.regular, fontSize: 16, color: colors.muted },
  fieldValue: { fontFamily: font.semibold, fontSize: 16, color: colors.ink, flexShrink: 1, textAlign: 'right', fontVariant: ['tabular-nums'] },
  pill: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 10, paddingVertical: 5, borderRadius: radius.pill, alignSelf: 'flex-start' },
  pillText: { fontFamily: font.semibold, fontSize: 13 },
  status: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  statusText: { fontFamily: font.medium, fontSize: 15 },
  dot: { width: 8, height: 8, borderRadius: 4 },
  meter: { height: 10, borderRadius: radius.pill, overflow: 'hidden' },
  meterFill: { height: '100%', borderRadius: radius.pill },
  error: { flexDirection: 'row', gap: 10, alignItems: 'flex-start', backgroundColor: colors.redSoft, borderRadius: radius.md, padding: 14 },
  errorText: { flex: 1, fontFamily: font.medium, fontSize: 15, lineHeight: 21, color: colors.red },
  button: { minHeight: 56, paddingVertical: 14, paddingHorizontal: 22, borderRadius: radius.pill, alignItems: 'center', justifyContent: 'center' },
  buttonBig: { minHeight: 72 },
  buttonText: { fontFamily: font.semibold, fontSize: 17 },
  buttonTextBig: { fontFamily: font.bold, fontSize: 20, letterSpacing: -0.3 },
  buttonSub: { fontFamily: font.regular, fontSize: 14, opacity: 0.85, marginTop: 2 },
  chip: { minHeight: 44, justifyContent: 'center', paddingHorizontal: 18, borderRadius: radius.pill, backgroundColor: colors.well },
  chipActive: { backgroundColor: colors.primary },
  chipText: { fontFamily: font.semibold, fontSize: 15, color: colors.ink },
});
