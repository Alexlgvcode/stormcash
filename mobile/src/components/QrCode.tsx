// Shows a StormCash QR payload. Error correction L keeps PAY codes scannable (§7.3, §23).
import { useWindowDimensions, View } from 'react-native';
import QRCode from 'react-native-qrcode-svg';

export function QrCode({ value }: { value: string }) {
  const { width } = useWindowDimensions();
  const size = Math.min(width - 40, 360);
  return (
    <View style={{ alignItems: 'center', padding: 8, backgroundColor: '#fff' }}>
      <QRCode value={value} size={size} ecl="L" quietZone={12} />
    </View>
  );
}
