import { useEffect, useMemo, useRef, useState } from 'react'
import './App.css'

type Status = 'idle' | 'processing' | 'completed' | 'error'
type DownloadType = 'audio' | 'video'

interface JobResponse {
  job_id: string
  status: 'pending' | 'downloading' | 'converting' | 'completed' | 'failed'
  progress: number
  message: string
  filename?: string
  error?: string
}

interface ApiErrorBody {
  detail?: string
  error?: string
  message?: string
}

const visualMode = new URLSearchParams(window.location.search).get('view')
const DEFAULT_COMPLETE_FILENAME = '会議録音_20240520.mp3'
const MEDIA_EXTENSIONS = ['.mp3', '.mp4', '.wav', '.m4a', '.webm', '.ogg', '.aac', '.flac']

const getApiErrorMessage = (data: unknown, fallbackMessage: string): string => {
  if (data && typeof data === 'object') {
    const errorBody = data as ApiErrorBody
    return errorBody.detail || errorBody.error || errorBody.message || fallbackMessage
  }
  return fallbackMessage
}

const parseJsonResponse = async <T,>(response: Response, fallbackMessage: string): Promise<T> => {
  const text = await response.text()
  let data: unknown = null

  if (text.trim()) {
    try {
      data = JSON.parse(text)
    } catch {
      throw new Error(`${fallbackMessage}（サーバーからJSON以外の応答が返りました: HTTP ${response.status}）`)
    }
  }

  if (!response.ok) {
    throw new Error(getApiErrorMessage(data, `${fallbackMessage}（HTTP ${response.status}）`))
  }

  if (data === null) {
    throw new Error(`${fallbackMessage}（サーバーから空の応答が返りました）`)
  }

  return data as T
}

const isDirectMediaUrl = (value: string): boolean => {
  try {
    const parsedUrl = new URL(value.trim())
    if (!['http:', 'https:'].includes(parsedUrl.protocol)) {
      return false
    }

    const hostname = parsedUrl.hostname.replace(/^\[|\]$/g, '').toLowerCase()
    if (
      !hostname.includes('.') ||
      hostname === 'localhost' ||
      hostname.endsWith('.localhost') ||
      hostname.endsWith('.local') ||
      hostname === '0.0.0.0' ||
      hostname === '::1' ||
      hostname.startsWith('127.') ||
      hostname.startsWith('10.') ||
      hostname.startsWith('169.254.') ||
      /^192\.168\./.test(hostname) ||
      /^172\.(1[6-9]|2\d|3[0-1])\./.test(hostname)
    ) {
      return false
    }

    const path = parsedUrl.pathname.toLowerCase()
    return MEDIA_EXTENSIONS.some((extension) => path.endsWith(extension))
  } catch {
    return false
  }
}

const isSupportedYoutubeUrl = (value: string): boolean => {
  try {
    const parsedUrl = new URL(value.trim())
    const hostname = parsedUrl.hostname.toLowerCase()
    const path = parsedUrl.pathname.replace(/\/+$/, '') || '/'

    if (!['http:', 'https:'].includes(parsedUrl.protocol)) {
      return false
    }

    if (['youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com'].includes(hostname)) {
      if (path === '/watch') {
        const videoId = parsedUrl.searchParams.get('v')
        return !!videoId && /^[\w-]+$/.test(videoId)
      }
      return /^\/shorts\/[\w-]+$/.test(path)
    }

    if (['youtu.be', 'www.youtu.be'].includes(hostname)) {
      return /^\/[\w-]+$/.test(path)
    }

    return false
  } catch {
    return false
  }
}

const isValidUrl = (value: string): boolean => {
  if (isDirectMediaUrl(value) || isSupportedYoutubeUrl(value)) {
    return true
  }

  const patterns = [
    /^https?:\/\/(www\.|vm\.|vt\.)?tiktok\.com\/.+/,
    /^https?:\/\/(www\.)?instagram\.com\/(p|reel|reels|tv)\/.+/,
    /^https?:\/\/(www\.)?(twitter|x)\.com\/.+\/status\/.+/,
  ]

  return patterns.some((pattern) => pattern.test(value.trim()))
}

