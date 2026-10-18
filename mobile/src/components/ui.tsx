// StormCash design system: tokens and the few components every screen is built from.
// Judges stand about a metre away (spec §18), so type is large and contrast is high.
// House rules (taste-skill): one typeface (Geist), one accent, surfaces separated by tone steps
// (no shadows at rest, no hairlines, no outlined boxes), round buttons, sentence-case labels.
import * as Haptics from 'expo-haptics';
import type { ReactNode } from 'react';
import {
  ActivityIndicator, Appearance, Pressable, ScrollView, StyleSheet, Text, useWindowDimensions, View,
  type ViewStyle,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { getSetting } from '../store/db';
import { Icon } from './Icon';
import { Radar } from './Radar';

export const font = {
  // Atkinson Hyperlegible (Braille Institute) for everything you read; Big Shoulders (civic
  // signage) only for figures and the few headlines.
  regular: 'AtkinsonHyperlegible_400Regular',
  medium: 'AtkinsonHyperlegible_400Regular',
  semibold: 'AtkinsonHyperlegible_700Bold',
  bold: 'AtkinsonHyperlegible_700Bold',
  heavy: 'AtkinsonHyperlegible_700Bold',
  display: 'BigShouldersDisplay_800ExtraBold',
  displayBold: 'BigShouldersDisplay_700Bold',
};

// Light: the receipt book by day. Dark: the same book at night on a storm-radar screen.
// The palette is fixed when the app starts (every StyleSheet reads it once), from the phone's
// appearance or the demo menu's override; a change applies the next time the app opens.
export type ThemePref = 'system' | 'dark' | 'light';
export function themePref(): ThemePref {
  try {
    const v = getSetting('theme');
    return v === 'dark' || v === 'light' ? v : 'system';
  } catch {
    return 'system';
  }
}
export const isDark = themePref() === 'dark' || (themePref() === 'system' && Appearance.getColorScheme() === 'dark');

const light = {
  // The receipt book: cool paper, the canary duplicate sheet, carbon ink, graphite, rubber stamps.
  bg: '#F7F8F6', // paper
  card: '#FFFFFF', // a clean sheet
  sheet: '#FFE873', // the canary duplicate copy
  sheetEdge: '#E9CF4E',
  well: '#ECEEEB', // pressed paper: secondary buttons, keys, chips
  ink: '#1F2328', // graphite: text
  text: '#1F2328',
  carbon: '#2B3A9E', // carbon-copy ink: figures and the primary action
  muted: '#646B75', // pencil: secondary notes
  faint: '#9AA0A8',
  line: '#D9DCE1', // ruled form lines (form fields only)
  primary: '#1F2328',
  onPrimary: '#FFFFFF',
  primarySoft: '#E6E8EB',
  green: '#1F7A47', // the VERIFIED stamp
  greenSoft: '#E3F1E8',
  red: '#C3321F', // the REFUSED stamp
  redSoft: '#F9E5E1',
  amber: '#9A5B00',
  amberSoft: '#FCEFD9',
  okBg: '#1F7A47',
  refuseBg: '#C3321F',
  tool: '#1F2328', // judge mode: the attacker tool is a different object
  navy: '#1F2328',
  navyRaised: '#2C3138',
  onNavy: '#FFFFFF',
  onNavyMuted: '#B9BEC6',
  sheetInk: '#1F2328', // text on the canary sheet
  sheetMuted: '#6B5A12',
  sheetFigure: '#2B3A9E', // the big figure on the sheet
  radar: '#1F7A47',
};

const dark: typeof light = {
  // The night copy: deep navy desk, the duplicate sheet in dim amber with glowing figures.
  bg: '#0A0F1A',
  card: '#131B2A',
  sheet: '#211C0D',
  sheetEdge: '#4A3F18',
  well: '#1D2738',
  ink: '#E9EDF3',
  text: '#E9EDF3',
  carbon: '#9AA8FF',
  muted: '#9AA4B4',
  faint: '#5F6A7C',
  line: '#2A3446',
  primary: '#E9EDF3',
  onPrimary: '#0A0F1A',
  primarySoft: '#232D3F',
  green: '#3CCB7F',
  greenSoft: '#12301F',
  red: '#FF6B57',
  redSoft: '#3A1612',
  amber: '#F2B34A',
  amberSoft: '#33240C',
  okBg: '#1F7A47',
  refuseBg: '#C3321F',
  tool: '#05080F',
  navy: '#05080F',
  navyRaised: '#141B28',
  onNavy: '#FFFFFF',
  onNavyMuted: '#9AA4B4',
  sheetInk: '#F3E9C6',
  sheetMuted: '#C9B56A',
  sheetFigure: '#FFD54A',
  radar: '#3CCB7F',
};

export const colors = isDark ? dark : light;

export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 };
export const radius = { sm: 4, md: 14, lg: 8, pill: 999 };

// ---- Layout ----

/** iPad and other wide screens get two-column layouts; phones stay one column. */
export const WIDE_MIN = 700;
export function useWide(): boolean {
  return useWindowDimensions().width >= WIDE_MIN;
}

