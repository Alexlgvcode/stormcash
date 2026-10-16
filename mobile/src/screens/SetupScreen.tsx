// First launch: choose a role (or a demo label), point at the server, register (§19.1).
import { useState } from 'react';
import { Alert, StyleSheet, TextInput } from 'react-native';
import { useNav } from '../nav';
import { register } from '../registration';
import {
  getApiBase, getServerPub, setApiBase, setDemoLabel, setServerPub, type DemoLabel, type Role,
} from '../settings';
import { Body, Button, Chip, colors, Muted, Row, Screen, Title } from '../components/ui';

const PRESETS: { label: DemoLabel; role: Role; name: string }[] = [
  { label: 'MAYA', role: 'resident', name: 'Maya' },
  { label: 'PHARMACY', role: 'merchant', name: 'Pharmacy' },
  { label: 'GAS_STATION', role: 'merchant', name: 'Gas Station' },
];

export function SetupScreen() {
  const nav = useNav();
  const [role, setRoleState] = useState<Role>('resident');
  const [label, setLabel] = useState<DemoLabel | null>(null);
  const [name, setName] = useState('');
  const [apiBase, setApiBaseState] = useState(getApiBase());
  const [serverPub, setServerPubState] = useState(getServerPub());
  const [busy, setBusy] = useState(false);

  const pickPreset = (p: (typeof PRESETS)[number]) => {
    setLabel(p.label);
    setRoleState(p.role);
    setName(p.name);
  };

  const submit = async () => {
    if (!name.trim()) return Alert.alert('Enter a name');
    setBusy(true);
    try {
      setApiBase(apiBase.trim());
      setServerPub(serverPub.trim() || null);
      setDemoLabel(label);
      const warnings = await register(role, name.trim(), label);
      if (warnings.length) Alert.alert('Registered', warnings.join('\n'));
      nav.home();
    } catch (e) {
      Alert.alert('Registration failed', e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen>
      <Title>StormCash setup</Title>
      <Muted>Setup needs internet. After this, payments work offline.</Muted>

      <Body>Demo phone</Body>
      <Row>
        {PRESETS.map((p) => (
          <Chip key={p.label} text={p.name} active={label === p.label} onPress={() => pickPreset(p)} />
        ))}
      </Row>

      <Body>Role</Body>
      <Row>
        <Chip text="Resident" active={role === 'resident'} onPress={() => setRoleState('resident')} />
        <Chip text="Merchant" active={role === 'merchant'} onPress={() => setRoleState('merchant')} />
      </Row>

      <Body>{role === 'resident' ? 'Your name' : 'Shop name'}</Body>
      <TextInput style={styles.input} value={name} onChangeText={setName} placeholder="Name" />

      <Body>Server URL</Body>
      <TextInput style={styles.input} value={apiBase} onChangeText={setApiBaseState}
        autoCapitalize="none" autoCorrect={false} keyboardType="url" />

      <Body>Server public key (hex)</Body>
      <TextInput style={styles.input} value={serverPub} onChangeText={setServerPubState}
        autoCapitalize="none" autoCorrect={false} placeholder="02…" />

      <Button title={busy ? 'Registering…' : 'Register'} onPress={submit} disabled={busy} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  input: { borderWidth: 1, borderColor: colors.line, borderRadius: 10, padding: 12, fontSize: 16 },
});
