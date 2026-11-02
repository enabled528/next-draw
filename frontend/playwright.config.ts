import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './tests', testMatch: ['ui.spec.ts', 'live.spec.ts'], timeout: 30_000,
  use: { baseURL: process.env.BASE_URL || 'http://127.0.0.1:4173', headless: true, channel: 'chrome' },
});
