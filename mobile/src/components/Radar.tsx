// Dark mode's backdrop: a faint storm radar sweeping behind the screen (rings and a sweep only:
// no blips, since it shows no real devices). Decorative only:
// no touches, hidden from VoiceOver, and still when the user asks for reduced motion.
import { useEffect, useRef, useState } from 'react';
import { AccessibilityInfo, Animated, Easing, StyleSheet, useWindowDimensions, View } from 'react-native';
import Svg, { Circle, Line, Path } from 'react-native-svg';
import { colors } from './ui';

const SWEEP_MS = 6000; // one turn
const SLICES = 14; // the fading tail behind the sweep line, 4° each
const SLICE_DEG = 4;

const rad = (deg: number) => ((deg - 90) * Math.PI) / 180; // 0° points up

function wedge(r: number, from: number, to: number): string {
  const [x1, y1] = [r + r * Math.cos(rad(from)), r + r * Math.sin(rad(from))];
  const [x2, y2] = [r + r * Math.cos(rad(to)), r + r * Math.sin(rad(to))];
  return `M${r},${r} L${x1},${y1} A${r},${r} 0 0 1 ${x2},${y2} Z`;
}

export function Radar() {
  const { width, height } = useWindowDimensions();
  const size = Math.round(width * 1.6);
  const r = size / 2;
  const spin = useRef(new Animated.Value(0)).current;
  const [still, setStill] = useState(false);

  useEffect(() => {
    AccessibilityInfo.isReduceMotionEnabled().then(setStill).catch(() => {});
    const sub = AccessibilityInfo.addEventListener('reduceMotionChanged', setStill);
    return () => sub.remove();
  }, []);

  useEffect(() => {
    if (still) return;
    const loop = Animated.loop(
      Animated.timing(spin, { toValue: 1, duration: SWEEP_MS, easing: Easing.linear, useNativeDriver: true }),
    );
    loop.start();
    return () => loop.stop();
  }, [still, spin]);

  const rotate = spin.interpolate({ inputRange: [0, 1], outputRange: ['0deg', '360deg'] });
  const c = colors.radar;

  return (
    <View
      pointerEvents="none"
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
      style={[styles.wrap, { width: size, height: size, left: (width - size) / 2, top: height * 0.3 - r }]}
    >
      <Svg width={size} height={size}>
        {[0.25, 0.5, 0.75, 1].map((f) => (
          <Circle key={f} cx={r} cy={r} r={r * f - 1} stroke={c} strokeOpacity={0.09} strokeWidth={1} fill="none" />
        ))}
        <Line x1={r} y1={0} x2={r} y2={size} stroke={c} strokeOpacity={0.05} strokeWidth={1} />
        <Line x1={0} y1={r} x2={size} y2={r} stroke={c} strokeOpacity={0.05} strokeWidth={1} />
      </Svg>
      <Animated.View style={[StyleSheet.absoluteFill, { transform: [{ rotate }] }]}>
        <Svg width={size} height={size}>
          {Array.from({ length: SLICES }).map((_, i) => (
            <Path
              key={i}
              d={wedge(r, -(i + 1) * SLICE_DEG, -i * SLICE_DEG)}
              fill={c}
              fillOpacity={0.09 * (1 - i / SLICES)}
            />
          ))}
          <Line x1={r} y1={r} x2={r} y2={0} stroke={c} strokeOpacity={0.25} strokeWidth={1} />
        </Svg>
      </Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { position: 'absolute' },
});
