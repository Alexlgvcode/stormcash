// Merchant result (§8.2, §19.2). Green: verified and backed. Red: names the failed check and rule.
import { StyleSheet, Text, View } from 'react-native';
import { Button, colors, Screen, wholeDollars } from '../components/ui';
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
  return (
    <Screen style={{ backgroundColor: ok ? colors.green : colors.red, justifyContent: 'center' }}>
      <View style={{ gap: 18 }}>
        <Text style={styles.icon}>{ok ? '✓' : '✕'}</Text>
        {ok ? (
          <>
            <Text style={styles.head}>Verified.</Text>
            <Text style={styles.body}>
              Backed by Capital One, {wholeDollars(pay?.t.cum_cents ?? 0)} of {wholeDollars(capCents)} used.
            </Text>
          </>
        ) : (
          <>
            <Text style={styles.head}>Refused</Text>
            <Text style={styles.body}>{refusalCopy(result.reason, result.rule)}</Text>
            <Text style={styles.small}>Check {result.check} · {result.reason}</Text>
          </>
        )}
        <Button title="Done" kind="secondary" onPress={nav.home} />
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  icon: { fontSize: 96, color: '#fff', fontWeight: '800', textAlign: 'center' },
  head: { fontSize: 40, color: '#fff', fontWeight: '800', textAlign: 'center' },
  body: { fontSize: 24, color: '#fff', textAlign: 'center' },
  small: { fontSize: 16, color: '#ffffffcc', textAlign: 'center' },
});
