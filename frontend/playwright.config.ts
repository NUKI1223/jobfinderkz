import { defineConfig, devices } from '@playwright/test'
export default defineConfig({
  testDir:'./tests', timeout:60000, expect:{timeout:12000}, fullyParallel:false, workers:1,
  reporter:[['list'],['html',{open:'never'}]],
  use:{baseURL:'http://localhost:5174',trace:'retain-on-failure',screenshot:'only-on-failure',
    launchOptions:{args:['--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream']}},
  projects:[{name:'chromium',use:{...devices['Desktop Chrome']}},
    {name:'chrome',use:{...devices['Desktop Chrome'],channel:'chrome'},grep:/record audio/},
    {name:'edge',use:{...devices['Desktop Edge'],channel:'msedge'},grep:/record audio/}],
  webServer:{command:'npm run dev -- --port 5174',url:'http://localhost:5174',reuseExistingServer:!process.env.CI,
    env:{API_TARGET:'http://localhost:8001'}}
})
