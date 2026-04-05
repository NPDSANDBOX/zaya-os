#!/usr/bin/env python3
"""
PIPELINE HUNYUAN VIDEO 1.5 I2V — Zaya OS
Image-to-Video using HunyuanVideo 1.5 via Wan2GP API (headless).
Step-distilled model (8 steps), INT8 quantized.
Uses models already in /opt/zaya_os/tools/Wan2GP/ckpts/ — no downloads.

Spec JSON:
{
    "image_path": "/path/to/image.png",
    "prompt": "motion description",
    "output": "/path/to/output.mp4",
    "num_frames": 97,
    "num_inference_steps": 8,
    "fps": 24
}
"""
import sys
import os
import json
import time
import shutil

WAN2GP_ROOT = "/opt/zaya_os/tools/Wan2GP"


def run(spec_path):
    with open(spec_path) as f:
        args = json.load(f)

    image_path = args.get("image_path", "")
    prompt = args.get("prompt", "")
    negative = args.get("negative", "")
    output_path = args.get("output", f"/opt/zaya_os/hub/io/output/videos/hunyuan_{int(time.time())}.mp4")
    num_frames = int(args.get("num_frames", 97))
    num_inference_steps = int(args.get("num_inference_steps", 8))
    flow_shift = float(args.get("flow_shift", 5.0))
    seed = int(args.get("seed", -1))

    if not image_path or not os.path.exists(image_path):
        print(f"[HUNYUAN] ERROR: image not found: {image_path}", flush=True)
        sys.exit(1)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    print(f"[HUNYUAN] Image: {image_path}", flush=True)
    print(f"[HUNYUAN] Prompt: {prompt[:80]}...", flush=True)
    print(f"[HUNYUAN] Frames: {num_frames} | Steps: {num_inference_steps}", flush=True)

    sys.path.insert(0, WAN2GP_ROOT)
    from shared.api import WanGPSession

    t0 = time.time()

    session = WanGPSession(
        root=WAN2GP_ROOT,
        output_dir=os.path.dirname(output_path),
        console_output=True,
    )

    task_settings = {
        "model_type": "hunyuan_1_5_480_i2v_step_distilled",
        "prompt": prompt,
        "negative_prompt": negative,
        "image_start": os.path.abspath(image_path),
        "image_prompt_type": "S",
        "resolution": "832x480",
        "video_length": num_frames,
        "num_inference_steps": num_inference_steps,
        "guidance_scale": 1.0,
        "embedded_guidance_scale": 6.0,
        "flow_shift": flow_shift,
        "sample_solver": "unipc",
        "sliding_window_overlap": 1,
    }

    print(f"[HUNYUAN] Submitting I2V task...", flush=True)
    job = session.submit_task(task_settings)

    for event in job.events.iter(timeout=1.0):
        if event.kind == "progress":
            data = event.data
            if hasattr(data, "progress"):
                print(f"[HUNYUAN] {data.phase}: {data.progress}% ({data.current_step}/{data.total_steps})", flush=True)
        elif event.kind == "completed":
            break
        elif event.kind == "error":
            print(f"[HUNYUAN] ERROR: {event.data}", flush=True)
            break

    result = job.result(timeout=1800)
    elapsed = time.time() - t0

    if result.success and result.generated_files:
        src = result.generated_files[0]
        if src != output_path:
            shutil.move(src, output_path)
        print(f"[HUNYUAN] OK: {output_path} ({elapsed:.1f}s)", flush=True)
    else:
        errors = ", ".join(str(e) for e in result.errors)
        print(f"[HUNYUAN] FAILED: {errors} ({elapsed:.1f}s)", flush=True)
        sys.exit(1)

    session.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "error": "usage: pipeline_hunyuan_i2v.py <spec.json>"}))
        sys.exit(1)
    run(sys.argv[1])
