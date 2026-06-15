import re
import sys

def parse_vtt(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Split content into cues
    # Cues are separated by blank lines
    cues_raw = content.split('\n\n')
    
    cues = []
    timestamp_re = re.compile(r'^(\d{2}:\d{2}:\d{2}\.\d{3}) --> (\d{2}:\d{2}:\d{2}\.\d{3})')
    
    for block in cues_raw:
        lines = block.strip().split('\n')
        if not lines:
            continue
        
        # Check if first line matches timestamp pattern
        match = timestamp_re.match(lines[0])
        if match:
            start_time = match.group(1)
            end_time = match.group(2)
            # The rest of the lines are the text
            text_lines = []
            for line in lines[1:]:
                # remove tags
                cleaned = re.sub(r'<[^>]+>', '', line)
                cleaned = ' '.join(cleaned.split())
                if cleaned:
                    text_lines.append(cleaned)
            
            text = ' '.join(text_lines)
            if text:
                cues.append({
                    'start': start_time,
                    'end': end_time,
                    'text': text
                })
    
    # Now deduplicate cues that overlap/repeat
    deduped = []
    for cue in cues:
        if not deduped:
            deduped.append(cue)
            continue
        
        prev = deduped[-1]
        prev_text = prev['text'].strip()
        curr_text = cue['text'].strip()
        
        # If current text starts with previous text, it's a continuation/update of the same line
        if curr_text.startswith(prev_text):
            # Update the previous cue's end time and text
            prev['end'] = cue['end']
            prev['text'] = curr_text
        elif prev_text.startswith(curr_text):
            # Current text is a substring of previous, keep previous but maybe update end time
            prev['end'] = max(prev['end'], cue['end'])
        else:
            # Check if there is some overlap at the end of prev and start of curr
            # (e.g. if the line scrolled and some words are at the end of prev and start of curr)
            words_prev = prev_text.split()
            words_curr = curr_text.split()
            
            overlap_found = False
            # Try to find overlap of words (max 8 words)
            for i in range(min(len(words_prev), 8), 0, -1):
                if words_prev[-i:] == words_curr[:i]:
                    # Overlap found! Merge them
                    merged_text = ' '.join(words_prev + words_curr[i:])
                    prev['text'] = merged_text
                    prev['end'] = cue['end']
                    overlap_found = True
                    break
            
            if not overlap_found:
                deduped.append(cue)
                
    return deduped

def format_timestamp(ts_str):
    # ts_str is HH:MM:SS.mmm
    # Convert to HH:MM:SS or MM:SS for readability
    parts = ts_str.split('.')
    hms = parts[0]
    # If hours is 00, just show MM:SS
    if hms.startswith('00:'):
        return hms[3:]
    return hms

if __name__ == '__main__':
    deduped_cues = parse_vtt('subs.en.vtt')
    
    # Let's print out the cleaned cues with their starting timestamps
    # Group them into larger chunks of ~30-60 seconds or when there's a natural gap
    current_chunk = []
    chunk_start = None
    
    for i, cue in enumerate(deduped_cues):
        if chunk_start is None:
            chunk_start = cue['start']
        
        current_chunk.append(cue['text'])
        
        # If we have gathered enough cues, or if the time gap is large, or if it's the last cue
        is_last = (i == len(deduped_cues) - 1)
        time_diff = 0
        if not is_last:
            # compute gap in seconds
            def to_secs(t):
                h, m, s = t.split(':')
                s, ms = s.split('.')
                return int(h)*3600 + int(m)*60 + int(s) + int(ms)/1000.0
            time_diff = to_secs(deduped_cues[i+1]['start']) - to_secs(cue['end'])
            
        if len(current_chunk) >= 10 or time_diff > 3.0 or is_last:
            combined_text = ' '.join(current_chunk)
            print(f"[{format_timestamp(chunk_start)}] {combined_text}\n")
            current_chunk = []
            chunk_start = None
