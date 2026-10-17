// Hidden demo menu (long-press the logo, §19.2).
import { useState } from 'react';
import { Alert, StyleSheet, TextInput } from 'react-native';
import { Body, Button, Chip, colors, Muted, Row, Screen, Title } from '../components/ui';
import {
  deleteDeviceKey, deviceKey, enclaveAvailable, getDeviceKey, setWantsEnclave, wantsEnclave,
} from '../keys';
import { useNav } from '../nav';
import {
  getDemoLabel, getRole, getServerPub, setDemoLabel, setServerPub, type DemoLabel,
} from '../settings';
import { isTopologyOn } from '../demo/topology';
import { resetDb, setSetting } from '../store/db';
import { syncManager } from '../sync/manager';

const LABELS: DemoLabel[] = ['MAYA', 'PHARMACY', 'GAS_STATION'];

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

  const toggleTopology = () => {
    setSetting('demo_topology', topology ? '0' : '1');
    setTopology(!topology);
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
      <Title>Demo menu</Title>

      {getRole() === 'resident' ? (
        <Button title="Judge mode" kind="danger" onPress={() => nav.go({ name: 'judge' })} />
      ) : null}

      <Body>Demo label</Body>
      <Row>
        {LABELS.map((l) => <Chip key={l} text={l} active={label === l} onPress={() => pickLabel(l)} />)}
      </Row>

      <Button
        title={`Demo topology: ${topology ? 'on' : 'off'}`}
        kind="secondary"
        onPress={toggleTopology}
      />
      <Muted>On: Pharmacy ↔ Maya ↔ Gas Station only (Pharmacy and Gas Station never link).</Muted>

      <Body>Device public key ({deviceKey().hardware ? 'Secure Enclave' : 'software key'})</Body>
      <Muted selectable>{deviceKey().pub}</Muted>
      <Button
        title={`Hardware key on next setup: ${enclave ? 'on' : 'off'}`}
        kind="secondary"
        disabled={!enclaveAvailable()}
        onPress={() => {
          setWantsEnclave(!enclave);
          setEnclave(!enclave);
        }}
      />
      <Muted>
        {enclaveAvailable() ? 'Takes effect after Reset local data, then register again.' : 'Secure Enclave not available here.'}
      </Muted>

      <Body>Server public key</Body>
      <TextInput
        style={styles.input}
        value={serverPub}
        onChangeText={setServerPubState}
        onEndEditing={() => setServerPub(serverPub.trim() || null)}
        autoCapitalize="none"
        autoCorrect={false}
      />

      <Button title="Reset local data" kind="danger" onPress={reset} />
      <Button title="Back" kind="secondary" onPress={nav.home} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  input: { borderWidth: 1, borderColor: colors.line, borderRadius: 10, padding: 12, fontSize: 14 },
});
