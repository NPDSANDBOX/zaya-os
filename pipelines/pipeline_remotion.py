#!/usr/bin/env python3
"""
PIPELINE REMOTION — Zaya OS
Render video with animated text, Ken Burns, particles, transitions.
Instant render — no AI animation needed.

Spec JSON:
{
    "scenes": [
        {"image": "/path/to/image.png", "text": "narration text", "duration": 10.0}
    ],
    "audio_file": "/path/to/narration.wav",
    "ambient_file": "/path/to/ambient.wav",
    "output": "/path/to/output.mp4",
    "fps": 30,
    "width": 1080,
    "height": 1920
}
"""
import sys
import os
import json
import shutil
import subprocess
import time

REMOTION_DIR = "/opt/zaya_os/tools/quantum-video"
PUBLIC_DIR = f"{REMOTION_DIR}/public"


def run(spec_path):
    with open(spec_path) as f:
        args = json.load(f)

    scenes = args.get("scenes", [])
    audio_file = args.get("audio_file", "")
    ambient_file = args.get("ambient_file", "")
    output_path = args.get("output", f"/opt/zaya_os/hub/io/output/videos/remotion_{int(time.time())}.mp4")
    fps = int(args.get("fps", 30))
    width = int(args.get("width", 1080))
    height = int(args.get("height", 1920))

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    os.makedirs(PUBLIC_DIR, exist_ok=True)

    print(f"[REMOTION] Scenes: {len(scenes)}", flush=True)

    # Copy assets to Remotion public folder
    remotion_scenes = []
    for i, scene in enumerate(scenes):
        img_name = f"scene{i+1}.png"
        src_img = scene["image"]
        if os.path.exists(src_img):
            shutil.copy2(src_img, f"{PUBLIC_DIR}/{img_name}")
        dur_frames = int(scene.get("duration", 8.0) * fps)
        remotion_scenes.append({
            "image": img_name,
            "text": scene.get("text", ""),
            "durationFrames": dur_frames,
        })

    if audio_file and os.path.exists(audio_file):
        shutil.copy2(audio_file, f"{PUBLIC_DIR}/audio.wav")
    if ambient_file and os.path.exists(ambient_file):
        shutil.copy2(ambient_file, f"{PUBLIC_DIR}/ambient.wav")

    total_frames = sum(s["durationFrames"] for s in remotion_scenes)
    print(f"[REMOTION] Total frames: {total_frames} ({total_frames/fps:.1f}s)", flush=True)

    # Write props file for Remotion
    props = {
        "scenes": remotion_scenes,
        "audioFile": "audio.wav" if audio_file else None,
        "ambientFile": "ambient.wav" if ambient_file else None,
    }
    props_path = f"{REMOTION_DIR}/input-props.json"
    with open(props_path, "w") as f:
        json.dump(props, f)

    # Render with Remotion CLI
    print(f"[REMOTION] Rendering {width}x{height} @ {fps}fps...", flush=True)
    t0 = time.time()

    result = subprocess.run([
        "npx", "remotion", "render",
        "QuantumShort",
        output_path,
        "--props", props_path,
        "--width", str(width),
        "--height", str(height),
        "--fps", str(fps),
        "--frames", f"0-{total_frames - 1}",
        "--codec", "h264",
        "--crf", "18",
    ], cwd=REMOTION_DIR, capture_output=True, text=True, timeout=300)

    elapsed = time.time() - t0

    if result.returncode == 0 and os.path.exists(output_path):
        size_mb = os.path.getsize(output_path) / 1024 / 1024
        print(f"[REMOTION] OK: {output_path} ({elapsed:.1f}s, {size_mb:.1f}MB)", flush=True)
    else:
        print(f"[REMOTION] FAILED ({elapsed:.1f}s)", flush=True)
        if result.stderr:
            print(result.stderr[-500:], flush=True)
        sys.exit(1)

    # Cleanup
    try:
        os.remove(props_path)
    except Exception:
        pass


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "error": "usage: pipeline_remotion.py <spec.json>"}))
        sys.exit(1)
    run(sys.argv[1])
