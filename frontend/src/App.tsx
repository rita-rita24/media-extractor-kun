import { forwardRef, useEffect, useMemo, useRef, useState } from 'react'
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
  const [isModalOpen, setIsModalOpen] = useState(visualMode === 'complete')
  const [jobId, setJobId] = useState<string | null>(null)
  const [progress, setProgress] = useState(0)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [filename, setFilename] = useState<string | null>(
    visualMode === 'complete' ? DEFAULT_COMPLETE_FILENAME : null,
  )
  const pollingRef = useRef<number | null>(null)
  const modalRef = useRef<HTMLDivElement | null>(null)

  const selectedFormat = useMemo(() => getFileFormat(downloadType, filename || ''), [downloadType, filename])

  const stopPolling = () => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current)
      pollingRef.current = null
    }
  }

  useEffect(() => {
    if (!isModalOpen) return

    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    modalRef.current?.focus()

    return () => {
      document.body.style.overflow = previousOverflow
    }
  }, [isModalOpen])

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

    setIsModalOpen(true)
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
    setIsModalOpen(false)
    setJobId(null)
    setProgress(0)
    setMessage('')
    setError('')
    setFilename(null)
    setUrl('')
    setCustomFilename('')
    setDownloadType('audio')
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
          disabled={!url.trim() || status === 'processing' || isModalOpen}
          onClick={handleExtract}
        >
          <span className="material-symbols-outlined" aria-hidden="true">download</span>
          {status === 'processing' ? '抽出しています' : '抽出を開始'}
        </button>

        {error && !isModalOpen && (
          <p className="error-message" role="alert">{error}</p>
        )}

        <p className="privacy-note">
          <span className="material-symbols-outlined" aria-hidden="true">lock</span>
          入力URLの解析と取得はこの端末上のAPIで実行され、必要な外部取得先へ接続します。
        </p>
      </section>

      <section className="trust-row" aria-label="サービスの特徴">
        <FeatureCard icon="save" title="ローカル保存">
          変換結果はこの端末に保存。<br />処理後の一時ファイルは削除できます。
        </FeatureCard>
        <FeatureCard icon="history_toggle_off" title="履歴なし">
          URLやファイルは保存されません。<br />使い終わったらすぐに消えます。
        </FeatureCard>
        <FeatureCard icon="open_in_browser" title="インストール不要">
          ブラウザだけで使えます。<br />いつでも、どこでも利用可能。
        </FeatureCard>
      </section>

      {isModalOpen && (
        <ExtractModal
          ref={modalRef}
          status={status}
          progress={progress}
          message={message}
          error={error}
          filename={filename}
          format={selectedFormat}
          canDownload={Boolean(jobId && filename)}
          onDownload={handleDownload}
          onClose={handleReset}
        />
      )}
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
      <span className="feature-icon-shell" aria-hidden="true">
        <span className="material-symbols-outlined feature-icon">{icon}</span>
      </span>
      <div>
        <h3>{title}</h3>
        <p>{children}</p>
      </div>
    </article>
  )
}

type ExtractModalProps = {
  status: Status
  progress: number
  message: string
  error: string
  filename: string | null
  format: 'MP3' | 'MP4'
  canDownload: boolean
  onDownload: () => void
  onClose: () => void
}

const getModalIcon = (status: Status) => {
  if (status === 'completed') return 'check'
  if (status === 'error') return 'error'
  return 'downloading'
}

const getModalTitle = (status: Status) => {
  if (status === 'completed') return '抽出が完了しました！'
  if (status === 'error') return '抽出に失敗しました'
  return '抽出しています'
}

const progressSteps = ['URL確認', 'ダウンロード', '変換', '完了']

function getStepClassName(index: number, status: Status, progress: number) {
  if (status === 'completed') return 'is-complete'
  if (status === 'error') return index === 0 ? 'is-complete' : ''

  const activeIndex = progress >= 75 ? 2 : progress >= 10 ? 1 : 0
  if (index < activeIndex) return 'is-complete'
  if (index === activeIndex) return 'is-active'
  return ''
}

const ExtractModal = forwardRef<HTMLDivElement, ExtractModalProps>(function ExtractModal(
  { status, progress, message, error, filename, format, canDownload, onDownload, onClose },
  ref,
) {
  const title = getModalTitle(status)
  const modalProgress = status === 'completed' ? 100 : progress

  return (
    <div className="modal-backdrop" role="presentation">
      <section
        ref={ref}
        className={`extract-modal extract-modal-${status}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby="extract-modal-title"
        tabIndex={-1}
      >
        <div className="modal-heading">
          <span className="modal-status-mark" aria-hidden="true">
            <span className="material-symbols-outlined">{getModalIcon(status)}</span>
          </span>
          <div>
            <p className="modal-kicker">{format}として保存</p>
            <h2 id="extract-modal-title">{title}</h2>
          </div>
        </div>

        <div className="modal-progress" role="status" aria-live="polite">
          <div className="progress-copy">
            <span>{status === 'completed' ? 'ファイルの準備ができました。' : message || '処理を開始しています'}</span>
            <strong>{modalProgress.toFixed(0)}%</strong>
          </div>
          <div className="progress-track" aria-hidden="true">
            <div className="progress-fill" style={{ width: `${modalProgress}%` }}></div>
          </div>
        </div>

        <ol className="modal-stepper" aria-label="処理状況">
          {progressSteps.map((label, index) => (
            <li key={label} className={getStepClassName(index, status, modalProgress)}>
              <span className="step-check" aria-hidden="true">
                <span className="material-symbols-outlined">
                  {getStepClassName(index, status, modalProgress) === 'is-complete' ? 'check' : 'fiber_manual_record'}
                </span>
              </span>
              <span>{label}</span>
            </li>
          ))}
        </ol>

        {status === 'completed' && filename && (
          <div className="modal-file-summary" aria-label="ファイル情報">
            <span className="modal-file-icon" aria-hidden="true">
              <span className="material-symbols-outlined">{format === 'MP4' ? 'movie' : 'music_note'}</span>
            </span>
            <dl>
              <div>
                <dt>ファイル名</dt>
                <dd>{filename}</dd>
              </div>
              <div>
                <dt>形式</dt>
                <dd>{format}</dd>
              </div>
            </dl>
          </div>
        )}

        {status === 'error' && (
          <p className="modal-error" role="alert">
            {error || '処理に失敗しました'}
          </p>
        )}

        <div className="modal-actions">
          {status === 'completed' && (
            <button
              type="button"
              className="download-button"
              disabled={!canDownload}
              onClick={onDownload}
            >
              <span className="material-symbols-outlined" aria-hidden="true">download</span>
              ダウンロード
            </button>
          )}

          {status !== 'processing' && (
            <button type="button" className="close-button" onClick={onClose}>閉じる</button>
          )}
        </div>
      </section>
    </div>
  )
})

export default App
