// Must load before anything that calls crypto.getRandomValues (noble key generation, nonces).
import 'react-native-get-random-values';
import { registerRootComponent } from 'expo';

import App from './App';

registerRootComponent(App);