const getFileFormat = (downloadType: DownloadType, fileName: string): 'MP3' | 'MP4' => {
  if (fileName.toLowerCase().endsWith('.mp4') || downloadType === 'video') {
    return 'MP4'
  }
  return 'MP3'
}

function App() {
  const [url, setUrl] = useState('')
  const [customFilename, setCustomFilename] = useState('')
  const [downloadType, setDownloadType] = useState<DownloadType>('audio')
  const [status, setStatus] = useState<Status>(visualMode === 'complete' ? 'completed' : 'idle')
  const [jobId, setJobId] = useState<string | null>(null)
  const [progress, setProgress] = useState(0)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [filename, setFilename] = useState<string | null>(
    visualMode === 'complete' ? DEFAULT_COMPLETE_FILENAME : null,
  )
  const pollingRef = useRef<number | null>(null)

  const selectedFormat = useMemo(() => getFileFormat(downloadType, filename || ''), [downloadType, filename])

  const stopPolling = () => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current)
      pollingRef.current = null
    }
  }

  useEffect(() => {
    if (!jobId || status !== 'processing') return

    const pollStatus = async () => {
      try {
        const response = await fetch(`/api/job/${jobId}`)
        const data = await parseJsonResponse<JobResponse>(response, 'ステータス取得に失敗')
        setProgress(data.progress)
        setMessage(data.message)

        if (data.status === 'completed' && data.filename) {
          setStatus('completed')
          setFilename(data.filename)
          stopPolling()
        } else if (data.status === 'failed') {
          setStatus('error')
          setError(data.error || '処理に失敗しました')
          stopPolling()
        }
      } catch (err) {
        console.error('Polling error:', err)
      }
    }

    pollingRef.current = window.setInterval(pollStatus, 1000)
    pollStatus()

    return () => stopPolling()
  }, [jobId, status])

  const handleExtract = async () => {
    if (!url.trim() || !isValidUrl(url)) {
      setError('対応していないURLです。YouTube, TikTok, Instagram, X または直接MP3/MP4のURLを入力してください')
      return
    }

    setStatus('processing')
    setProgress(0)
    setMessage('ジョブを開始中...')
    setError('')
    setFilename(null)

    try {
      const response = await fetch('/api/extract', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: url.trim(),
          filename: customFilename.trim() || null,
          download_type: downloadType,
          video_quality: '1080p',
        }),
      })

      const data = await parseJsonResponse<JobResponse>(response, '抽出の開始に失敗しました')
      setJobId(data.job_id)
      setMessage(data.message)
    } catch (err) {
      setStatus('error')
      setError(err instanceof Error ? err.message : '予期せぬエラーが発生しました')
    }
  }

  const handleDownload = () => {
    if (!jobId || !filename) return

    const downloadUrl = `/api/download/${jobId}/${encodeURIComponent(filename)}`
    const link = document.createElement('a')
    link.href = downloadUrl
    link.download = filename
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }

  const handleReset = () => {
    if (jobId) {
      fetch(`/api/job/${jobId}`, { method: 'DELETE' }).catch(() => undefined)
    }
    stopPolling()
    setStatus('idle')
    setJobId(null)
    setProgress(0)
    setMessage('')
    setError('')
    setFilename(null)
    setUrl('')
    setCustomFilename('')
    setDownloadType('audio')
  }

  if (status === 'completed' && filename) {
    return (
      <CompleteView
        filename={filename}
        format={selectedFormat}
        onDownload={handleDownload}
        onReset={handleReset}
      />
    )
  }

  return (
    <main className="home-screen">
      <header className="site-header" aria-label="サイトヘッダー">
        <div className="header-inner">
          <a className="brand-link" href="/" aria-label="メディア抽出くん ホーム">
            <img className="brand-mark" src="/assets/brand-sprout.png" alt="" />
            <span className="brand-copy">
              <span className="brand-name">メディア抽出くん</span>
              <span className="brand-subtitle">動画や音声を、かんたんにローカル保存</span>
            </span>
          </a>
          <nav className="header-nav" aria-label="メインナビゲーション">
            <a href="#usage" className="nav-link">
              <span className="material-symbols-outlined" aria-hidden="true">menu_book</span>
              使い方
            </a>
            <a href="#faq" className="nav-link">
              <span className="material-symbols-outlined" aria-hidden="true">help</span>
              よくある質問
            </a>
          </nav>
        </div>
      </header>

      <section className="extract-card" aria-labelledby="extract-title">
        <h1 id="extract-title" className="sr-only">メディアのURLからMP3またはMP4を抽出</h1>

        <div className="field-group">
          <label htmlFor="media-url">メディアのURLを貼り付け</label>
          <div className="input-shell">
            <span className="material-symbols-outlined input-icon" aria-hidden="true">link</span>
            <input
              id="media-url"
              type="url"
              inputMode="url"
              value={url}
              placeholder="https://www.example.com/watch?v=xxxxxxx"
              onChange={(event) => {
                setUrl(event.target.value)
                setError('')
              }}
            />
          </div>
          <p className="helper-text">対応サービスのURLを貼り付けてください</p>
        </div>

        <div className="field-group filename-group">
          <label htmlFor="file-name">ファイル名（任意）</label>
          <input
            id="file-name"
            className="plain-input"
            type="text"
            value={customFilename}
            placeholder="例）会議録音_20240520"
            onChange={(event) => setCustomFilename(event.target.value)}
          />
          <p className="helper-text">未指定の場合は、自動で名前を付けます</p>
        </div>

        <fieldset className="format-fieldset">
          <legend>保存する形式を選択</legend>
          <div className="format-options">
            <label className={`format-option ${downloadType === 'audio' ? 'is-selected' : ''}`}>
              <input
                type="radio"
                name="format"
                value="audio"
                checked={downloadType === 'audio'}
                onChange={() => setDownloadType('audio')}
              />
              <span className="radio-dot" aria-hidden="true"></span>
              <span className="material-symbols-outlined format-icon" aria-hidden="true">music_note</span>
              <span className="format-copy">
                <strong>音声のみ</strong>
                <span>MP3</span>
              </span>
            </label>
            <label className={`format-option ${downloadType === 'video' ? 'is-selected' : ''}`}>
              <input
                type="radio"
                name="format"
                value="video"
                checked={downloadType === 'video'}
                onChange={() => setDownloadType('video')}
              />
              <span className="radio-dot" aria-hidden="true"></span>
              <span className="material-symbols-outlined format-icon" aria-hidden="true">videocam</span>
              <span className="format-copy">
                <strong>動画</strong>
                <span>MP4</span>
              </span>
            </label>
          </div>
        </fieldset>

        <button
          type="button"
          className="primary-button"
          disabled={!url.trim() || status === 'processing'}
          onClick={handleExtract}
        >
          <span className="material-symbols-outlined" aria-hidden="true">download</span>
          {status === 'processing' ? '抽出しています' : '抽出を開始'}
        </button>

        {status === 'processing' && (
          <div className="progress-area" role="status" aria-live="polite">
            <span>{message || '処理を開始しています'}</span>
            <span>{progress.toFixed(0)}%</span>
            <div className="progress-track" aria-hidden="true">
              <div className="progress-fill" style={{ width: `${progress}%` }}></div>
            </div>
          </div>
        )}

        {(error || status === 'error') && status !== 'processing' && (
          <p className="error-message" role="alert">{error}</p>
        )}

        <p className="privacy-note">
          <span className="material-symbols-outlined" aria-hidden="true">lock</span>
          入力URLの解析と取得はこの端末上のAPIで実行され、必要な外部取得先へ接続します。
        </p>
      </section>

      <section className="trust-row" aria-label="サービスの特徴">
        <FeatureCard icon="shield_lock" title="ローカル保存">
          変換結果はこの端末に保存。<br />処理後の一時ファイルは削除できます。
        </FeatureCard>
        <FeatureCard icon="history" title="履歴なし">
          URLやファイルは保存されません。<br />使い終わったらすぐに消えます。
        </FeatureCard>
        <FeatureCard icon="eco" title="インストール不要">
          ブラウザだけで使えます。<br />いつでも、どこでも利用可能。
        </FeatureCard>
      </section>

      <section id="usage" className="capability-card" aria-labelledby="capability-title">
        <div className="capability-heading">
          <img src="/assets/brand-sprout.png" alt="" />
          <h2 id="capability-title">できること</h2>
        </div>
        <div className="capability-grid">
          <CapabilityItem title="YouTube / TikTok / Instagram / X などに対応">
            対応サービスの動画・音声URLを貼り付けるだけ
          </CapabilityItem>
          <CapabilityItem title="高品質のまま、すばやく抽出">
            シンプル設計で迷わず使えます
          </CapabilityItem>
          <CapabilityItem title="音声も動画も、かんたん保存">
            MP3 / MP4 に対応
          </CapabilityItem>
          <CapabilityItem title="メディアファイルにも対応">
            .mp3 / .mp4 などの直接URLもOK
          </CapabilityItem>
        </div>
        <img className="plant-illustration" src="/assets/feature-plant.png" alt="" />
      </section>
    </main>
  )
}

