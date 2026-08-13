#!/usr/bin/env node
/** Capture missing guide screenshots only */
import { chromium } from 'playwright'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ASSETS = path.join(__dirname, 'assets')
const BASE = 'http://127.0.0.1:5173'
const CASE_ID = '76aed706-f8f4-49e0-80e2-127513910659'
const REVIEW_ID = 'ca34c91c-0d6d-4674-8c89-8c32a4b624e6'
const EMAIL = process.env.LOGIN_EMAIL
const PASSWORD = process.env.LOGIN_PASSWORD

async function shot(page, name) {
  await page.screenshot({ path: path.join(ASSETS, `${name}.png`), fullPage: false })
  console.log('saved', name)
}

async function login(page) {
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
  await page.getByLabel('Email').fill(EMAIL)
  await page.getByLabel('Пароль').fill(PASSWORD)
  await page.getByRole('button', { name: /войти/i }).click()
  await page.waitForURL(/\/cases/, { timeout: 30000 })
}

async function main() {
  const browser = await chromium.launch({ headless: true, channel: 'chrome' })
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 })).newPage()
  await login(page)

  await page.goto(`${BASE}/cases/${CASE_ID}/tabular-review/${REVIEW_ID}`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(2500)

  const docCell = page.getByText(/funds_movement|\.pdf/i).first()
  if (await docCell.count()) {
    await docCell.click()
    await page.waitForTimeout(2000)
    await shot(page, '07-tabular-source')
  }

  await page.goto(`${BASE}/cases/${CASE_ID}/tabular-review/${REVIEW_ID}`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1000)
  const menuBtn = page.locator('button').filter({ has: page.locator('svg') }).filter({ hasText: '' }).last()
  const dots = page.locator('button[aria-haspopup="menu"], button').filter({ has: page.locator('.lucide-more-horizontal, .lucide-ellipsis') }).first()
  if (await dots.count()) {
    await dots.click()
  } else {
    await page.getByRole('button').filter({ hasText: /^$/ }).nth(-1).click().catch(() => {})
  }
  await page.waitForTimeout(500)
  const exportOpt = page.getByRole('menuitem', { name: /экспорт/i }).or(page.getByText(/^Экспорт$/))
  if (await exportOpt.count()) {
    await exportOpt.first().click()
    await page.waitForTimeout(1000)
    await shot(page, '11-export')
  }

  const SESSION_ID = '24524333-b323-4535-a8b7-3c0df2c7b5ab'
  const SESSION_WITH_CITES = '3a851b0d-0154-4fed-bd5c-931a4b9abac8'
  await page.goto(`${BASE}/cases/${CASE_ID}/chat?session=${SESSION_ID}`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(5000)

  const inputCard = page.locator('.ws-input-card').first()
  await inputCard.scrollIntoViewIfNeeded().catch(() => {})
  await page.waitForTimeout(400)
  const box = await inputCard.boundingBox()
  if (box) {
    await page.screenshot({ path: path.join(ASSETS, '09-assistant-settings.png'), clip: box })
  } else {
    await shot(page, '09-assistant-settings')
  }
  console.log('saved 09-assistant-settings')

  await page.evaluate(() => window.scrollTo(0, 0))
  await page.waitForTimeout(300)
  await shot(page, '08-assistant')

  const cite = page.locator('[data-citation-badge], .inline-citation-badge').first()
  if (await cite.count()) {
    await cite.click()
    await page.waitForTimeout(2000)
    await shot(page, '10-assistant-source')
  }

  await browser.close()
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
