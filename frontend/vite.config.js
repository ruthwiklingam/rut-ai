import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [vue()],
  define: {
    // amazon-cognito-identity-js references Node's `global` — polyfill for browsers
    global: 'globalThis',
  },
})