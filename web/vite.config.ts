import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    proxy: {
      ...Object.fromEntries(
        ['/health', '/docs', '/openapi.json', '/v1'].map((path) => [
          path,
          { target: 'http://api:8000', changeOrigin: true },
        ]),
      ),
    },
  },
})
