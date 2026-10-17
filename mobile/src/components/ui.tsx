// StormCash design system: tokens and the few components every screen is built from.
// Judges stand about a metre away (spec §18), so type is large and contrast is high.
// House rules (taste-skill): one typeface (Geist), one accent, surfaces separated by tone steps
// (no shadows at rest, no hairlines, no outlined boxes), round buttons, sentence-case labels.
import * as Haptics from 'expo-haptics';
import type { ReactNode } from 'react';
import { useEffect, useRef } from 'react';
import {
  AccessibilityInfo, ActivityIndicator, Animated, ImageBackground, Pressable, ScrollView, StyleSheet, Text, View,
  type ViewStyle,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Icon } from './Icon';

export const font = {
  regular: 'Geist_400Regular',
  medium: 'Geist_500Medium',
  semibold: 'Geist_600SemiBold',
  bold: 'Geist_700Bold',
  heavy: 'Geist_800ExtraBold',
  display: 'BricolageGrotesque_800ExtraBold', // figures and headlines only
  displayBold: 'BricolageGrotesque_700Bold',
};

export const colors = {
  bg: '#0A0F14', // storm night: the ground
  card: '#131B24', // one tone step up
  well: '#1C2632', // two steps up: secondary buttons, keys, chips
  ink: '#F3F5F7', // headings, amounts, running text
  text: '#F3F5F7',
  muted: '#93A0AF', // secondary notes
  faint: '#5F6B79',
  line: '#2A3542', // form fields and radar rings only
  primary: '#FFB547', // the one accent: storm-warning amber, actions only
  onPrimary: '#1A1205',
  primarySoft: '#33270F',
  green: '#3DD68C',
  greenSoft: '#11291D',
  red: '#FF6B5E',
  redSoft: '#331513',
  amber: '#FFB547',
  amberSoft: '#33270F',
  okBg: '#0D7A45', // result screens
  refuseBg: '#C4291E',
  navy: '#0A0F14',
  navyRaised: '#131B24',
  onNavy: '#F3F5F7',
  onNavyMuted: '#93A0AF',
};

export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 };
export const radius = { sm: 12, md: 16, lg: 24, pill: 999 };

// Ultra-subtle film grain over the ground (generated locally, tiled).
const GRAIN = require('../../assets/grain.png');

// ---- Layout ----

export function Screen({
  children, scroll = true, style, tone = 'default',
}: { children: ReactNode; scroll?: boolean; style?: ViewStyle; tone?: 'default' | 'dark' }) {
  const bg = tone === 'dark' ? colors.navy : colors.bg;
  const body = <View style={[s.screen, style]}>{children}</View>;
  return (
    <View style={[s.fill, { backgroundColor: bg }]}>
      <ImageBackground source={GRAIN} resizeMode="repeat" style={StyleSheet.absoluteFill} imageStyle={{ opacity: 1 }} />
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

/** Fades its children up into place once, after `delay` ms. Skipped under Reduce Motion. */
export function FadeUp({ children, delay = 0, style }: { children: ReactNode; delay?: number; style?: ViewStyle }) {
  const t = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    let cancelled = false;
    AccessibilityInfo.isReduceMotionEnabled()
      .then((reduce) => {
        if (cancelled) return;
        if (reduce) t.setValue(1);
        else Animated.timing(t, { toValue: 1, duration: 420, delay, useNativeDriver: true }).start();
      })
      .catch(() => t.setValue(1));
    return () => {
      cancelled = true;
    };
  }, [delay, t]);
  const translateY = t.interpolate({ inputRange: [0, 1], outputRange: [18, 0] });
  return <Animated.View style={[style, { opacity: t, transform: [{ translateY }] }]}>{children}</Animated.View>;
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
    light: ['#FFFFFF24', '#fff'],
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
  topBar: { flexDirection: 'row', alignItems: 'center', gap: 8, marginHorizontal: -8, minHeight: 48 },
  back: { width: 44, height: 44, borderRadius: 22, alignItems: 'center', justifyContent: 'center' },
  topTitle: { flex: 1, fontFamily: font.semibold, fontSize: 17, color: colors.ink, textAlign: 'center' },
  card: { backgroundColor: colors.card, borderRadius: radius.lg, padding: 20, gap: space.md },
  cardNavy: { backgroundColor: colors.card },
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: space.sm, alignItems: 'center' },
  title: { fontFamily: font.display, fontSize: 34, lineHeight: 36, color: colors.ink, letterSpacing: -1 },
  big: { fontFamily: font.display, fontSize: 64, lineHeight: 68, color: colors.ink, letterSpacing: -2, fontVariant: ['tabular-nums'] },
  body: { fontFamily: font.medium, fontSize: 17, lineHeight: 24, color: colors.ink },
  muted: { fontFamily: font.regular, fontSize: 15, lineHeight: 21, color: colors.muted },
  label: { fontFamily: font.semibold, fontSize: 15, lineHeight: 20, color: colors.muted },
  field: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: space.md, paddingVertical: 6 },
  fieldLabel: { fontFamily: font.regular, fontSize: 16, color: colors.muted },
  fieldValue: { fontFamily: font.semibold, fontSize: 16, color: colors.ink, flexShrink: 1, textAlign: 'right', fontVariant: ['tabular-nums'] },
  group: { backgroundColor: colors.card, borderRadius: radius.lg, overflow: 'hidden', paddingVertical: 4 },
  cell: { flexDirection: 'row', alignItems: 'center', gap: 12, minHeight: 64, paddingHorizontal: 18, paddingVertical: 12 },
  cellTitle: { fontFamily: font.semibold, fontSize: 17, color: colors.ink },
  cellDetail: { fontFamily: font.regular, fontSize: 14, lineHeight: 19, color: colors.muted },
  cellValue: { fontFamily: font.semibold, fontSize: 17, color: colors.ink, fontVariant: ['tabular-nums'] },
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
  chipTextActive: { color: colors.onPrimary },
  chipText: { fontFamily: font.semibold, fontSize: 15, color: colors.ink },
});
