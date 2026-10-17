// Merchant home: shop name and Charge.
import { Header } from '../components/Header';
import { Big, Button, Muted, Screen } from '../components/ui';
import { useNav } from '../nav';
import { countsByKind } from '../store/items';
import { merchantCert } from '../store/merchant';

export function MerchantHomeScreen() {
  const nav = useNav();
  const mc = merchantCert();
  if (!mc) return null;
  const carrying = Object.values(countsByKind()).reduce((a, b) => a + (b ?? 0), 0);
  return (
    <Screen>
      <Header />
      <Big>{mc.display_name}</Big>
      <Muted>Carrying {carrying} records</Muted>
      <Button title="Charge" onPress={() => nav.go({ name: 'charge' })} />
      <Button title="Records" kind="secondary" onPress={() => nav.go({ name: 'records' })} />
    </Screen>
  );
}
