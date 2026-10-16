import { defineConfig } from 'vitest/config';
import { resolve } from 'node:path';

export default defineConfig({
  test: { include: ['src/**/__tests__/**/*.test.ts'] },
  resolve: { alias: { 'expo-sqlite': resolve(__dirname, 'test/expo-sqlite.ts') } },
});
