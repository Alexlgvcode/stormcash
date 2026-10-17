// First launch: choose a role (or a demo label), point at the server, register (§19.1).
import { useState } from 'react';
import { Alert, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { Logo } from '../components/Header';
import { useNav } from '../nav';
import { register } from '../registration';
import {
  getApiBase, getServerPub, setApiBase, setDemoLabel, setServerPub, type DemoLabel, type Role,
} from '../settings';
import { Body, Button, Card, Chip, colors, ErrorNote, font, Label, Muted, radius, Row, Screen, Section } from '../components/ui';

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
  const [advanced, setAdvanced] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pickPreset = (p: (typeof PRESETS)[number]) => {
    setLabel(p.label);
    setRoleState(p.role);
    setName(p.name);
  };

  const submit = async () => {
    if (!name.trim()) return setError('Enter a name for this phone.');
    setError(null);
    setBusy(true);
    try {
      setApiBase(apiBase.trim());
      setServerPub(serverPub.trim() || null);
      setDemoLabel(label);
      const warnings = await register(role, name.trim(), label);
      if (warnings.length) Alert.alert('Registered', warnings.join('\n'));
      nav.home();
    } catch (e) {
      setError(`Registration failed: ${e instanceof Error ? e.message : String(e)}. Check the server URL and that this phone is online.`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen>
      <Card tone="navy" style={{ gap: 10, paddingVertical: 28 }}>
        <Logo light />
        <Text style={styles.hero}>Pay local shops when the network is down.</Text>
        <Muted color="#C7D2FE">Setup needs internet once. After that, payments work phone to phone.</Muted>
      </Card>

      <Section title="This phone is">
        {PRESETS.map((p) => (
          <Pressable
            key={p.label}
            onPress={() => pickPreset(p)}
            style={[styles.option, label === p.label && styles.optionActive]}
            accessibilityRole="radio"
            accessibilityState={{ checked: label === p.label }}
          >
            <View style={{ flex: 1 }}>
              <Body>{p.name}</Body>
              <Muted>{p.role === 'resident' ? 'Resident · pays shops' : 'Shop · takes payments'}</Muted>
            </View>
            <View style={[styles.radio, label === p.label && styles.radioOn]} />
          </Pressable>
        ))}
      </Section>

      <Section title="Or set it up yourself">
        <Row>
          <Chip text="Resident" active={role === 'resident'} onPress={() => setRoleState('resident')} />
          <Chip text="Shop" active={role === 'merchant'} onPress={() => setRoleState('merchant')} />
        </Row>
        <TextInput
          style={styles.input}
          value={name}
          onChangeText={setName}
          placeholder={role === 'resident' ? 'Your name' : 'Shop name'}
          placeholderTextColor={colors.faint}
        />
      </Section>

      <Pressable onPress={() => setAdvanced(!advanced)}>
        <Text style={styles.link}>{advanced ? 'Hide' : 'Show'} server settings</Text>
      </Pressable>
      {advanced ? (
        <Card>
          <Label>Server URL</Label>
          <TextInput style={styles.input} value={apiBase} onChangeText={setApiBaseState}
            autoCapitalize="none" autoCorrect={false} keyboardType="url" />
          <Label>Server public key</Label>
          <TextInput style={[styles.input, styles.mono]} value={serverPub} onChangeText={setServerPubState}
            autoCapitalize="none" autoCorrect={false} multiline />
        </Card>
      ) : null}

      {error ? <ErrorNote text={error} /> : null}
      <Button title="Register this phone" big onPress={submit} busy={busy} disabled={!name.trim()} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  hero: { fontFamily: font.bold, fontSize: 30, lineHeight: 34, color: '#fff', letterSpacing: -0.9 },
  option: { flexDirection: 'row', alignItems: 'center', gap: 12, padding: 18, borderRadius: radius.lg, backgroundColor: colors.card },
  optionActive: { backgroundColor: colors.primarySoft },
  radio: { width: 22, height: 22, borderRadius: 11, borderWidth: 2, borderColor: colors.faint },
  radioOn: { borderColor: colors.primary, borderWidth: 7 },
  input: {
    borderWidth: 1, borderColor: colors.line, borderRadius: radius.md, padding: 16, fontSize: 17,
    fontFamily: font.medium, backgroundColor: colors.card, color: colors.ink,
  },
  mono: { fontFamily: 'Menlo', fontSize: 13 },
  link: { fontFamily: font.semibold, fontSize: 16, color: colors.primary, paddingVertical: 12 },
});
