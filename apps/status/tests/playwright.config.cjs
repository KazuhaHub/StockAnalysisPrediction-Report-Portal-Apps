const { defineConfig } = require('@playwright/test')
module.exports = defineConfig({ testDir: '.', testMatch: '*.spec.cjs', workers: 1, timeout: 90000, expect: { timeout: 15000 }, use: { headless: true, actionTimeout: 15000, locale: 'en-US', screenshot: 'only-on-failure', trace: 'retain-on-failure' }, reporter: 'list' })
