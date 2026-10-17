import { StatusBar } from 'expo-status-bar';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, View } from 'react-native';
import { getDeviceKey } from './src/keys';
import { NavContext, type Nav, type Route } from './src/nav';
import { getRole } from './src/settings';
import { getDb } from './src/store/db';
import { syncManager } from './src/sync/manager';
import { ChargeScreen } from './src/screens/ChargeScreen';
import { DemoMenuScreen } from './src/screens/DemoMenuScreen';
import { JudgeModeScreen } from './src/screens/JudgeModeScreen';
import { MerchantHomeScreen } from './src/screens/MerchantHomeScreen';
import { PayScreen } from './src/screens/PayScreen';
import { QrSyncScreen } from './src/screens/QrSyncScreen';
import { RecordsScreen } from './src/screens/RecordsScreen';
import { ResultScreen } from './src/screens/ResultScreen';
import { SetupScreen } from './src/screens/SetupScreen';
import { WalletScreen } from './src/screens/WalletScreen';

export default function App() {
  const [ready, setReady] = useState(false);
  const [route, setRoute] = useState<Route>({ name: 'home' });
  const [, setVersion] = useState(0);

  useEffect(() => {
    getDb();
    getDeviceKey().then(() => setReady(true));
  }, []);

  const nav = useMemo<Nav>(() => ({
    go: setRoute,
    home: () => setRoute({ name: 'home' }),
    refresh: () => setVersion((v) => v + 1),
  }), []);

  // Advertise + browse while the app is open, once this phone is registered (§19.5).
  const role = ready ? getRole() : null;
  useEffect(() => {
    if (role) syncManager.start();
  }, [role]);

  const render = useCallback(() => {
    const role = getRole();
    if (!role || route.name === 'setup') return <SetupScreen />;
    switch (route.name) {
      case 'pay':
        return <PayScreen />;
      case 'charge':
        return <ChargeScreen />;
      case 'records':
        return <RecordsScreen />;
      case 'qrsync':
        return <QrSyncScreen />;
      case 'demo':
        return <DemoMenuScreen />;
      case 'judge':
        return <JudgeModeScreen />;
      case 'result':
        return <ResultScreen result={route.result} pay={route.pay} capCents={route.capCents} />;
      default:
        return role === 'resident' ? <WalletScreen /> : <MerchantHomeScreen />;
    }
  }, [route]);

  if (!ready) {
    return (
      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center' }}>
        <ActivityIndicator />
      </View>
    );
  }
  return (
    <NavContext.Provider value={nav}>
      {render()}
      <StatusBar style="dark" />
    </NavContext.Provider>
  );
}
