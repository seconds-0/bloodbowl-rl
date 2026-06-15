import sys
from youtube_transcript_api import YouTubeTranscriptApi

video_id = "5U_m3E7HJ38"

try:
    print(f"Fetching transcript for video ID: {video_id}")
    api = YouTubeTranscriptApi()
    transcript = api.fetch(video_id)
    
    # Save raw transcript with timestamps
    with open(f"scratch/raw_transcript_{video_id}.txt", "w", encoding="utf-8") as f:
        for entry in transcript:
            start = entry['start']
            duration = entry['duration']
            text = entry['text'].replace('\n', ' ')
            f.write(f"[{start:.2f} + {duration:.2f}] {text}\n")
            
    print(f"Successfully saved transcript with timestamps to scratch/raw_transcript_{video_id}.txt")
    
except Exception as e:
    import traceback
    print(f"Error fetching transcript: {e}")
    traceback.print_exc()
    sys.exit(1)
