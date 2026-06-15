import sys
import urllib.request
import traceback
import requests
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import GenericProxyConfig

video_id = "kD7l9fqIdDk"

class TimeoutHTTPAdapter(requests.adapters.HTTPAdapter):
    def __init__(self, timeout=4, *args, **kwargs):
        self.timeout = timeout
        super().__init__(*args, **kwargs)
    def send(self, request, **kwargs):
        kwargs['timeout'] = self.timeout
        return super().send(request, **kwargs)

def get_proxies():
    print("Fetching free proxy list...", flush=True)
    urls = [
        "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=3000&country=all&ssl=all&anonymity=all",
        "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/http.txt",
        "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt"
    ]
    proxies = []
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                content = response.read().decode('utf-8')
                for line in content.split('\n'):
                    line = line.strip()
                    if line and ':' in line:
                        parts = line.split(':')
                        if len(parts) >= 2 and parts[0].replace('.', '').isdigit() and parts[1].isdigit():
                            proxies.append(line)
        except Exception as e:
            print(f"Error fetching from {url}: {e}", flush=True)
    proxies = list(set(proxies))
    print(f"Found {len(proxies)} unique proxies.", flush=True)
    return proxies

def try_fetch_with_proxies(proxies):
    session = requests.Session()
    adapter = TimeoutHTTPAdapter(timeout=4)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    for i, proxy in enumerate(proxies[:300]): # Try up to 300 proxies
        print(f"[{i+1}/{len(proxies)}] Trying proxy: {proxy}", flush=True)
        try:
            proxy_config = GenericProxyConfig(
                http_url=f"http://{proxy}",
                https_url=f"http://{proxy}"
            )
            api = YouTubeTranscriptApi(proxy_config=proxy_config, http_client=session)
            transcript = api.fetch(video_id)
            print("SUCCESS!", flush=True)
            return transcript
        except Exception as e:
            err_str = str(e)
            if "IpBlocked" in err_str or "RequestBlocked" in err_str:
                print("  Blocked by YouTube.", flush=True)
            elif "NoTranscriptFound" in err_str:
                print("  No transcript found for video.", flush=True)
                raise e
            else:
                msg = err_str[:50].replace('\n', ' ')
                print(f"  Failed: {type(e).__name__} - {msg}", flush=True)
    return None

def main():
    proxies = get_proxies()
    if not proxies:
        print("No proxies found. Exiting.", flush=True)
        sys.exit(1)
        
    try:
        transcript = try_fetch_with_proxies(proxies)
        if transcript:
            with open(f"scratch/raw_transcript_{video_id}.txt", "w", encoding="utf-8") as f:
                for entry in transcript:
                    start = entry['start']
                    duration = entry['duration']
                    text = entry['text'].replace('\n', ' ')
                    f.write(f"[{start:.2f} + {duration:.2f}] {text}\n")
            print(f"Saved transcript to scratch/raw_transcript_{video_id}.txt", flush=True)
        else:
            print("Could not fetch transcript with any of the tried proxies.", flush=True)
            sys.exit(1)
    except Exception as e:
        print(f"Terminated with error: {e}", flush=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
