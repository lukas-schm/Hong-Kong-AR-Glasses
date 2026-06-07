import { defineConfig } from 'vite';

// The plugin is served over the LAN to the Even App's WebView on the phone.
// All CDARS data calls go straight to the FastAPI server (see src/config.ts),
// so no proxy is needed here.
export default defineConfig({
  server: { host: '0.0.0.0', port: 5173 },
  build: { target: 'es2022' },
});
