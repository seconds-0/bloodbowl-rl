import os
import subprocess

timestamps = {
    "puzzle1_start": "00:01:15",
    "puzzle1_layout": "00:02:55",
    "puzzle1_t_shapes": "00:04:15",
    "puzzle1_solution": "00:05:45",
    "puzzle1_execution": "00:06:30",
    "puzzle2_transition": "00:08:00",
    "puzzle2_start": "00:11:15",
    "puzzle2_method1": "00:13:10",
    "puzzle2_method2": "00:14:15",
    "puzzle2_post_surf": "00:14:50"
}

output_dir = "/Users/alexanderhuth/.gemini/antigravity-cli/brain/3a415868-b2b7-4f5d-b118-dec581ae33d0/scratch"
os.makedirs(output_dir, exist_ok=True)

for name, ts in timestamps.items():
    output_path = os.path.join(output_dir, f"{name}.jpg")
    cmd = [
        "ffmpeg", "-y",
        "-ss", ts,
        "-i", "test_video.mp4",
        "-vframes", "1",
        "-q:v", "2",
        output_path
    ]
    print(f"Extracting {name} at {ts}...", flush=True)
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

print("Extraction complete!", flush=True)
