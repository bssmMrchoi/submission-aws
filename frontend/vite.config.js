import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 로컬 개발: /api 요청을 FastAPI(8000)로 넘긴다. 운영에서는 CloudFront가 이 역할을 한다.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://localhost:8000' } },
})
