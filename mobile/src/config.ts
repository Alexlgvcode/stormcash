// Server public key (SEC1 compressed hex). Person B generates the server key once on Friday
// and pastes its public key here (§6.3). It can be overridden from the hidden demo menu.
export const SERVER_PUB = '028b27e635cd97ce5d35db4a205bd86f0b7d444fffad267032e0c9e1792f5bd74c';

// Default API base; the cloudflared URL changes, so it is editable on the setup screen.
export const DEFAULT_API_BASE = 'http://localhost:8000';

export const DEMO_REGION = 'asheville-downtown';

// Where the device private key lives (SecureStore item name); recorded in the wallet store.
export const KEY_NAME = 'stormcash.device_priv';
export const KEY_REF = 'securestore:' + KEY_NAME;
