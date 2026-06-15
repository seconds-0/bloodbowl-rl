import re
import sys

def format_time(seconds):
    mins = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{mins:02d}:{secs:02d}"

def clean_transcript(file_path, output_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    pattern = re.compile(r'^\[(\d+\.\d+)\s*\+\s*(\d+\.\d+)\]\s*(.*)$')
    cues = []
    
    for line in lines:
        match = pattern.match(line.strip())
        if match:
            start = float(match.group(1))
            duration = float(match.group(2))
            text = match.group(3).strip()
            if text:
                cues.append({
                    'start': start,
                    'end': start + duration,
                    'text': text
                })
                
    # Deduplicate and group cues
    grouped = []
    current_text = []
    current_start = None
    
    for i, cue in enumerate(cues):
        if current_start is None:
            current_start = cue['start']
        
        current_text.append(cue['text'])
        
        # Group every 8 cues or if there's a natural pause (e.g. gap > 3 seconds)
        is_last = (i == len(cues) - 1)
        gap = 0
        if not is_last:
            gap = cues[i+1]['start'] - cue['end']
            
        if len(current_text) >= 8 or gap > 3.0 or is_last:
            combined = ' '.join(current_text)
            # Simple deduplication of adjacent duplicate words/phrases
            words = combined.split()
            deduped_words = []
            for word in words:
                if not deduped_words or deduped_words[-1] != word:
                    deduped_words.append(word)
            combined_clean = ' '.join(deduped_words)
            
            grouped.append(f"[{format_time(current_start)}] {combined_clean}")
            current_text = []
            current_start = None
            
    with open(output_path, 'w', encoding='utf-8') as f:
        for item in grouped:
            f.write(item + "\n\n")
            
    print(f"Successfully cleaned transcript and saved to {output_path}")

if __name__ == '__main__':
    clean_transcript('scratch/raw_transcript_5U_m3E7HJ38.txt', 'scratch/cleaned_target_transcript.txt')
