// Weather-radar motif behind the hero figure: rings, a slow sweep, and one blip per phone
// connected nearby (real data from the sync manager). Respects Reduce Motion.
import { useEffect, useRef, useState } from 'react';
import { AccessibilityInfo, Animated, Easing, StyleSheet, View } from 'react-native';
import Svg, { Circle, Defs, Path, RadialGradient, Stop } from 'react-native-svg';
import { colors } from './ui';

const SIZE = 340;
const C = SIZE / 2;
// Blip positions (ring radius fraction, angle in degrees), stable so they don't jump.
const BLIPS: [number, number][] = [[0.62, 38], [0.82, 152], [0.45, 250], [0.9, 305], [0.7, 95]];

export function Radar({ blips = 0, accent = colors.primary }: { blips?: number; accent?: string }) {
  const spin = useRef(new Animated.Value(0)).current;
  const [reduce, setReduce] = useState(false);

  useEffect(() => {
    AccessibilityInfo.isReduceMotionEnabled().then(setReduce).catch(() => {});
    const sub = AccessibilityInfo.addEventListener('reduceMotionChanged', setReduce);
    return () => sub.remove();
  }, []);

  useEffect(() => {
    if (reduce) return;
    const loop = Animated.loop(
      Animated.timing(spin, { toValue: 1, duration: 6000, easing: Easing.linear, useNativeDriver: true }),
    );
    loop.start();
    return () => loop.stop();
  }, [reduce, spin]);

  const rotate = spin.interpolate({ inputRange: [0, 1], outputRange: ['0deg', '360deg'] });
  const wedge = `M${C} ${C} L${C} 0 A${C} ${C} 0 0 1 ${C + C * Math.sin(Math.PI / 4)} ${C - C * Math.cos(Math.PI / 4)} Z`;

  return (
    <View pointerEvents="none" style={styles.wrap} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
      <Svg width={SIZE} height={SIZE}>
        {[0.25, 0.5, 0.75, 1].map((f) => (
          <Circle key={f} cx={C} cy={C} r={C * f - 1} stroke={colors.line} strokeWidth={1} fill="none" />
        ))}
        {BLIPS.slice(0, Math.min(blips, BLIPS.length)).map(([r, deg], i) => {
          const a = (deg * Math.PI) / 180;
          return <Circle key={i} cx={C + Math.sin(a) * C * r} cy={C - Math.cos(a) * C * r} r={5} fill={accent} />;
        })}
      </Svg>
      <Animated.View style={[StyleSheet.absoluteFill, { transform: [{ rotate }] }]}>
        <Svg width={SIZE} height={SIZE}>
          <Defs>
            <RadialGradient id="sweep" cx={C} cy={C} r={C} gradientUnits="userSpaceOnUse">
              <Stop offset="0" stopColor={accent} stopOpacity={0.0} />
              <Stop offset="1" stopColor={accent} stopOpacity={0.18} />
            </RadialGradient>
          </Defs>
          <Path d={wedge} fill="url(#sweep)" />
        </Svg>
      </Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { position: 'absolute', width: SIZE, height: SIZE, right: -150, top: -10, opacity: 0.9 },
});
