// Hidden demo menu (long-press the logo, §19.2).
import { useState } from 'react';
import { Alert, StyleSheet, Switch, TextInput, View } from 'react-native';
import { Body, Button, Card, Chip, colors, Field, Muted, radius, Row, Screen, Section, Title, TopBar } from '../components/ui';
import {
  deleteDeviceKey, deviceKey, enclaveAvailable, getDeviceKey, setWantsEnclave, wantsEnclave,
} from '../keys';
import { useNav, type Route } from '../nav';
import {
  getDemoLabel, getRole, getServerPub, setDemoLabel, setServerPub, type DemoLabel,
} from '../settings';
import { isTopologyOn } from '../demo/topology';
import { resetDb, setSetting } from '../store/db';
import { syncManager } from '../sync/manager';

const LABELS: DemoLabel[] = ['MAYA', 'PHARMACY', 'GAS_STATION'];
const LABEL_NAMES: Record<DemoLabel, string> = { MAYA: 'Maya', PHARMACY: 'Pharmacy', GAS_STATION: 'Gas Station' };

// Dev-build previews of the result screen (the simulator camera can't scan). Not in Release builds.
const PREVIEW_TAG = {
  cert_id: '00'.repeat(16), counter: 1, prev_hash: '00'.repeat(32), amount_cents: 1200, cum_cents: 1200,
  details_hash: '00'.repeat(32),
};
const PREVIEW_PAY = {
  c: { cert_id: '00'.repeat(16), cert_ver: 2, holder_pub: '02' + '00'.repeat(32), cap_cents: 5000, issued_at: 0, expires_at: 0, escrow_ref: 'preview' },
  t: PREVIEW_TAG,
  d: { merchant_pub: '02' + '00'.repeat(32), nonce: '00'.repeat(16), ts: 0 },
};
const PREVIEW_OK: Route = { name: 'result', result: { ok: true }, pay: PREVIEW_PAY, capCents: 5000 };
const PREVIEW_REFUSED: Route = {
  name: 'result', pay: PREVIEW_PAY, capCents: 5000,
  result: { ok: false, check: 'C6', reason: 'SAME_COUNTER', rule: 'SAME_COUNTER', conflict: PREVIEW_TAG },
};

export function DemoMenuScreen() {
  const nav = useNav();
  const [label, setLabel] = useState(getDemoLabel());
  const [topology, setTopology] = useState(isTopologyOn());
  const [serverPub, setServerPubState] = useState(getServerPub());
  const [enclave, setEnclave] = useState(wantsEnclave());

  const pickLabel = async (l: DemoLabel) => {
    setDemoLabel(l);
    setLabel(l);
    await syncManager.stop(); // peers see the new name after a restart
    await syncManager.start();
  };

  const toggleTopology = (on: boolean) => {
    setSetting('demo_topology', on ? '1' : '0');
    setTopology(on);
  };

  const reset = () => {
    Alert.alert('Reset this phone?', 'Deletes the wallet, records, log and the device key. You will register again.', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Reset', style: 'destructive',
        onPress: async () => {
          await syncManager.stop();
          resetDb();
          setWantsEnclave(enclave); // the key choice survives the reset
          await deleteDeviceKey();
          await getDeviceKey();
          nav.go({ name: 'setup' });
        },
      },
    ]);
  };

  return (
    <Screen>
      <TopBar onBack={nav.home} />
      <Title>Demo menu</Title>
      <Muted>Hidden from customers. Long-press the logo to get here.</Muted>

      {getRole() === 'resident' ? (
        <Button title="Judge mode" subtitle="Attacker tool: roll the wallet back" kind="danger" big
          onPress={() => nav.go({ name: 'judge' })} />
      ) : null}

      <Section title="Demo phone">
        <Row>
          {LABELS.map((l) => <Chip key={l} text={LABEL_NAMES[l]} active={label === l} onPress={() => pickLabel(l)} />)}
        </Row>
        <Card>
          <Row style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}>
            <View style={{ flex: 1, gap: 2 }}>
              <Body>Demo topology</Body>
              <Muted>Pharmacy ↔ Maya ↔ Gas Station. Pharmacy and Gas Station never link.</Muted>
            </View>
            <Switch value={topology} onValueChange={toggleTopology} trackColor={{ true: colors.primary }} />
          </Row>
        </Card>
      </Section>

      <Section title="Keys">
        <Card>
          <Field label="Device key" value={deviceKey().hardware ? 'Secure Enclave' : 'Software key'} />
          <Muted selectable>{deviceKey().pub}</Muted>
          <Row style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}>
            <View style={{ flex: 1, gap: 2 }}>
              <Body>Hardware key on next setup</Body>
              <Muted>{enclaveAvailable() ? 'Takes effect after Reset, then register again.' : 'Secure Enclave not available here.'}</Muted>
            </View>
            <Switch
              value={enclave}
              disabled={!enclaveAvailable()}
              onValueChange={(v) => {
                setWantsEnclave(v);
                setEnclave(v);
              }}
              trackColor={{ true: colors.primary }}
            />
          </Row>
        </Card>
      </Section>

      <Section title="Server public key">
        <TextInput
          style={styles.input}
          value={serverPub}
          onChangeText={setServerPubState}
          onEndEditing={() => setServerPub(serverPub.trim() || null)}
          autoCapitalize="none"
          autoCorrect={false}
          multiline
        />
      </Section>

      {__DEV__ ? (
        <Section title="Dev builds only">
          <Row style={{ flexWrap: 'nowrap' }}>
            <View style={{ flex: 1 }}>
              <Button title="Preview green" kind="secondary" onPress={() => nav.go(PREVIEW_OK)} />
            </View>
            <View style={{ flex: 1 }}>
              <Button title="Preview red" kind="secondary" onPress={() => nav.go(PREVIEW_REFUSED)} />
            </View>
          </Row>
        </Section>
      ) : null}

      <Button title="Reset local data" kind="danger" onPress={reset} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  input: {
    borderWidth: 1, borderColor: colors.line, borderRadius: radius.sm, padding: 12, fontSize: 13,
    fontFamily: 'Menlo', backgroundColor: colors.well, color: colors.ink,
  },
});
