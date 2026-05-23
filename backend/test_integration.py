from main import extract_tiktok_url
import subprocess
import os

url = "https://vt.tiktok.com/ZSaPaWdvS/"

print(f"Testing extraction for {url}...")
extracted_url = extract_tiktok_url(url)
print(f"Extracted URL: {extracted_url}")

if extracted_url == url:
    print("Optimization: Extraction failed or returned same URL")
else:
    print("Optimization: Extraction successful!")

print("Running yt-dlp dry-run...")
cmd = [
    "yt-dlp",
    extracted_url,
    "--simulate",
    "--no-playlist"
]

result = subprocess.run(cmd, capture_output=True, text=True)

if result.returncode == 0:
    print("yt-dlp Success!")
    print(result.stderr[:500])
else:
    print("yt-dlp Failed!")
    print(result.stderr)
