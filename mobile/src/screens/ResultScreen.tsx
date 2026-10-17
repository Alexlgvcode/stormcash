// Merchant result (§8.2, §19.2). Green: verified and backed. Red: names the failed check and rule.
import * as Haptics from 'expo-haptics';
import { useEffect, useRef } from 'react';
import { AccessibilityInfo, Animated, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Icon } from '../components/Icon';
import { Button, colors, font, wholeDollars } from '../components/ui';
import { useNav } from '../nav';
import type { CheckResult, Pay, ReasonToken } from '../protocol';

// Red-screen copy per check (§8.2); the machine reason token is shown small underneath.
const RULE_COPY: Record<string, string> = {
  SAME_COUNTER: 'same counter', BROKEN_LINK: 'broken link', TOTAL_BACKWARDS: 'total went backwards',
};
function refusalCopy(reason: ReasonToken, rule: string | null): string {
  switch (reason) {
    case 'BAD_CERT_SIG': return 'Certificate not issued by StormCash';
    case 'EXPIRED': return 'Certificate expired';
    case 'FROZEN': return 'Certificate frozen';
    case 'WRONG_CERT': case 'BAD_TAG_SIG': return "Signature doesn't match";
    case 'DETAILS_MISMATCH': case 'WRONG_MERCHANT': case 'WRONG_NONCE': case 'WRONG_AMOUNT': case 'REQ_EXPIRED':
      return 'Payment is for a different request';
    case 'BAD_AMOUNT': case 'OVER_CAP': return 'Over certificate cap';
    case 'OVER_LIMIT': return "Over this shop's limit";
    default:
      return rule
        ? `These funds were already spent nearby (Rule: ${RULE_COPY[rule]}). Certificate flagged.`
        : 'These funds were already spent nearby. Certificate flagged.';
  }
}

export function ResultScreen({ result, pay, capCents }: { result: CheckResult; pay: Pay | null; capCents: number }) {
  const nav = useNav();
  const ok = result.ok;
  const pop = useRef(new Animated.Value(0.6)).current;
  useEffect(() => {
    AccessibilityInfo.isReduceMotionEnabled().then((reduce) => {
      if (reduce) pop.setValue(1);
      else Animated.spring(pop, { toValue: 1, friction: 5, tension: 120, useNativeDriver: true }).start();
    }).catch(() => pop.setValue(1));
  }, [pop]);
  useEffect(() => {
    Haptics.notificationAsync(ok ? Haptics.NotificationFeedbackType.Success : Haptics.NotificationFeedbackType.Error)
      .catch(() => {});
  }, [ok]);

  return (
    <SafeAreaView style={[styles.fill, { backgroundColor: ok ? colors.okBg : colors.refuseBg }]} edges={['top', 'bottom']}>
      <View style={styles.body}>
        <View style={styles.markWrap}>
        {[0, 1, 2].map((i) => <Ripple key={i} delay={i * 450} />)}
        <Animated.View style={[styles.markRing, { transform: [{ scale: pop }] }]}>
          <Icon name={ok ? 'check' : 'x'} size={76} color="#fff" strokeWidth={2.75} />
        </Animated.View>
        </View>
        <Text style={styles.head} accessibilityRole="header">{ok ? 'Verified' : 'Refused'}</Text>
        {ok ? (
          <>
            <Text style={styles.amount}>{wholeDollars(pay?.t.amount_cents ?? 0)}</Text>
            <Text style={styles.copy}>
              Backed by Capital One, {wholeDollars(pay?.t.cum_cents ?? 0)} of {wholeDollars(capCents)} used.
            </Text>
          </>
        ) : (
          <Text style={styles.copy}>{refusalCopy(result.reason, result.rule)}</Text>
        )}
        <View style={styles.detail}>
          <Text style={styles.detailText}>
            {ok
              ? 'All six checks passed on this phone, with no internet.'
              : `Check ${result.check} failed · ${result.reason}${result.conflict ? ' · signed evidence saved' : ''}`}
          </Text>
        </View>
      </View>
      <View style={styles.footer}>
        <Button title="Done" kind="light" big onPress={nav.home} />
      </View>
    </SafeAreaView>
  );
}

/** A ring that expands and fades out behind the mark, twice. Skipped under Reduce Motion. */
function Ripple({ delay }: { delay: number }) {
  const t = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    let stop = false;
    AccessibilityInfo.isReduceMotionEnabled().then((reduce) => {
      if (reduce || stop) return;
      Animated.loop(
        Animated.timing(t, { toValue: 1, duration: 1400, delay, useNativeDriver: true }),
        { iterations: 2 },
      ).start();
    }).catch(() => {});
    return () => {
      stop = true;
    };
  }, [delay, t]);
  const scale = t.interpolate({ inputRange: [0, 1], outputRange: [1, 2.4] });
  const opacity = t.interpolate({ inputRange: [0, 0.1, 1], outputRange: [0, 0.35, 0] });
  return <Animated.View style={[styles.ripple, { opacity, transform: [{ scale }] }]} />;
}

const styles = StyleSheet.create({
  markWrap: { width: 136, height: 136, alignItems: 'center', justifyContent: 'center', marginBottom: 8 },
  ripple: { position: 'absolute', width: 136, height: 136, borderRadius: 68, borderWidth: 2, borderColor: '#FFFFFF' },
  fill: { flex: 1 },
  body: { flex: 1, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 28, gap: 14 },
  markRing: {
    width: 136, height: 136, borderRadius: 68, backgroundColor: '#FFFFFF26',
    alignItems: 'center', justifyContent: 'center',
  },
  head: { fontFamily: font.display, fontSize: 60, lineHeight: 62, color: '#fff', letterSpacing: -1.5 },
  amount: { fontFamily: font.display, fontSize: 48, lineHeight: 52, color: '#fff', letterSpacing: -1, fontVariant: ['tabular-nums'] },
  copy: { fontFamily: font.semibold, fontSize: 24, lineHeight: 31, color: '#fff', textAlign: 'center', letterSpacing: -0.3 },
  detail: { backgroundColor: '#00000022', borderRadius: 14, paddingHorizontal: 14, paddingVertical: 10, marginTop: 8 },
  detailText: { fontFamily: font.medium, fontSize: 15, lineHeight: 20, color: '#FFFFFFE6', textAlign: 'center' },
  footer: { paddingHorizontal: 20, paddingBottom: 12 },
});
