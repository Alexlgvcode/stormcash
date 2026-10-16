// Camera QR scanner. Calls onScan once per mount with the first StormCash code it sees,
// or, with `continuous`, once for every distinct code (multi-frame QR sync).
import { CameraView, useCameraPermissions } from 'expo-camera';
import { useRef } from 'react';
import { StyleSheet, View } from 'react-native';
import { QR_PREFIX } from '../protocol';
import { Body, Button } from './ui';

export function Scanner({ onScan, continuous }: { onScan: (data: string) => void; continuous?: boolean }) {
  const [permission, requestPermission] = useCameraPermissions();
  const done = useRef(false);
  const seen = useRef(new Set<string>());

  if (!permission) return null;
  if (!permission.granted) {
    return (
      <View style={{ gap: 12 }}>
        <Body>Camera access is needed to scan payment codes.</Body>
        <Button title="Allow camera" onPress={requestPermission} />
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
    </View>
  );
}

const styles = StyleSheet.create({
  frame: { width: '100%', aspectRatio: 1, borderRadius: 16, overflow: 'hidden', backgroundColor: '#000' },
});