/**
 * One screen. `width` caps the content on wide screens: "wide" for two-column homes,
 * "narrow" for single-task flows (paying, scanning) so a phone layout isn't stretched across an iPad.
 */
export function Screen({
  children, scroll = true, style, tone = 'default', width = 'wide',
}: { children: ReactNode; scroll?: boolean; style?: ViewStyle; tone?: 'default' | 'dark'; width?: 'wide' | 'narrow' }) {
  const bg = tone === 'dark' ? colors.tool : colors.bg;
  const wide = useWide();
  const body = (
    <View style={[s.screen, wide && { paddingHorizontal: 32, maxWidth: width === 'wide' ? 1080 : 600, width: '100%', alignSelf: 'center' }, style]}>
      {children}
    </View>
  );
  return (
    <View style={[s.fill, { backgroundColor: bg }]}>
      {isDark && tone === 'default' ? <Radar /> : null}
      <SafeAreaView style={s.fill} edges={['top', 'bottom']}>
        {scroll ? (
          <ScrollView style={s.fill} contentContainerStyle={s.grow} keyboardShouldPersistTaps="handled">
            {body}
          </ScrollView>
        ) : (
          body
        )}
      </SafeAreaView>
    </View>
  );
}

/** Two columns side by side on wide screens, stacked on phones. */
export function Columns({ left, right, ratio = 1 }: { left: ReactNode; right: ReactNode; ratio?: number }) {
  const wide = useWide();
  if (!wide) return <>{left}{right}</>;
  return (
    <View style={s.columns}>
      <View style={[s.column, { flex: ratio }]}>{left}</View>
      <View style={[s.column, { flex: 1 }]}>{right}</View>
    </View>
  );
}

/** A labelled money row: label and note on the left, a tabular amount on the right. */
export function MoneyRow({ label, note, value, tone, strong }: {
  label: string; note?: string; value: string; tone?: 'green' | 'amber' | 'red'; strong?: boolean;
}) {
  const fg = tone ? TONES[tone][1] : colors.ink;
  return (
    <View style={s.moneyRow}>
      <View style={{ flex: 1, minWidth: 0, gap: 2 }}>
        <Text style={[s.moneyLabel, strong && { fontFamily: font.bold }]}>{label}</Text>
        {note ? <Text style={s.moneyNote}>{note}</Text> : null}
      </View>
      <Text maxFontSizeMultiplier={1.3} style={[s.moneyValue, { color: fg }, strong && { fontSize: 22 }]}>{value}</Text>
    </View>
  );
}

