#!/usr/bin/env python3
"""
ZAYA PIPELINE — SVD Cinematic
Animates a static image into a 30-40s cinematic video.
Zero acceleration, zero distortion, zero ping-pong loop.

Invented by Mike Henri.

Pipeline:
  1. Pad image to 16:9 (no stretch) → 1024x576
  2. Generate N clips via SVD with different seeds (varied motion)
  3. Cut each clip in half (remove ping-pong return)
  4. Frame interpolation (minterpolate) → smooth 24fps without speedup
  5. Crossfade between clips (0.5s dissolve)
  6. Concatenate → final 30-40s cinematic video

Usage:
  python3 pipeline_svd_cinematic.py <spec.json>

spec.json:
  {
    "image": "/path/to/source.png",
    "output": "/path/to/output.mp4",
    "duration": 30,
    "motion": 80
  }
"""
import sys
import json
import os
import time
import shutil
import subprocess
import torch
import warnings

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

from diffusers import StableVideoDiffusionPipeline
from diffusers.utils import export_to_video
from PIL import Image

SVD_MODEL = "/opt/zaya_os/hub/models/sd/svd"
SVD_WIDTH = 1024
SVD_HEIGHT = 576
SVD_NUM_FRAMES = 25
SVD_FPS = 7
SVD_STEPS = 30
SVD_DECODE_CHUNK = 4
SVD_NOISE_AUG = 0.02
TARGET_FPS = 24
CROSSFADE_DURATION = 0.5
# Work dir — NEVER /tmp
WORK_BASE = "/opt/zaya_os/hub/data/contracts/svd_cinematic_work"


def log(msg):
    print(f"[SVD_CINEMATIC] {msg}", flush=True)


def pad_image_16_9(image_path, output_path):
    """Pad image to 1024x576 without stretching. Black letterbox."""
    cmd = [
        "ffmpeg", "-y", "-i", image_path,
        "-vf", f"scale={SVD_WIDTH}:{SVD_HEIGHT}:force_original_aspect_ratio=decrease,"
               f"pad={SVD_WIDTH}:{SVD_HEIGHT}:(ow-iw)/2:(oh-ih)/2:black",
        output_path
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg pad failed: {r.stderr}")
    log(f"Padded image: {output_path}")


def generate_svd_clip(pipe, image, seed, motion_bucket_id, output_path):
    """Generate a single SVD clip."""
    generator = torch.Generator("cpu").manual_seed(seed)
    frames = pipe(
        image=image,
        num_frames=SVD_NUM_FRAMES,
        decode_chunk_size=SVD_DECODE_CHUNK,
        motion_bucket_id=motion_bucket_id,
        noise_aug_strength=SVD_NOISE_AUG,
        num_inference_steps=SVD_STEPS,
        generator=generator,
    ).frames[0]

    export_to_video(frames, output_path, fps=SVD_FPS)
    log(f"Generated clip: {output_path} (seed={seed}, {len(frames)} frames)")
    return len(frames)


def cut_half(input_path, output_path):
    """Cut clip to first half only — removes ping-pong return loop."""
    # Get duration
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", input_path],
        capture_output=True, text=True
    )
    duration = float(probe.stdout.strip())
    half = duration / 2.0

    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-t", f"{half:.3f}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        output_path
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg cut failed: {r.stderr}")
    log(f"Cut to {half:.2f}s: {output_path}")
    return half


def interpolate_frames(input_path, output_path):
    """Interpolate frames from SVD native fps to 24fps — smooth, no speedup."""
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-vf", f"minterpolate=fps={TARGET_FPS}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        output_path
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg interpolation failed: {r.stderr}")
    log(f"Interpolated to {TARGET_FPS}fps: {output_path}")


def get_duration(path):
    """Get video duration in seconds."""
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        capture_output=True, text=True
    )
    return float(probe.stdout.strip())


def crossfade_clips(clip_paths, output_path):
    """Crossfade all clips together with dissolve transitions."""
    if len(clip_paths) == 1:
        shutil.copy2(clip_paths[0], output_path)
        return

    # Build xfade filter chain incrementally
    # [0][1] xfade → [v01], [v01][2] xfade → [v012], etc.
    durations = [get_duration(p) for p in clip_paths]
    log(f"Clip durations: {[f'{d:.2f}s' for d in durations]}")

    inputs = []
    for p in clip_paths:
        inputs.extend(["-i", p])

    filter_parts = []
    # Calculate offsets: each xfade starts at (accumulated_duration - crossfade_overlap)
    accumulated = durations[0]

    for i in range(1, len(clip_paths)):
        offset = accumulated - CROSSFADE_DURATION
        if offset < 0:
            offset = 0

        if i == 1:
            src = "[0:v]"
        else:
            src = f"[v{i-1}]"

        dst = f"[{i}:v]"

        if i == len(clip_paths) - 1:
            out = "[vout]"
        else:
            out = f"[v{i}]"

        filter_parts.append(
            f"{src}{dst}xfade=transition=fade:duration={CROSSFADE_DURATION}:offset={offset:.3f}{out}"
        )
        accumulated = offset + durations[i]

    filter_complex = ";".join(filter_parts)

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        output_path
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg crossfade failed: {r.stderr}")
    log(f"Crossfade done: {output_path}")


