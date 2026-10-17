// Merchant result (§8.2, §19.2): the receipt, stamped VERIFIED or REFUSED, with the reason in words.
import * as Haptics from 'expo-haptics';
import { useEffect, useRef } from 'react';
import { AccessibilityInfo, Animated, Easing, StyleSheet, Text, View } from 'react-native';
import { Button, colors, font, Screen, wholeDollars } from '../components/ui';
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
  const ink = ok ? colors.green : colors.red;
  // The one orchestrated moment: the stamp comes down once, lands, and the phone thumps.
  const drop = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    const land = () =>
      Haptics.notificationAsync(ok ? Haptics.NotificationFeedbackType.Success : Haptics.NotificationFeedbackType.Error)
        .catch(() => {});
    AccessibilityInfo.isReduceMotionEnabled()
      .then((reduce) => {
        if (reduce) {
          drop.setValue(1);
          land();
          return;
        }
        Animated.timing(drop, { toValue: 1, duration: 220, delay: 250, easing: Easing.in(Easing.cubic), useNativeDriver: true })
          .start(() => {
            Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy).catch(() => {});
            land();
          });
      })
      .catch(() => drop.setValue(1));
  }, [drop, ok]);
  const scale = drop.interpolate({ inputRange: [0, 1], outputRange: [2.4, 1] });
  const rotate = drop.interpolate({ inputRange: [0, 1], outputRange: ['-16deg', '-8deg'] });
  const opacity = drop.interpolate({ inputRange: [0, 0.4, 1], outputRange: [0, 0.6, 1] });

  const amount = wholeDollars(pay?.t.amount_cents ?? 0);
  return (
    <Screen>
      <View style={styles.receipt}>
        <Text style={styles.kicker}>Payment received offline</Text>
        <View style={styles.row}>
          <Text style={styles.what}>Copy no. {pay?.t.counter ?? '-'}</Text>
          <Text maxFontSizeMultiplier={1.15} style={[styles.amount, { marginLeft: 'auto' }]}>{amount}</Text>
        </View>
        <Text style={styles.meta}>
          {ok
            ? `Backed by Capital One. ${wholeDollars(pay?.t.cum_cents ?? 0)} of ${wholeDollars(capCents)} used.`
            : 'Not accepted. Do not hand over the goods.'}
        </Text>
        <View style={styles.stampArea}>
          <Animated.View
            style={[styles.stamp, { borderColor: ink, opacity, transform: [{ scale }, { rotate }] }]}
            accessible
            accessibilityRole="header"
            accessibilityLabel={ok ? 'Verified' : 'Refused'}
          >
            <View style={[styles.stampInner, { borderColor: ink }]}>
              <Text allowFontScaling={false} adjustsFontSizeToFit numberOfLines={1} style={[styles.stampText, { color: ink }]}>{ok ? 'VERIFIED' : 'REFUSED'}</Text>
            </View>
          </Animated.View>
        </View>
      </View>

      <Text style={[styles.why, { color: ok ? colors.ink : colors.red }]}>
        {ok ? 'All six checks passed on this phone, with no internet.' : refusalCopy(result.reason, result.rule)}
      </Text>
      {!ok ? (
        <Text style={styles.detail}>
          Check {result.check} failed ({result.reason}).{result.conflict ? ' The signed evidence is saved and will reach the bank with the next phone online.' : ''}
        </Text>
      ) : null}
      <Button title="Done" big onPress={nav.home} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  receipt: { backgroundColor: colors.card, borderRadius: 8, padding: 22, gap: 6, marginTop: 24 },
  kicker: { fontFamily: font.regular, fontSize: 16, color: colors.muted },
  row: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'flex-end', columnGap: 12 },
  what: { fontFamily: font.bold, fontSize: 20, color: colors.ink, paddingBottom: 10 },
  amount: { fontFamily: font.display, fontSize: 72, lineHeight: 78, color: colors.carbon, fontVariant: ['tabular-nums'] },
  meta: { fontFamily: font.regular, fontSize: 17, lineHeight: 24, color: colors.ink },
  stampArea: { height: 190, alignItems: 'center', justifyContent: 'center' },
  stamp: { borderWidth: 5, borderRadius: 10, padding: 5, maxWidth: '92%' },
  stampInner: { borderWidth: 2, borderRadius: 6, paddingHorizontal: 18, paddingTop: 6, paddingBottom: 2, alignItems: 'center' },
  stampText: { fontFamily: font.display, fontSize: 72, lineHeight: 82, letterSpacing: 2 },
  why: { fontFamily: font.bold, fontSize: 24, lineHeight: 31 },
  detail: { fontFamily: font.regular, fontSize: 16, lineHeight: 23, color: colors.muted },
});
