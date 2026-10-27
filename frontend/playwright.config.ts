import { defineConfig } from '@playwright/test'
import path from 'node:path'

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: 1,
  timeout: 30000,
  use: {baseURL: 'http://127.0.0.1:8000', channel: 'chrome', viewport: {width: 1440, height: 900}, trace: 'retain-on-failure'},
  webServer: {
    command: '..\\.venv\\Scripts\\python.exe -m research_assistant.cli',
    url: 'http://127.0.0.1:8000/api/config',
    reuseExistingServer: false,
    env: {RESEARCH_DATA_DIR: path.resolve('../.tmp/browser-runs', String(Date.now())), SEC_USER_AGENT: '', OPENAI_API_KEY: '', OPENAI_BASE_URL: '', OPENROUTER_API_KEY: '', RESEARCH_MODEL_PROVIDER: '', RESEARCH_MODEL: ''},
  },
})
