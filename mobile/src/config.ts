// Server public key (SEC1 compressed hex). Person B generates the server key once on Friday
// and pastes its public key here (§6.3). It can be overridden from the hidden demo menu.
export const SERVER_PUB = '030c300f1f00882c4c6f7baada7cd83243b1a84821eacb4dd450cfc562a6446510';

// Default API base; the cloudflared URL changes, so it is editable on the setup screen.
export const DEFAULT_API_BASE = 'http://localhost:8000';

export const DEMO_REGION = 'asheville-downtown';

// Where the device private key lives (SecureStore item name); recorded in the wallet store.
export const KEY_NAME = 'stormcash.device_priv';
export const KEY_REF = 'securestore:' + KEY_NAME;
