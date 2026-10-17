// Shows a StormCash QR payload on a white plate (scanners need dark-on-light with a quiet zone).
// Error correction L keeps PAY codes scannable (§7.3, §23).
import { StyleSheet, useWindowDimensions, View } from 'react-native';
import QRCode from 'react-native-qrcode-svg';

const INSET = 40 + 32; // screen gutters + plate padding

export function QrCode({ value }: { value: string }) {
  const { width } = useWindowDimensions();
  const size = Math.min(width - INSET, 380);
  return (
    <View style={styles.plate}>
      <QRCode value={value} size={size} ecl="L" quietZone={4} color="#0A0F14" backgroundColor="#FFFFFF" />
    </View>
  );
}

const styles = StyleSheet.create({
  plate: { backgroundColor: '#FFFFFF', borderRadius: 24, padding: 16, alignSelf: 'center' },
});
