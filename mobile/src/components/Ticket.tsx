// The payment code as a receipt ticket: the real-world artefact of a payment. White paper so the
// QR scans, shop and amount on the stub, a perforation, then the code.
import { StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import QRCode from 'react-native-qrcode-svg';
import { colors, font } from './ui';

const INK = '#1F2328';

export function Ticket({
  value, kicker, title, amount, footnote, dim, copy,
}: { value: string; kicker: string; title: string; amount: string; footnote?: string; dim?: boolean; copy?: boolean }) {
  const paper = copy ? colors.sheet : colors.card; // the payer's copy is canary; the shop's request is white
  const { width } = useWindowDimensions();
  const qr = Math.min(width - 40 - 48, 340);
  return (
    <View style={[styles.ticket, { backgroundColor: paper }, dim && { opacity: 0.35 }]} accessible accessibilityLabel={`${kicker} ${title}, ${amount}. Payment code.`}>
      <View style={styles.stub}>
        <Text style={styles.kicker}>{kicker}</Text>
        <View style={styles.stubRow}>
          <Text style={styles.title} numberOfLines={1}>{title}</Text>
          <Text maxFontSizeMultiplier={1.15} style={styles.amount}>{amount}</Text>
        </View>
      </View>
      <View style={styles.perf}>
        <View style={[styles.notch, { left: -14 }]} />
        <View style={styles.dots}>
          {Array.from({ length: 24 }).map((_, i) => <View key={i} style={styles.dot} />)}
        </View>
        <View style={[styles.notch, { right: -14 }]} />
      </View>
      <View style={styles.code}>
        <QRCode value={value} size={qr} ecl="L" quietZone={0} color={INK} backgroundColor={paper} />
        {footnote ? <Text style={styles.foot}>{footnote}</Text> : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  ticket: { borderRadius: 8, overflow: 'visible' },
  stub: { paddingHorizontal: 24, paddingTop: 20, paddingBottom: 16, gap: 4 },
  kicker: { fontFamily: font.regular, fontSize: 16, color: colors.muted },
  stubRow: { flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between', gap: 12 },
  title: { flex: 1, fontFamily: font.bold, fontSize: 22, color: INK },
  amount: { fontFamily: font.display, fontSize: 48, lineHeight: 48, color: colors.carbon, fontVariant: ['tabular-nums'] },
  perf: { height: 28, justifyContent: 'center' },
  notch: { position: 'absolute', width: 28, height: 28, borderRadius: 14, backgroundColor: colors.bg, top: 0 },
  dots: { flexDirection: 'row', justifyContent: 'space-between', marginHorizontal: 22 },
  dot: { width: 5, height: 5, borderRadius: 3, backgroundColor: colors.line },
  code: { alignItems: 'center', paddingHorizontal: 24, paddingBottom: 22, paddingTop: 8, gap: 12 },
  foot: { fontFamily: font.regular, fontSize: 15, color: colors.muted },
});
