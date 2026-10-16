// App-level settings kept in the SQLite settings table.
import { DEFAULT_API_BASE, SERVER_PUB } from './config';
import { getSetting, setSetting } from './store/db';

export type Role = 'resident' | 'merchant';
export type DemoLabel = 'MAYA' | 'PHARMACY' | 'GAS_STATION';

export const getRole = (): Role | null => getSetting('role') as Role | null;
export const setRole = (r: Role | null): void => setSetting('role', r);

export const getDemoLabel = (): DemoLabel | null => getSetting('demo_label') as DemoLabel | null;
export const setDemoLabel = (l: DemoLabel | null): void => setSetting('demo_label', l);

export const getApiBase = (): string => getSetting('api_base') ?? DEFAULT_API_BASE;
export const setApiBase = (url: string): void => setSetting('api_base', url.replace(/\/+$/, ''));

export const getServerPub = (): string => getSetting('server_pub') ?? SERVER_PUB;
export const setServerPub = (pub: string | null): void => setSetting('server_pub', pub);

export const getDisplayName = (): string | null => getSetting('display_name');
export const setDisplayName = (n: string): void => setSetting('display_name', n);

export const getResidentId = (): string | null => getSetting('resident_id');
export const setResidentId = (id: string): void => setSetting('resident_id', id);
