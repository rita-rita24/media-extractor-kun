import { expect, test } from '@playwright/test'

test('completes the extraction flow after the API job finishes', async ({ page }) => {
  const extractRequests: unknown[] = []

  await page.route('**/api/extract', async (route) => {
    extractRequests.push(route.request().postDataJSON())
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        job_id: 'job-1',
        status: 'pending',
        progress: 0,
        message: '待機中...',
      }),
    })
  })

  await page.route('**/api/job/job-1', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        job_id: 'job-1',
        status: 'completed',
        progress: 100,
        message: '完了！',
        filename: 'clip.mp3',
      }),
    })
  })

  await page.goto('/')
  await page.getByLabel('メディアのURLを貼り付け').fill('https://youtu.be/abc_123')
  await page.getByLabel('ファイル名（任意）').fill('clip')
  await page.getByRole('button', { name: '抽出を開始' }).click()

  await expect(page.getByRole('heading', { name: '抽出が完了しました！' })).toBeVisible()
  await expect(page.getByText('clip.mp3')).toBeVisible()
  expect(extractRequests).toEqual([
    {
      url: 'https://youtu.be/abc_123',
      filename: 'clip',
      download_type: 'audio',
      video_quality: '1080p',
    },
  ])
})

test('shows an API error instead of leaving the user without feedback', async ({ page }) => {
  await page.route('**/api/extract', async (route) => {
    await route.fulfill({
      status: 500,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'サーバー内部で失敗しました' }),
    })
  })

  await page.goto('/')
  await page.getByLabel('メディアのURLを貼り付け').fill('https://youtu.be/abc_123')
  await page.getByRole('button', { name: '抽出を開始' }).click()

  await expect(page.getByRole('alert')).toContainText('サーバー内部で失敗しました')
})

test('rejects unsupported URLs before calling the API', async ({ page }) => {
  let extractCalled = false
  await page.route('**/api/extract', async (route) => {
    extractCalled = true
    await route.fulfill({ status: 500, body: '{}' })
  })

  await page.goto('/')
  await page.getByLabel('メディアのURLを貼り付け').fill('file:///tmp/private.mp3')
  await page.getByRole('button', { name: '抽出を開始' }).click()

  await expect(page.getByRole('alert')).toContainText('対応していないURLです')
  expect(extractCalled).toBe(false)
})

test('does not claim that URLs are never sent outside the device', async ({ page }) => {
  await page.goto('/')

  await expect(page.getByText('外部に送信されません')).toHaveCount(0)
  await expect(page.getByText('必要な外部取得先へ接続します')).toBeVisible()
})

test('accepts supported social platform URLs for both audio and video requests', async ({ page }) => {
  const matrix = [
    ['youtube', 'https://www.youtube.com/watch?v=jNQXAC9IVRw'],
    ['tiktok', 'https://www.tiktok.com/@patroxofficial/video/6742501081818877190?langCountry=en'],
    ['instagram', 'https://www.instagram.com/reel/CDUMkliABpa/'],
    ['x', 'https://x.com/historyinmemes/status/1790637656616943991'],
    ['twitter', 'https://twitter.com/historyinmemes/status/1790637656616943991'],
  ] as const
  const requestBodies: unknown[] = []

  await page.route('**/api/extract', async (route) => {
    requestBodies.push(route.request().postDataJSON())
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        job_id: `matrix-${requestBodies.length}`,
        status: 'pending',
        progress: 0,
        message: '待機中...',
      }),
    })
  })

  await page.route('**/api/job/matrix-*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        job_id: 'matrix',
        status: 'completed',
        progress: 100,
        message: '完了！',
        filename: 'matrix.mp3',
      }),
    })
  })

  for (const [, url] of matrix) {
    for (const downloadType of ['audio', 'video'] as const) {
      await page.goto('/')
      await page.getByLabel('メディアのURLを貼り付け').fill(url)
      if (downloadType === 'video') {
        await page.getByLabel('動画').check()
      }
      const previousCount = requestBodies.length
      await page.getByRole('button', { name: '抽出を開始' }).click()
      await expect.poll(() => requestBodies.length).toBe(previousCount + 1)
      expect(requestBodies[requestBodies.length - 1]).toMatchObject({
        url,
        download_type: downloadType,
      })
    }
  }
})

test('can reset from the completed view and deletes the server job', async ({ page }) => {
  let deleteCalled = false

  await page.route('**/api/extract', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ job_id: 'job-reset', status: 'pending', progress: 0, message: '待機中...' }),
    })
  })
  await page.route('**/api/job/job-reset', async (route) => {
    if (route.request().method() === 'DELETE') {
      deleteCalled = true
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) })
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        job_id: 'job-reset',
        status: 'completed',
        progress: 100,
        message: '完了！',
        filename: 'reset.mp3',
      }),
    })
  })

  await page.goto('/')
  await page.getByLabel('メディアのURLを貼り付け').fill('https://youtu.be/abc_123')
  await page.getByRole('button', { name: '抽出を開始' }).click()
  await expect(page.getByRole('heading', { name: '抽出が完了しました！' })).toBeVisible()

  await page.getByRole('button', { name: '閉じる' }).click()

  await expect(page.getByLabel('メディアのURLを貼り付け')).toBeVisible()
  expect(deleteCalled).toBe(true)
})
