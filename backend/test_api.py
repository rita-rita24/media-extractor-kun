from yt_dlp import YoutubeDL

url = "https://www.tiktok.com/@_uyu.19/video/7595113974174174471"

ydl_opts = {
    'impersonate': 'chrome',
    'quiet': False,
    'verbose': True,
    'simulate': True,
    'dump_single_json': True,
}

try:
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        print("Success!")
        print(f"Title: {info.get('title')}")
except Exception as e:
    print(f"Error: {e}")