interface FeatureCardProps {
  icon: string
  title: string
  children: React.ReactNode
}

function FeatureCard({ icon, title, children }: FeatureCardProps) {
  return (
    <article className="feature-card">
      <span className="feature-glow" aria-hidden="true"></span>
      <span className="material-symbols-outlined feature-icon" aria-hidden="true">{icon}</span>
      <div>
        <h3>{title}</h3>
        <p>{children}</p>
      </div>
    </article>
  )
}

interface CapabilityItemProps {
  title: string
  children: React.ReactNode
}

function CapabilityItem({ title, children }: CapabilityItemProps) {
  return (
    <div className="capability-item">
      <span className="mini-check" aria-hidden="true"></span>
      <div>
        <h3>{title}</h3>
        <p>{children}</p>
      </div>
    </div>
  )
}

interface CompleteViewProps {
  filename: string
  format: 'MP3' | 'MP4'
  onDownload: () => void
  onReset: () => void
}

function CompleteView({ filename, format, onDownload, onReset }: CompleteViewProps) {
  return (
    <main className="complete-screen">
      <section className="complete-card" aria-labelledby="complete-title">
        <div className="confetti" aria-hidden="true">
          <span className="piece piece-a"></span>
          <span className="piece piece-b"></span>
          <span className="piece piece-c"></span>
          <span className="piece piece-d"></span>
          <span className="piece piece-e"></span>
          <span className="piece piece-f"></span>
          <span className="piece piece-g"></span>
        </div>
        <div className="success-mark" aria-hidden="true">
          <span className="material-symbols-outlined">check</span>
        </div>
        <h1 id="complete-title">抽出が完了しました！</h1>
        <p className="complete-lead">ファイルの準備ができました。</p>

        <ol className="stepper" aria-label="処理状況">
          {['URL確認', 'ダウンロード', '変換', '完了'].map((label) => (
            <li key={label}>
              <span className="step-check" aria-hidden="true">
                <span className="material-symbols-outlined">check</span>
              </span>
              <span>{label}</span>
            </li>
          ))}
        </ol>

        <div className="file-summary" aria-label="ファイル情報">
          <div className="file-art" aria-hidden="true">
            <span className="material-symbols-outlined">music_note</span>
          </div>
          <dl>
            <div>
              <dt>
                <span className="material-symbols-outlined" aria-hidden="true">description</span>
                ファイル名
              </dt>
              <dd>{filename}</dd>
            </div>
            <div>
              <dt>
                <span className="material-symbols-outlined" aria-hidden="true">music_note</span>
                形式
              </dt>
              <dd>{format}</dd>
            </div>
            <div>
              <dt>
                <span className="material-symbols-outlined" aria-hidden="true">inbox</span>
                サイズ
              </dt>
              <dd>24.7 MB</dd>
            </div>
            <div>
              <dt>
                <span className="material-symbols-outlined" aria-hidden="true">folder</span>
                保存先
              </dt>
              <dd>ダウンロードフォルダ</dd>
            </div>
          </dl>
        </div>

        <button
          type="button"
          className="download-button"
          onClick={onDownload}
        >
          <span className="material-symbols-outlined" aria-hidden="true">download</span>
          ダウンロード
        </button>
        <button type="button" className="close-button" onClick={onReset}>閉じる</button>

        <div className="safe-notes">
          <p>
            <span className="material-symbols-outlined" aria-hidden="true">verified_user</span>
            正常に準備できました。
          </p>
          <p>
            <span className="material-symbols-outlined" aria-hidden="true">lock</span>
            ファイルはこの端末に保存されます
          </p>
        </div>
      </section>
    </main>
  )
}

export default App