/** Top bar for subscreens: a real back button and the screen title. */
export function TopBar({ title, onBack, right }: { title?: string; onBack: () => void; right?: ReactNode }) {
  return (
    <View style={s.topBar}>
      <Pressable
        onPress={() => {
          Haptics.selectionAsync().catch(() => {});
          onBack();
        }}
        accessibilityRole="button"
        accessibilityLabel="Back"
        hitSlop={8}
        style={({ pressed }) => [s.back, pressed && { backgroundColor: colors.well }]}
      >
        <Icon name="chevron-left" size={24} color={colors.ink} strokeWidth={2.25} />
      </Pressable>
      {title ? <Text style={s.topTitle} numberOfLines={1}>{title}</Text> : <View style={{ flex: 1 }} />}
      <View style={{ minWidth: 44, alignItems: 'flex-end' }}>{right}</View>
    </View>
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
  <Text maxFontSizeMultiplier={1.15} style={[s.title, color ? { color } : null]} accessibilityRole="header">{children}</Text>
);
export const Big = ({ children, color }: { children: ReactNode; color?: string }) => (
  <Text maxFontSizeMultiplier={1.15} style={[s.big, color ? { color } : null]} adjustsFontSizeToFit numberOfLines={1}>{children}</Text>
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

/** A grouped list of rows (settings-cell style): one container, rows separated by space. */
export function Group({ children }: { children: ReactNode }) {
  return <View style={s.group}>{children}</View>;
}

/** One row in a Group. Tappable when onPress is given (shows a chevron). */
export function Cell({
  title, detail, value, onPress, accessory,
}: { title: string; detail?: string; value?: string; onPress?: () => void; accessory?: ReactNode }) {
  const body = (
    <>
      <View style={{ flex: 1, gap: 2 }}>
        <Text style={s.cellTitle}>{title}</Text>
        {detail ? <Text style={s.cellDetail}>{detail}</Text> : null}
      </View>
      {value ? <Text style={s.cellValue}>{value}</Text> : null}
      {accessory}
      {onPress ? <Icon name="chevron-right" size={20} color={colors.faint} /> : null}
    </>
  );
  if (!onPress) return <View style={s.cell}>{body}</View>;
  return (
    <Pressable
      accessibilityRole="button"
      onPress={() => {
        Haptics.selectionAsync().catch(() => {});
        onPress();
      }}
      style={({ pressed }) => [s.cell, pressed && { backgroundColor: colors.well }]}
    >
      {body}
    </Pressable>
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
  const dotColor = fg;
  return (
    <View style={s.status}>
      <View style={[s.dot, { backgroundColor: dotColor }]} />
      <Text style={[s.statusText, { color: colors.ink }]}>{text}</Text>
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
    primary: [colors.primary, colors.onPrimary],
    secondary: [colors.well, colors.ink],
    danger: [colors.refuseBg, '#fff'],
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
      <Text style={[s.chipText, active && s.chipTextActive]}>{text}</Text>
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
  columns: { flexDirection: 'row', gap: space.xl, alignItems: 'flex-start' },
  column: { minWidth: 0, gap: space.lg },
  moneyRow: { flexDirection: 'row', alignItems: 'center', gap: space.md, paddingVertical: 10 },
  moneyLabel: { fontFamily: font.semibold, fontSize: 17, color: colors.ink },
  moneyNote: { fontFamily: font.regular, fontSize: 14, lineHeight: 19, color: colors.muted },
  moneyValue: { fontFamily: font.bold, fontSize: 19, fontVariant: ['tabular-nums'] },
  topBar: { flexDirection: 'row', alignItems: 'center', gap: 8, marginHorizontal: -8, minHeight: 48 },
  back: { width: 44, height: 44, borderRadius: 22, alignItems: 'center', justifyContent: 'center' },
  topTitle: { flex: 1, fontFamily: font.semibold, fontSize: 17, color: colors.ink, textAlign: 'center' },
  card: { backgroundColor: colors.card, borderRadius: radius.lg, padding: 20, gap: space.md },
  cardNavy: { backgroundColor: colors.sheet },
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: space.sm, alignItems: 'center' },
  title: { fontFamily: font.display, fontSize: 40, lineHeight: 46, color: colors.ink, letterSpacing: -0.2 },
  big: { fontFamily: font.display, fontSize: 72, lineHeight: 80, color: colors.carbon, fontVariant: ['tabular-nums'] },
  body: { fontFamily: font.regular, fontSize: 18, lineHeight: 26, color: colors.ink },
  muted: { fontFamily: font.regular, fontSize: 16, lineHeight: 23, color: colors.muted },
  label: { fontFamily: font.bold, fontSize: 16, lineHeight: 21, color: colors.ink },
  // Wraps so that at large text sizes the value drops under its label instead of squeezing into it.
  field: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'center', columnGap: space.md, rowGap: 2, paddingVertical: 6 },
  fieldLabel: { fontFamily: font.regular, fontSize: 16, color: colors.muted },
  fieldValue: { fontFamily: font.semibold, fontSize: 16, color: colors.ink, flexShrink: 1, marginLeft: 'auto', textAlign: 'right', fontVariant: ['tabular-nums'] },
  group: { backgroundColor: colors.card, borderRadius: radius.lg, overflow: 'hidden', paddingVertical: 4 },
  cell: { flexDirection: 'row', alignItems: 'center', gap: 12, minHeight: 64, paddingHorizontal: 18, paddingVertical: 12 },
  cellTitle: { fontFamily: font.semibold, fontSize: 17, color: colors.ink },
  cellDetail: { fontFamily: font.regular, fontSize: 14, lineHeight: 19, color: colors.muted },
  cellValue: { fontFamily: font.semibold, fontSize: 17, color: colors.ink, fontVariant: ['tabular-nums'] },
  pill: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 10, paddingVertical: 5, borderRadius: radius.md, alignSelf: 'flex-start', maxWidth: '100%' }, // md, not pill: stays a capsule on one line, a rounded box when large text wraps
  pillText: { fontFamily: font.semibold, fontSize: 13, flexShrink: 1 },
  status: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  statusText: { fontFamily: font.medium, fontSize: 15 },
  dot: { width: 8, height: 8, borderRadius: 4 },
  meter: { height: 10, borderRadius: radius.pill, overflow: 'hidden' },
  meterFill: { height: '100%', borderRadius: radius.pill },
  error: { flexDirection: 'row', gap: 10, alignItems: 'flex-start', backgroundColor: colors.redSoft, borderRadius: radius.md, padding: 14 },
  errorText: { flex: 1, fontFamily: font.medium, fontSize: 15, lineHeight: 21, color: colors.red },
  button: { minHeight: 56, paddingVertical: 14, paddingHorizontal: 22, borderRadius: 10, alignItems: 'center', justifyContent: 'center' },
  buttonBig: { minHeight: 72 },
  buttonText: { fontFamily: font.semibold, fontSize: 17 },
  buttonTextBig: { fontFamily: font.bold, fontSize: 21 },
  buttonSub: { fontFamily: font.regular, fontSize: 14, opacity: 0.85, marginTop: 2 },
  chip: { minHeight: 44, justifyContent: 'center', paddingHorizontal: 18, borderRadius: 10, backgroundColor: colors.well },
  chipActive: { backgroundColor: colors.primary },
  chipTextActive: { color: colors.onPrimary },
  chipText: { fontFamily: font.semibold, fontSize: 15, color: colors.ink },
});
