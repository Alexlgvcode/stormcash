import * as Network from 'expo-network';
import { useEffect, useState } from 'react';

/** True when the internet is reachable (§10.5 uplink). */
export function useOnline(): boolean {
  const [online, setOnline] = useState(false);
  useEffect(() => {
    Network.getNetworkStateAsync().then((s) => setOnline(!!s.isInternetReachable)).catch(() => {});
    const sub = Network.addNetworkStateListener((s) => setOnline(!!s.isInternetReachable));
    return () => sub.remove();
  }, []);
  return online;
}

/** Re-renders every `ms` (countdowns, clocks). */
export function useTick(ms = 1000): number {
  const [t, setT] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setT(Date.now()), ms);
    return () => clearInterval(id);
  }, [ms]);
  return t;
}
