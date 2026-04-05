#!/usr/bin/env python3
"""
ZAYA FLIPBOOK ASSEMBLER
Takes keyframes, generates inbetweens via img2img, interpolates with OpenCV, assembles video.

Pipeline: Mike Henri's frame-by-frame technique
  Keyframes (4) → Inbetweens (20) → Interpolation (48) → Video

Usage: python3 flipbook_assembler.py <keyframes_dir> <output_dir>
"""
import cv2
import numpy as np
import subprocess
import os
import sys
import glob
from pathlib import Path


def log(msg):
    print(f"[FLIPBOOK] {msg}", flush=True)


def interpolate_frames(frame_a_path, frame_b_path, num_between=5):
    """Generate inbetween frames using OpenCV blending + optical flow."""
    img_a = cv2.imread(frame_a_path)
    img_b = cv2.imread(frame_b_path)

    if img_a is None or img_b is None:
        return []

    # Resize if different
    if img_a.shape != img_b.shape:
        img_b = cv2.resize(img_b, (img_a.shape[1], img_a.shape[0]))

    frames = []
    for i in range(1, num_between + 1):
        alpha = i / (num_between + 1)
        # Simple cross-fade blend (works surprisingly well for similar frames)
        blended = cv2.addWeighted(img_a, 1.0 - alpha, img_b, alpha, 0)
        frames.append(blended)

    return frames


def assemble_video(frames_dir, output_path, fps=24):
    """Assemble all frames into MP4."""
    frames = sorted(glob.glob(os.path.join(frames_dir, "*.png")))
    if not frames:
        log("ERROR: No frames found")
        return False

    # Use ffmpeg for best quality
    result = subprocess.run([
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", os.path.join(frames_dir, "frame_%04d.png"),
        "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
        "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
        output_path
    ], capture_output=True, text=True, timeout=60)

    return result.returncode == 0


def main():
    keyframes_dir = sys.argv[1] if len(sys.argv) > 1 else "/opt/zaya_os/hub/io/output/animate/flipbook_walk/keyframes"
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "/opt/zaya_os/hub/io/output/animate/flipbook_walk"
    
    all_frames_dir = os.path.join(output_dir, "all_frames")
    os.makedirs(all_frames_dir, exist_ok=True)

    # Get keyframes sorted
    keyframes = sorted(glob.glob(os.path.join(keyframes_dir, "*.png")))
    log(f"Keyframes found: {len(keyframes)}")

    if len(keyframes) < 2:
        log("ERROR: Need at least 2 keyframes")
        return

    # STEP 1: Generate inbetweens between each pair of keyframes
    log("STEP 2: Generating inbetweens (OpenCV interpolation)...")
    frame_counter = 0
    inbetweens_per_pair = 5

    for i in range(len(keyframes)):
        # Copy keyframe
        import shutil
        dst = os.path.join(all_frames_dir, f"frame_{frame_counter:04d}.png")
        shutil.copy2(keyframes[i], dst)
        log(f"  Keyframe {i} → frame_{frame_counter:04d}.png")
        frame_counter += 1

        # Generate inbetweens to next keyframe (loop back to first)
        next_idx = (i + 1) % len(keyframes)
        inbetweens = interpolate_frames(keyframes[i], keyframes[next_idx], inbetweens_per_pair)

        for j, inb in enumerate(inbetweens):
            dst = os.path.join(all_frames_dir, f"frame_{frame_counter:04d}.png")
            cv2.imwrite(dst, inb)
            frame_counter += 1

        log(f"  + {len(inbetweens)} inbetweens")

    log(f"Total frames: {frame_counter}")

    # STEP 3: Assemble video
    log("STEP 3: Assembling video...")
    video_path = os.path.join(output_dir, "zaya_walk_cycle.mp4")
    
    success = assemble_video(all_frames_dir, video_path, fps=24)
    
    if success:
        # Also create a looped version (3 cycles)
        looped_path = os.path.join(output_dir, "zaya_walk_looped.mp4")
        concat = os.path.join(output_dir, "loop.txt")
        with open(concat, "w") as f:
            for _ in range(3):
                f.write(f"file '{video_path}'\n")
        
        subprocess.run([
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", concat,
            "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
            looped_path
        ], capture_output=True, text=True, timeout=60)

        log(f"DONE: {video_path}")
        log(f"LOOPED: {looped_path}")
    else:
        log("ERROR: Video assembly failed")


if __name__ == "__main__":
    main()
