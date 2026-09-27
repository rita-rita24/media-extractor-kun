import { useEffect, useRef } from 'react'
import type { ExtractionState } from '../hooks/useExtraction'
import type { DownloadType } from '../lib/api'

const STATUS_CONTENT = {
  processing: { icon: 'downloading', title: '抽出しています' },
  completed: { icon: 'check', title: '抽出が完了しました！' },
  error: { icon: 'error', title: '抽出に失敗しました' },
}
const PROGRESS_STEPS = ['URL確認', 'ダウンロード', '変換', '完了']

interface ExtractModalProps {
  extraction: ExtractionState
  downloadType: DownloadType
  onClose: () => void
}

export function ExtractModal({ extraction, downloadType, onClose }: ExtractModalProps) {
  const { status, jobId, progress, message, error, filename } = extraction
  const dialogRef = useRef<HTMLDialogElement>(null)
  const { icon, title } = STATUS_CONTENT[status]
  const format = filename?.split('.').at(-1)?.toUpperCase() || (downloadType === 'video' ? 'MP4' : 'MP3')
  const modalProgress = status === 'completed' ? 100 : progress
  const activeStep = progress >= 75 ? 2 : progress >= 10 ? 1 : 0

  useEffect(() => {
    const dialog = dialogRef.current
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    dialog?.showModal()
    return () => {
      dialog?.close()
      document.body.style.overflow = previousOverflow
    }
  }, [])

  const close = () => {
    dialogRef.current?.close()
    onClose()
  }

  return (
    <dialog
      ref={dialogRef}
      className="extract-modal"
      data-status={status}
      aria-labelledby="extract-modal-title"
      onCancel={(event) => {
        event.preventDefault()
        if (status !== 'processing') close()
      }}
    >
      <div className="modal-heading">
        <span className="modal-status-mark" aria-hidden="true">
          <span className="material-symbols-outlined">{icon}</span>
        </span>
        <div>
          <p className="modal-kicker">{format}として保存</p>
          <h2 id="extract-modal-title">{title}</h2>
        </div>
      </div>

      <div className="modal-progress" role="status">
        <div className="progress-copy">
          <span>{status === 'completed' ? 'ファイルの準備ができました。' : message || '処理を開始しています'}</span>
          <strong>{modalProgress.toFixed(0)}%</strong>
        </div>
        <div className="progress-track" aria-hidden="true">
          <div className="progress-fill" style={{ width: `${modalProgress}%` }} />
        </div>
      </div>

      <ol className="modal-stepper" aria-label="処理状況">
        {PROGRESS_STEPS.map((label, index) => {
          const stepStatus = status === 'completed' || (status !== 'error' && index < activeStep)
            ? 'complete'
            : status === 'processing' && index === activeStep ? 'active' : undefined
          return (
            <li key={label} data-status={stepStatus} aria-current={stepStatus === 'active' ? 'step' : undefined}>
              <span className="step-check" aria-hidden="true">
                <span className="material-symbols-outlined">
                  {stepStatus === 'complete' ? 'check' : 'fiber_manual_record'}
                </span>
              </span>
              <span>{label}</span>
            </li>
          )
        })}
      </ol>

      {status === 'completed' && filename && (
        <div className="modal-file-summary" aria-label="ファイル情報">
          <span className="modal-file-icon" aria-hidden="true">
            <span className="material-symbols-outlined">{downloadType === 'video' ? 'movie' : 'music_note'}</span>
          </span>
          <dl>
            <div><dt>ファイル名</dt><dd>{filename}</dd></div>
            <div><dt>形式</dt><dd>{format}</dd></div>
          </dl>
        </div>
      )}

      {status === 'error' && <p className="modal-error" role="alert">{error || '処理に失敗しました'}</p>}

      {status !== 'processing' && (
        <div className="modal-actions">
          {status === 'completed' && jobId && filename && (
            <a
              className="download-button"
              href={`/api/download/${encodeURIComponent(jobId)}/${encodeURIComponent(filename)}`}
              download={filename}
            >
              <span className="material-symbols-outlined" aria-hidden="true">download</span>
              ダウンロード
            </a>
          )}
          <button type="button" className="close-button" onClick={close}>閉じる</button>
        </div>
      )}
    </dialog>
  )
}
