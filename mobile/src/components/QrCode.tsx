// Shows a StormCash QR payload. Error correction L keeps PAY codes scannable (§7.3, §23).
import { useWindowDimensions } from 'react-native';
import QRCode from 'react-native-qrcode-svg';

// Screen gutters (2 × 20) + card padding (2 × 12) leave this much room inside a Card.
const INSET = 64;

export function QrCode({ value }: { value: string }) {
  const { width } = useWindowDimensions();
  const size = Math.min(width - INSET, 380);
  return <QRCode value={value} size={size} ecl="L" quietZone={10} color="#0B1B2B" />;
}
