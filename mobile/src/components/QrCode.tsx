// A StormCash QR on a white sheet (scanners need dark-on-light with a quiet zone). ECL L (§7.3, §23).
import { StyleSheet, useWindowDimensions, View } from 'react-native';
import QRCode from 'react-native-qrcode-svg';

export function QrCode({ value }: { value: string }) {
  const { width } = useWindowDimensions();
  const size = Math.min(width - 40 - 32, 380);
  return (
    <View style={styles.sheet}>
      <QRCode value={value} size={size} ecl="L" quietZone={0} color="#1F2328" backgroundColor="#FFFFFF" />
    </View>
  );
}

const styles = StyleSheet.create({
  sheet: { backgroundColor: '#FFFFFF', borderRadius: 8, padding: 16, alignSelf: 'center' },
});
