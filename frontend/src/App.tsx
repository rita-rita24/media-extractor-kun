import { useRef, useState, type FormEvent, type ReactNode } from 'react'
import { ExtractModal } from './components/ExtractModal'
import { useExtraction } from './hooks/useExtraction'
import type { DownloadType } from './lib/api'
import { isValidUrl } from './lib/media'
import './App.css'

const FORMATS = [
  { value: 'audio', title: '音声のみ', format: 'MP3', icon: 'music_note' },
  { value: 'video', title: '動画', format: 'MP4', icon: 'videocam' },
] as const

function App() {
  const [url, setUrl] = useState('')
  const [customFilename, setCustomFilename] = useState('')
  const [downloadType, setDownloadType] = useState<DownloadType>('audio')
  const [error, setError] = useState('')
  const urlInputRef = useRef<HTMLInputElement>(null)
  const { extraction, start, reset } = useExtraction()

  const handleExtract = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!isValidUrl(url)) {
      setError('対応していないURLです。YouTube, TikTok, Instagram, X または直接メディアURLを入力してください')
      urlInputRef.current?.focus()
      return
    }
    setError('')
    void start(url, customFilename, downloadType)
  }

  const handleReset = () => {
    reset()
    setUrl('')
    setCustomFilename('')
    setDownloadType('audio')
    setError('')
    urlInputRef.current?.focus()
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

      <form className="extract-card" aria-labelledby="extract-title" onSubmit={handleExtract} noValidate>
        <h1 id="extract-title" className="sr-only">メディアのURLからMP3またはMP4を抽出</h1>

        <div className="field-group">
          <label htmlFor="media-url">メディアのURLを貼り付け</label>
          <div className="input-shell">
            <span className="material-symbols-outlined input-icon" aria-hidden="true">link</span>
            <input
              ref={urlInputRef}
              id="media-url"
              aria-describedby={error ? "url-help url-error" : "url-help"}
              aria-invalid={Boolean(error)}
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
          <p id="url-help" className="helper-text">対応サービスのURLを貼り付けてください</p>
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
            {FORMATS.map(({ value, title, format, icon }) => (
              <label key={value} className="format-option">
                <input
                  type="radio"
                  name="format"
                  value={value}
                  checked={downloadType === value}
                  onChange={() => setDownloadType(value)}
                />
                <span className="radio-dot" aria-hidden="true" />
                <span className="material-symbols-outlined format-icon" aria-hidden="true">{icon}</span>
                <span className="format-copy">
                  <strong>{title}</strong>
                  <span>{format}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>

        <button
          type="submit"
          className="primary-button"
          disabled={!url.trim() || Boolean(extraction)}
        >
          <span className="material-symbols-outlined" aria-hidden="true">download</span>
          {extraction?.status === 'processing' ? '抽出しています' : '抽出を開始'}
        </button>

        {error && (
          <p id="url-error" className="error-message" role="alert">{error}</p>
        )}

        <p className="privacy-note">
          <span className="material-symbols-outlined" aria-hidden="true">lock</span>
          入力URLの解析と取得はこの端末上のAPIで実行され、必要な外部取得先へ接続します。
        </p>
      </form>

      <section className="trust-row" aria-label="サービスの特徴">
        <FeatureCard icon="save" title="ローカル保存">
          変換結果はこの端末に保存。<br />処理後の一時ファイルは削除できます。
        </FeatureCard>
        <FeatureCard icon="history_toggle_off" title="履歴なし">
          ジョブ情報はメモリ上で管理。<br />閉じると一時ファイルを削除します。
        </FeatureCard>
        <FeatureCard icon="open_in_browser" title="ブラウザで操作">
          ローカルAPIの起動後は、<br />ブラウザからかんたんに操作。
        </FeatureCard>
      </section>

      {extraction && (
        <ExtractModal extraction={extraction} downloadType={downloadType} onClose={handleReset} />
      )}
    </main>
  )
}

interface FeatureCardProps {
  icon: string
  title: string
  children: ReactNode
}

function FeatureCard({ icon, title, children }: FeatureCardProps) {
  return (
    <article className="feature-card">
      <span className="feature-icon-shell" aria-hidden="true">
        <span className="material-symbols-outlined feature-icon">{icon}</span>
      </span>
      <div>
        <h2>{title}</h2>
        <p>{children}</p>
      </div>
    </article>
  )
}

export default App
