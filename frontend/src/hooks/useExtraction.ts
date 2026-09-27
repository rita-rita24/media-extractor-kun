import { useEffect, useRef, useState } from 'react'
import { getErrorMessage, requestJob, type DownloadType, type JobResponse } from '../lib/api'

export interface ExtractionState {
  status: 'processing' | 'completed' | 'error'
  jobId: string | null
  progress: number
  message: string
  filename: string | null
  error: string | null
}

const toState = (job: JobResponse): ExtractionState => ({
  status: job.status === 'completed' ? 'completed' : job.status === 'failed' ? 'error' : 'processing',
  jobId: job.job_id,
  progress: Math.max(0, Math.min(100, job.progress)),
  message: job.message,
  filename: job.filename ?? null,
  error: job.error ?? null,
})

export function useExtraction() {
  const [extraction, setExtraction] = useState<ExtractionState | null>(null)
  const startController = useRef<AbortController | null>(null)
  const jobId = extraction?.jobId
  const status = extraction?.status

  useEffect(() => () => startController.current?.abort(), [])

  useEffect(() => {
    if (!jobId || status !== 'processing') return

    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined

    const poll = async () => {
      try {
        const job = await requestJob(`/api/job/${encodeURIComponent(jobId)}`, 'ステータス取得に失敗しました', {
          signal: controller.signal,
        })
        if (controller.signal.aborted) return

        const nextState = toState(job)
        setExtraction(nextState)
        if (nextState.status === 'processing') timer = setTimeout(poll, 1000)
      } catch (error) {
        if (controller.signal.aborted) return
        setExtraction((current) => current && { ...current, status: 'error', error: getErrorMessage(error) })
      }
    }

    void poll()
    return () => {
      controller.abort()
      clearTimeout(timer)
    }
  }, [jobId, status])

  const start = async (url: string, filename: string, downloadType: DownloadType) => {
    if (extraction || startController.current) return

    const controller = new AbortController()
    startController.current = controller
    setExtraction({
      status: 'processing', jobId: null, progress: 0,
      message: 'ジョブを開始中...', filename: null, error: null,
    })

    try {
      const job = await requestJob('/api/extract', '抽出の開始に失敗しました', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: controller.signal,
        body: JSON.stringify({
          url: url.trim(), filename: filename.trim() || null,
          download_type: downloadType, video_quality: '1080p',
        }),
      })
      if (!controller.signal.aborted) setExtraction(toState(job))
    } catch (error) {
      if (!controller.signal.aborted) {
        setExtraction((current) => current && { ...current, status: 'error', error: getErrorMessage(error) })
      }
    } finally {
      if (startController.current === controller) startController.current = null
    }
  }

  const reset = () => {
    startController.current?.abort()
    startController.current = null
    if (jobId) {
      void fetch(`/api/job/${encodeURIComponent(jobId)}`, { method: 'DELETE' }).catch(() => undefined)
    }
    setExtraction(null)
  }

  return { extraction, start, reset }
}
