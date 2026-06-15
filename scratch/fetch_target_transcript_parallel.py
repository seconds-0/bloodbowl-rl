import sys
import os
import socket
import urllib.request
import traceback
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import GenericProxyConfig

# Set global socket timeout to prevent any thread from hanging indefinitely
socket.setdefaulttimeout(3)

video_id = "5U_m3E7HJ38"

class TimeoutHTTPAdapter(requests.adapters.HTTPAdapter):
    def __init__(self, timeout=3, *args, **kwargs):
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
            with urllib.request.urlopen(req, timeout=5) as response:
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

def test_proxy(proxy, index):
    session = requests.Session()
    adapter = TimeoutHTTPAdapter(timeout=3)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    proxy_config = GenericProxyConfig(
        http_url=f"http://{proxy}",
        https_url=f"http://{proxy}"
    )
    api = YouTubeTranscriptApi(proxy_config=proxy_config, http_client=session)
    try:
        transcript = api.fetch(video_id)
        return proxy, transcript
    except Exception as e:
        err_str = str(e)
        if "NoTranscriptFound" in err_str:
            raise e
        return proxy, None

def try_fetch_with_proxies_parallel(proxies):
    print("Starting parallel proxy check...", flush=True)
    executor = ThreadPoolExecutor(max_workers=50)
    futures = {
        executor.submit(test_proxy, proxy, i): proxy 
        for i, proxy in enumerate(proxies[:1200]) # check up to 1200 proxies
    }
    for future in as_completed(futures):
        try:
            proxy, transcript = future.result()
            if transcript:
                print(f"SUCCESS with proxy: {proxy}!", flush=True)
                return transcript
        except Exception as e:
            if "NoTranscriptFound" in str(e):
                print(f"CRITICAL: YouTube returned NoTranscriptFound. Captions might be disabled. Error: {e}", flush=True)
                raise e
    return None

def main():
    proxies = get_proxies()
    if not proxies:
        print("No proxies found. Exiting.", flush=True)
        sys.exit(1)
        
    try:
        transcript = try_fetch_with_proxies_parallel(proxies)
        if transcript:
            output_file = f"scratch/raw_transcript_{video_id}.txt"
            with open(output_file, "w", encoding="utf-8") as f:
                for entry in transcript:
                    try:
                        start = entry['start']
                        duration = entry['duration']
                        text = entry['text']
                    except TypeError:
                        start = entry.start
                        duration = entry.duration
                        text = entry.text
                    
                    text = text.replace('\n', ' ')
                    f.write(f"[{start:.2f} + {duration:.2f}] {text}\n")
            print(f"Saved transcript to {output_file}", flush=True)
            # Use os._exit to terminate the process instantly, stopping all threads
            os._exit(0)
        else:
            print("Could not fetch transcript with any of the tried proxies.", flush=True)
            sys.exit(1)
    except Exception as e:
        print(f"Terminated with error: {e}", flush=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
