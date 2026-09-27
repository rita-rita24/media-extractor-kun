const MEDIA_EXTENSIONS = ['.mp3', '.mp4', '.wav', '.m4a', '.webm', '.ogg', '.aac', '.flac']
const YOUTUBE_HOSTS = new Set(['youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com'])
const SOCIAL_PATHS: Record<string, RegExp> = {
  'tiktok.com': /^\/.+/,
  'vm.tiktok.com': /^\/.+/,
  'vt.tiktok.com': /^\/.+/,
  'instagram.com': /^\/(p|reel|reels|tv)\/.+/,
  'twitter.com': /^\/.+\/status\/.+/,
  'x.com': /^\/.+\/status\/.+/,
}

export function isValidUrl(value: string): boolean {
  try {
    const { protocol, hostname, pathname, searchParams } = new URL(value.trim())
    if (protocol !== 'http:' && protocol !== 'https:') return false

    const path = pathname.replace(/\/+$/, '')
    if (YOUTUBE_HOSTS.has(hostname) && (path === '/watch'
      ? /^[\w-]+$/.test(searchParams.get('v') ?? '')
      : /^\/shorts\/[\w-]+$/.test(path))) return true

    if ((hostname === 'youtu.be' || hostname === 'www.youtu.be') && /^\/[\w-]+$/.test(path)) return true
    if (SOCIAL_PATHS[hostname.replace(/^www\./, '')]?.test(pathname)) return true

    // DNS解決と最終的な取得先の検証はAPIで行う。
    const host = hostname.replace(/\.$/, '')
    if (
      !host.includes('.') ||
      host === 'localhost.localdomain' ||
      host.endsWith('.localhost') || host.endsWith('.local') ||
      /^(0|10|127)\./.test(host) || /^169\.254\./.test(host) ||
      /^192\.168\./.test(host) || /^172\.(1[6-9]|2\d|3[01])\./.test(host)
    ) return false

    return MEDIA_EXTENSIONS.some((extension) => pathname.toLowerCase().endsWith(extension))
  } catch {
    return false
  }
}
