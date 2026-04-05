#!/usr/bin/env python3
"""
PIPELINE WAN2GP v1 — Zaya OS
Image-to-Video animation via Wan2GP API (headless, no UI needed).

Spec JSON format:
{
    "image_path": "/path/to/image.png",
    "prompt": "motion description — what should move and how",
    "output": "/path/to/output.mp4",
    "resolution": "832x480",
    "video_length": 81,
    "num_inference_steps": 30,
    "flow_shift": 7.0,
    "motion_amplitude": 1.15
}
"""
import sys
import os
import json
import time

WAN2GP_ROOT = "/opt/zaya_os/tools/Wan2GP"

def run(spec_path):
    with open(spec_path) as f:
        args = json.load(f)

    image_path = args.get("image_path", "")
    prompt = args.get("prompt", "")
    output_path = args.get("output", "")
    resolution = args.get("resolution", "832x480")
    video_length = int(args.get("video_length", 81))
    num_inference_steps = int(args.get("num_inference_steps", 30))
    flow_shift = float(args.get("flow_shift", 7.0))
    motion_amplitude = float(args.get("motion_amplitude", 1.15))
    negative = args.get("negative", "blurry, low quality, cartoon, anime, static image")

    if not image_path or not os.path.exists(image_path):
        print(f"[WAN2GP] ERROR: image not found: {image_path}", flush=True)
        sys.exit(1)

    if not output_path:
        output_path = f"/opt/zaya_os/hub/io/output/videos/wan2gp_{int(time.time())}.mp4"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    print(f"[WAN2GP] Image: {image_path}", flush=True)
    print(f"[WAN2GP] Prompt: {prompt[:80]}...", flush=True)
    print(f"[WAN2GP] Resolution: {resolution} | Frames: {video_length} | Steps: {num_inference_steps}", flush=True)

    # Add Wan2GP to path
    sys.path.insert(0, WAN2GP_ROOT)

    from shared.api import WanGPSession

    t0 = time.time()

    session = WanGPSession(
        root=WAN2GP_ROOT,
        output_dir=os.path.dirname(output_path),
        console_output=True,
        cli_args=["--i2v-14B"],
    )

    task_settings = {
        "model_type": args.get("model_type", "i2v"),
        "prompt": prompt,
        "negative_prompt": negative,
        "image_start": os.path.abspath(image_path),
        "image_prompt_type": "S",
        "resolution": resolution,
        "video_length": video_length,
        "num_inference_steps": num_inference_steps,
        "flow_shift": flow_shift,
        "motion_amplitude": motion_amplitude,
        "sample_solver": "unipc",
        "sliding_window_overlap": 1,
        "sliding_window_color_correction_strength": 0,
    }

    print(f"[WAN2GP] Submitting I2V task...", flush=True)
    job = session.submit_task(task_settings)

    # Monitor progress
    for event in job.events.iter(timeout=1.0):
        if event.kind == "progress":
            data = event.data
            if hasattr(data, "progress"):
                print(f"[WAN2GP] {data.phase}: {data.progress}% ({data.current_step}/{data.total_steps})", flush=True)
        elif event.kind == "completed":
            break
        elif event.kind == "error":
            print(f"[WAN2GP] ERROR: {event.data}", flush=True)
            break

    result = job.result(timeout=1800)

    elapsed = time.time() - t0

    if result.success and result.generated_files:
        # Move/rename output to desired path
        src = result.generated_files[0]
        if src != output_path:
            import shutil
            shutil.move(src, output_path)
        print(f"[WAN2GP] OK: {output_path} ({elapsed:.1f}s)", flush=True)
    else:
        errors = ", ".join(str(e) for e in result.errors)
        print(f"[WAN2GP] FAILED: {errors} ({elapsed:.1f}s)", flush=True)
        sys.exit(1)

    session.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "error": "usage: pipeline_wan2gp_v1.py <spec.json>"}))
        sys.exit(1)
    run(sys.argv[1])
