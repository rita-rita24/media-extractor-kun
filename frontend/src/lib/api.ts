export type DownloadType = 'audio' | 'video'

export interface JobResponse {
  job_id: string
  status: 'pending' | 'downloading' | 'converting' | 'completed' | 'failed'
  progress: number
  message: string
  filename?: string | null
  error?: string | null
}

const getApiErrorMessage = (data: unknown, fallback: string): string => {
  if (data && typeof data === 'object') {
    for (const key of ['detail', 'error', 'message'] as const) {
      const value = (data as Record<string, unknown>)[key]
      if (typeof value === 'string' && value.trim()) return value
    }
  }
  return fallback
}

export async function requestJob(
  url: string,
  fallbackMessage: string,
  options: RequestInit = {},
): Promise<JobResponse> {
  const timeout = AbortSignal.timeout(30_000)
  const response = await fetch(url, {
    ...options,
    signal: options.signal ? AbortSignal.any([options.signal, timeout]) : timeout,
  })
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

  if (!data || typeof data !== 'object') {
    throw new Error(`${fallbackMessage}（サーバーから空または不正な応答が返りました）`)
  }

  const job = data as JobResponse
  if (
    typeof job.job_id !== 'string' || !job.job_id ||
    !['pending', 'downloading', 'converting', 'completed', 'failed'].includes(job.status) ||
    !Number.isFinite(job.progress) || typeof job.message !== 'string' ||
    (job.filename != null && typeof job.filename !== 'string') ||
    (job.error != null && typeof job.error !== 'string') ||
    (job.status === 'completed' && !job.filename)
  ) {
    throw new Error(`${fallbackMessage}（サーバーの応答形式が不正です）`)
  }

  return job
}

export const getErrorMessage = (error: unknown): string => {
  if (error instanceof Error) {
    return error.name === 'TimeoutError' ? 'サーバーの応答がタイムアウトしました' : error.message
  }
  return '予期せぬエラーが発生しました'
}