def calculate_num_clips(target_duration):
    """Calculate how many SVD clips needed for target duration.
    Each clip: 25 frames at 7fps = 3.57s, cut in half = ~1.78s.
    After interpolation to 24fps the duration stays the same (~1.78s).
    With 0.5s crossfade overlap between clips:
      total ≈ N * 1.78 - (N-1) * 0.5
    """
    clip_duration = (SVD_NUM_FRAMES / SVD_FPS) / 2.0  # ~1.78s after half-cut
    # total = N * clip_duration - (N-1) * crossfade
    # target = N * clip_duration - N * crossfade + crossfade
    # target - crossfade = N * (clip_duration - crossfade)
    # N = (target - crossfade) / (clip_duration - crossfade)
    n = (target_duration - CROSSFADE_DURATION) / (clip_duration - CROSSFADE_DURATION)
    n = max(int(n) + 1, 2)  # At least 2 clips, round up
    return n


def run(spec_path):
    with open(spec_path) as f:
        args = json.load(f)

    image_path = args["image"]
    output_path = args["output"]
    target_duration = args.get("duration", 30)
    motion_bucket_id = args.get("motion", 80)

    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")

    num_clips = calculate_num_clips(target_duration)
    log(f"Target: {target_duration}s | Motion: {motion_bucket_id} | Clips needed: {num_clips}")
    log(f"Source: {image_path}")
    log(f"Output: {output_path}")

    t0 = time.time()

    # Setup work directory
    work_id = f"{int(time.time())}_{os.getpid()}"
    work_dir = os.path.join(WORK_BASE, work_id)
    os.makedirs(work_dir, exist_ok=True)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    try:
        # ── STEP 1: Pad image to 16:9 ──
        log("STEP 1/6 — Padding image to 16:9...")
        padded_image = os.path.join(work_dir, "input_padded.png")
        pad_image_16_9(image_path, padded_image)
        image = Image.open(padded_image).convert("RGB")

        # ── STEP 2: Load SVD and generate clips ──
        log("STEP 2/6 — Loading SVD pipeline...")
        torch.cuda.empty_cache()
        pipe = StableVideoDiffusionPipeline.from_pretrained(
            SVD_MODEL,
            torch_dtype=torch.float16,
            variant="fp16"
        )
        pipe.enable_sequential_cpu_offload()
        pipe.unet.enable_forward_chunking()

        base_seed = int(time.time())
        raw_clips = []

        for i in range(num_clips):
            seed = base_seed + i * 1337
            clip_path = os.path.join(work_dir, f"raw_{i:02d}.mp4")
            log(f"Generating clip {i+1}/{num_clips} (seed={seed})...")
            generate_svd_clip(pipe, image, seed, motion_bucket_id, clip_path)
            raw_clips.append(clip_path)
            torch.cuda.empty_cache()

        # Free model from memory — no longer needed
        del pipe
        torch.cuda.empty_cache()
        log("SVD pipeline unloaded, VRAM freed.")

        # ── STEP 3: Cut each clip in half ──
        log("STEP 3/6 — Cutting ping-pong loops...")
        cut_clips = []
        for i, raw in enumerate(raw_clips):
            cut_path = os.path.join(work_dir, f"cut_{i:02d}.mp4")
            cut_half(raw, cut_path)
            cut_clips.append(cut_path)

        # ── STEP 4: Frame interpolation ──
        log("STEP 4/6 — Interpolating frames to 24fps...")
        smooth_clips = []
        for i, cut in enumerate(cut_clips):
            smooth_path = os.path.join(work_dir, f"smooth_{i:02d}.mp4")
            interpolate_frames(cut, smooth_path)
            smooth_clips.append(smooth_path)

        # ── STEP 5: Crossfade ──
        log("STEP 5/6 — Crossfading clips...")
        crossfade_path = os.path.join(work_dir, "crossfaded.mp4")
        crossfade_clips(smooth_clips, crossfade_path)

        # ── STEP 6: Trim to target duration ──
        log("STEP 6/6 — Final trim and output...")
        final_duration = get_duration(crossfade_path)

        if final_duration > target_duration + 1:
            # Trim to target
            cmd = [
                "ffmpeg", "-y", "-i", crossfade_path,
                "-t", str(target_duration),
                "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                "-pix_fmt", "yuv420p",
                output_path
            ]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError(f"ffmpeg trim failed: {r.stderr}")
        else:
            shutil.copy2(crossfade_path, output_path)

        elapsed = time.time() - t0
        final_dur = get_duration(output_path)
        size = os.path.getsize(output_path)

        log(f"DONE — {output_path}")
        log(f"Duration: {final_dur:.1f}s | Size: {size/1024/1024:.1f}MB | Time: {elapsed:.0f}s")

        result = {
            "ok": True,
            "output": output_path,
            "duration_s": round(final_dur, 1),
            "clips_generated": num_clips,
            "fps": TARGET_FPS,
            "resolution": f"{SVD_WIDTH}x{SVD_HEIGHT}",
            "elapsed_s": round(elapsed, 1),
            "size_bytes": size
        }
        print(json.dumps(result))

    finally:
        # Clean up work directory
        if os.path.exists(work_dir):
            shutil.rmtree(work_dir)
            log(f"Cleaned work dir: {work_dir}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "error": "usage: pipeline_svd_cinematic.py <spec.json>"}))
        sys.exit(1)
    run(sys.argv[1])
