// Minimal stack navigation: a route state in App and a context to change it.
import { createContext, useContext } from 'react';
import type { CheckResult, Pay } from './protocol';

export type Route =
  | { name: 'setup' }
  | { name: 'home' }
  | { name: 'pay' }
  | { name: 'charge' }
  | { name: 'result'; result: CheckResult; pay: Pay | null; capCents: number }
  | { name: 'records' }
  | { name: 'qrsync' }
  | { name: 'demo' }
  | { name: 'judge' };

export interface Nav {
  go: (r: Route) => void;
  home: () => void;
  refresh: () => void; // re-render after store changes
}

export const NavContext = createContext<Nav | null>(null);

export function useNav(): Nav {
  const n = useContext(NavContext);
  if (!n) throw new Error('NavContext missing');
  return n;
}
