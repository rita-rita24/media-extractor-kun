import { expect, test } from '@playwright/test'

test('completes the extraction flow after the API job finishes', async ({ page }) => {
  const extractRequests: unknown[] = []
  let jobPollCount = 0

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
    jobPollCount += 1
    const isComplete = jobPollCount > 1

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        job_id: 'job-1',
        status: isComplete ? 'completed' : 'downloading',
        progress: isComplete ? 100 : 40,
        message: isComplete ? '完了！' : 'ダウンロード中...',
        filename: isComplete ? 'clip.mp3' : undefined,
      }),
    })
  })

  await page.goto('/')
  await page.getByLabel('メディアのURLを貼り付け').fill('https://youtu.be/abc_123')
  await page.getByLabel('ファイル名（任意）').fill('clip')
  await page.getByRole('button', { name: '抽出を開始' }).click()

  await expect(page.getByRole('dialog', { name: '抽出しています' })).toBeVisible()
  await expect(page.getByRole('dialog')).toContainText('40%')
  await expect(page.locator('#media-url')).toBeVisible()
  await expect(page.getByRole('dialog', { name: '抽出が完了しました！' })).toBeVisible()
  await expect(page.getByRole('dialog')).toContainText('clip.mp3')
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

  await expect(page.getByRole('dialog', { name: '抽出に失敗しました' })).toBeVisible()
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
  await expect(page.getByRole('dialog')).toHaveCount(0)
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
    if (route.request().method() === 'DELETE') {
      await route.fulfill({ json: { success: true } })
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        job_id: route.request().url().split('/').at(-1),
        status: 'completed',
        progress: 100,
        message: '完了！',
        filename: 'matrix.mp3',
      }),
    })
  })

  await page.goto('/')

  for (const [, url] of matrix) {
    for (const downloadType of ['audio', 'video'] as const) {
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
      await expect(page.getByRole('dialog', { name: '抽出が完了しました！' })).toBeVisible()
      await page.getByRole('button', { name: '閉じる' }).click()
      await expect(page.getByRole('dialog')).toHaveCount(0)
    }
  }
})

test('can close the completed modal and deletes the server job', async ({ page }) => {
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

test('submits with Enter, prevents background focus, and restores the form on Escape', async ({ page }) => {
  await page.route('**/api/extract', (route) => route.fulfill({ json: {
    job_id: 'keyboard', status: 'completed', progress: 100,
    message: '完了！', filename: '会議 録音.wav',
  } }))
  await page.route('**/api/job/keyboard', (route) => route.fulfill({ json: { success: true } }))
  await page.goto('/')
  await page.getByLabel('メディアのURLを貼り付け').fill('https://cdn.example.com/audio.wav')
  await page.getByLabel('メディアのURLを貼り付け').press('Enter')

  const dialog = page.getByRole('dialog', { name: '抽出が完了しました！' })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByText('WAV', { exact: true })).toBeVisible()
  await expect(dialog.getByRole('link', { name: 'ダウンロード' })).toHaveAttribute(
    'href', `/api/download/keyboard/${encodeURIComponent('会議 録音.wav')}`,
  )
  await dialog.getByRole('link', { name: 'ダウンロード' }).focus()
  await page.keyboard.press('Tab')
  await expect(dialog.getByRole('button', { name: '閉じる' })).toBeFocused()
  for (let index = 0; index < 4; index += 1) {
    await page.keyboard.press('Tab')
    await expect(page.locator('.brand-link:focus, .extract-card :focus')).toHaveCount(0)
  }

  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(page.getByLabel('メディアのURLを貼り付け')).toBeFocused()
  await expect(page.getByLabel('メディアのURLを貼り付け')).toHaveValue('')
})

test('waits for a slow status response before polling again and ignores Escape while processing', async ({ page }) => {
  await page.clock.install()
  let polls = 0
  let finishPoll!: () => void
  const pendingPoll = new Promise<void>((resolve) => { finishPoll = resolve })
  await page.route('**/api/extract', (route) => route.fulfill({ json: {
    job_id: 'slow', status: 'pending', progress: 0, message: '待機中...',
  } }))
  await page.route('**/api/job/slow', async (route) => {
    polls += 1
    await pendingPoll
    await route.fulfill({ json: {
      job_id: 'slow', status: 'completed', progress: 100, message: '完了！', filename: 'slow.mp3',
    } })
  })
  await page.goto('/')
  await page.getByLabel('メディアのURLを貼り付け').fill('https://youtu.be/abc_123')
  await page.getByRole('button', { name: '抽出を開始' }).click()
  await expect.poll(() => polls).toBe(1)
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog', { name: '抽出しています' })).toBeVisible()
  await page.clock.fastForward(3500)
  expect(polls).toBe(1)
  finishPoll()
  await expect(page.getByRole('dialog', { name: '抽出が完了しました！' })).toBeVisible()
  await page.clock.fastForward(3500)
  expect(polls).toBe(1)
})

test('shows polling errors and lets the user return to the form', async ({ page }) => {
  await page.route('**/api/extract', (route) => route.fulfill({ json: {
    job_id: 'missing', status: 'pending', progress: 0, message: '待機中...',
  } }))
  await page.route('**/api/job/missing', (route) => route.fulfill({
    status: 404, json: { detail: 'ジョブが見つかりません' },
  }))
  await page.goto('/')
  await page.getByLabel('メディアのURLを貼り付け').fill('https://youtu.be/abc_123')
  await page.getByRole('button', { name: '抽出を開始' }).click()
  await expect(page.getByRole('alert')).toHaveText('ジョブが見つかりません')
  await page.getByRole('button', { name: '閉じる' }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

for (const [name, response, error] of [
  ['HTML', { status: 502, contentType: 'text/html', body: '<h1>Bad Gateway</h1>' }, 'JSON以外の応答'],
  ['empty', { status: 200, body: '' }, '空または不正な応答'],
  ['invalid job', { status: 200, json: { status: 'completed', progress: 100 } }, '応答形式が不正'],
  ['structured error', { status: 422, json: { detail: [{ msg: 'invalid' }] } }, 'HTTP 422'],
] as const) {
  test(`handles ${name} API responses without getting stuck`, async ({ page }) => {
    await page.route('**/api/extract', (route) => route.fulfill(response))
    await page.goto('/')
    await page.getByLabel('メディアのURLを貼り付け').fill('https://youtu.be/abc_123')
    await page.getByRole('button', { name: '抽出を開始' }).click()
    await expect(page.getByRole('alert')).toContainText(error)
    await expect(page.getByRole('button', { name: '閉じる' })).toBeVisible()
  })
}

test('keeps the form and long filenames within the viewport', async ({ page }, testInfo) => {
  await page.route('**/api/extract', (route) => route.fulfill({ json: {
    job_id: 'layout', status: 'completed', progress: 100,
    message: '完了！', filename: `${'非常に長いファイル名'.repeat(15)}.mp4`,
  } }))
  await page.goto('/')
  await expect(page.locator('.format-option').first()).toHaveCSS('border-color', 'rgb(77, 127, 71)')
  await page.getByLabel('動画').check()
  await expect(page.locator('.format-option').last()).toHaveCSS('border-color', 'rgb(77, 127, 71)')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('form.png'), fullPage: true })
  await page.getByLabel('メディアのURLを貼り付け').fill('https://youtu.be/abc_123')
  await page.getByRole('button', { name: '抽出を開始' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  if (testInfo.project.name === 'mobile-chrome') {
    expect(await page.locator('.modal-stepper').evaluate((element) => getComputedStyle(element, '::before').display)).toBe('none')
  }
  expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('completed.png'), fullPage: true })
})
