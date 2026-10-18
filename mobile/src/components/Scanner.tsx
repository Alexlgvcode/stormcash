// Camera QR scanner. Calls onScan once per mount with the first StormCash code it sees,
// or, with `continuous`, once for every distinct code (multi-frame QR sync).
import { CameraView, useCameraPermissions } from 'expo-camera';
import { useRef } from 'react';
import { Linking, StyleSheet, View } from 'react-native';
import { QR_PREFIX } from '../protocol';
import { Body, Button } from './ui';

export function Scanner({ onScan, continuous }: { onScan: (data: string) => void; continuous?: boolean }) {
  const [permission, requestPermission] = useCameraPermissions();
  const done = useRef(false);
  const seen = useRef(new Set<string>());

  if (!permission) return null;
  if (!permission.granted) {
    // Once access was refused, iOS never shows the prompt again: send the user to Settings.
    const blocked = !permission.canAskAgain;
    return (
      <View style={{ gap: 12 }}>
        <Body>{blocked ? 'Camera is off for StormCash. Turn it on in Settings.' : 'Camera access is needed to scan payment codes.'}</Body>
        <Button title={blocked ? 'Open Settings' : 'Allow camera'} onPress={blocked ? () => Linking.openSettings() : requestPermission} />
      </View>
    );
  }
  return (
    <View style={styles.frame}>
      <CameraView
        style={StyleSheet.absoluteFill}
        facing="back"
        barcodeScannerSettings={{ barcodeTypes: ['qr'] }}
        onBarcodeScanned={({ data }) => {
          if (done.current || !data.startsWith(QR_PREFIX)) return;
          if (continuous) {
            if (seen.current.has(data)) return;
            seen.current.add(data);
          } else {
            done.current = true;
          }
          onScan(data);
        }}
      />
      <View pointerEvents="none" style={styles.overlay}>
        <View style={[styles.corner, styles.tl]} />
        <View style={[styles.corner, styles.tr]} />
        <View style={[styles.corner, styles.bl]} />
        <View style={[styles.corner, styles.br]} />
      </View>
    </View>
  );
}

const C = 44; // corner bracket length
const styles = StyleSheet.create({
  frame: { width: '100%', aspectRatio: 1, borderRadius: 20, overflow: 'hidden', backgroundColor: '#000' },
  overlay: { position: 'absolute', top: 36, left: 36, right: 36, bottom: 36 },
  corner: { position: 'absolute', width: C, height: C, borderColor: '#fff' },
  tl: { top: 0, left: 0, borderTopWidth: 5, borderLeftWidth: 5, borderTopLeftRadius: 12 },
  tr: { top: 0, right: 0, borderTopWidth: 5, borderRightWidth: 5, borderTopRightRadius: 12 },
  bl: { bottom: 0, left: 0, borderBottomWidth: 5, borderLeftWidth: 5, borderBottomLeftRadius: 12 },
  br: { bottom: 0, right: 0, borderBottomWidth: 5, borderRightWidth: 5, borderBottomRightRadius: 12 },
});
