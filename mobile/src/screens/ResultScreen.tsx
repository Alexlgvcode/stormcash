// Merchant result (§8.2, §19.2). Green: verified and backed. Red: names the failed check and rule.
import * as Haptics from 'expo-haptics';
import { useEffect } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Button, colors, wholeDollars } from '../components/ui';
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
  useEffect(() => {
    Haptics.notificationAsync(ok ? Haptics.NotificationFeedbackType.Success : Haptics.NotificationFeedbackType.Error)
      .catch(() => {});
  }, [ok]);

  return (
    <SafeAreaView style={[styles.fill, { backgroundColor: ok ? colors.green : colors.red }]} edges={['top', 'bottom']}>
      <View style={styles.body}>
        <View style={styles.markRing}>
          <Text style={styles.mark}>{ok ? '✓' : '✕'}</Text>
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

const styles = StyleSheet.create({
  fill: { flex: 1 },
  body: { flex: 1, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 28, gap: 14 },
  markRing: {
    width: 132, height: 132, borderRadius: 66, borderWidth: 6, borderColor: '#FFFFFF66',
    alignItems: 'center', justifyContent: 'center', marginBottom: 8,
  },
  mark: { fontSize: 72, color: '#fff', fontWeight: '900' },
  head: { fontSize: 48, color: '#fff', fontWeight: '900', letterSpacing: -1 },
  amount: { fontSize: 40, color: '#fff', fontWeight: '800', fontVariant: ['tabular-nums'] },
  copy: { fontSize: 24, lineHeight: 32, color: '#fff', textAlign: 'center', fontWeight: '600' },
  detail: { backgroundColor: '#00000022', borderRadius: 14, paddingHorizontal: 14, paddingVertical: 10, marginTop: 8 },
  detailText: { fontSize: 15, color: '#FFFFFFE6', textAlign: 'center' },
  footer: { paddingHorizontal: 20, paddingBottom: 12 },
});
