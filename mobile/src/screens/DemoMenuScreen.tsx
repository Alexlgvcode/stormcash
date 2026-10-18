// Hidden demo menu (long-press the logo, §19.2).
import { useState } from 'react';
import { Alert, StyleSheet, Switch, TextInput, View } from 'react-native';
import {
  Body, Button, Card, Chip, colors, Field, Muted, radius, Row, Screen, Section, themePref, Title, TopBar, type ThemePref,
} from '../components/ui';
import {
  deleteDeviceKey, deviceKey, enclaveAvailable, getDeviceKey, setWantsEnclave, wantsEnclave,
} from '../keys';
import { PREVIEW_OK, PREVIEW_REFUSED } from '../demo/previews';
import { useNav } from '../nav';
import {
  getDemoLabel, getRole, getServerPub, setDemoLabel, setServerPub, type DemoLabel,
} from '../settings';
import { isTopologyOn } from '../demo/topology';
import { resetDb, setSetting } from '../store/db';
import { isMultipeerEnabled, setMultipeerEnabled, syncManager } from '../sync/manager';

const LABELS: DemoLabel[] = ['MAYA', 'PHARMACY', 'GAS_STATION'];
const LABEL_NAMES: Record<DemoLabel, string> = { MAYA: 'Maya', PHARMACY: 'Pharmacy', GAS_STATION: 'Gas Station' };


export function DemoMenuScreen() {
  const nav = useNav();
  const [label, setLabel] = useState(getDemoLabel());
  const [topology, setTopology] = useState(isTopologyOn());
  const [multipeer, setMultipeer] = useState(isMultipeerEnabled());
  const [theme, setTheme] = useState<ThemePref>(themePref());
  const [serverPub, setServerPubState] = useState(getServerPub());
  const [enclave, setEnclave] = useState(wantsEnclave());

  const pickLabel = async (l: DemoLabel) => {
    setDemoLabel(l);
    setLabel(l);
    await syncManager.stop(); // peers see the new name after a restart
    if (isMultipeerEnabled()) await syncManager.start();
  };

  // Off: this phone stops advertising and browsing; Sync by QR still works (§21.5 backup 1).
  const toggleMultipeer = async (on: boolean) => {
    setMultipeerEnabled(on);
    setMultipeer(on);
    await syncManager.stop();
    if (on) await syncManager.start();
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
              <Muted>Maya links to the Pharmacy and the Gas Station. Those two never link to each other.</Muted>
            </View>
            <Switch value={topology} onValueChange={toggleTopology} trackColor={{ true: colors.primary }} />
          </Row>
        </Card>
        <Card>
          <Row style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}>
            <View style={{ flex: 1, gap: 2 }}>
              <Body>Phone-to-phone link</Body>
              <Muted>Bluetooth and Wi-Fi sync with nearby phones. Turn off to use Sync by QR only.</Muted>
            </View>
            <Switch value={multipeer} onValueChange={toggleMultipeer} trackColor={{ true: colors.primary }} />
          </Row>
        </Card>
      </Section>

      <Section title="Appearance">
        <Row>
          {(['system', 'dark', 'light'] as const).map((t) => (
            <Chip key={t} text={t === 'system' ? 'Phone setting' : t === 'dark' ? 'Dark' : 'Light'} active={theme === t}
              onPress={() => { setSetting('theme', t); setTheme(t); }} />
          ))}
        </Row>
        <Muted>Applies the next time StormCash opens.</Muted>
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
