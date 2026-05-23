from curl_cffi import requests
import subprocess
import os

url = "https://vt.tiktok.com/ZSaPaWdvS/"

print(f"Resolving redirects for {url}...")
try:
    r = requests.get(
        url,
        allow_redirects=True,
        impersonate="chrome",
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
    )
    target_url = r.url
    print(f"Resolved URL: {target_url}")
except Exception as e:
    print(f"Error resolving redirects: {e}")
    exit(1)

print("Running yt-dlp with impersonate...")
cmd = [
    "./venv/bin/yt-dlp",
    target_url,
    "--impersonate", "safari",
    "--simulate",
    "--dump-json"
]

result = subprocess.run(cmd, capture_output=True, text=True)

if result.returncode == 0:
    print("Success!")
    print(result.stdout[:500])  # JSONの先頭だけ表示
else:
    print("Failed!")
    print(result.stderr)
