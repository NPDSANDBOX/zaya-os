#!/usr/bin/env python3
"""
PIPELINE CogVideoX-5B I2V — Zaya OS
"""
import sys, os, json, time
import torch
from diffusers import CogVideoXImageToVideoPipeline
from diffusers.utils import load_image, export_to_video

MODEL_PATH = "/opt/zaya_os/hub/models/cogvideox-5b-i2v"

def run(spec_path):
    with open(spec_path) as f:
        args = json.load(f)

    image_path  = args.get("image", "")
    prompt      = args.get("prompt", "cinematic motion")
    output_path = args.get("output", f"/opt/zaya_os/hub/io/output/video/cogvideox_{int(time.time())}.mp4")
    num_frames  = int(args.get("num_frames", 49))
    steps       = int(args.get("num_inference_steps", 50))
    guidance    = float(args.get("guidance_scale", 6.0))
    fps         = int(args.get("fps", 8))
    seed        = int(args.get("seed", 42))

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

    print(f"[COG] Loading model...", flush=True)
    pipe = CogVideoXImageToVideoPipeline.from_pretrained(
        MODEL_PATH,
        torch_dtype=torch.bfloat16
    )
    pipe.enable_sequential_cpu_offload()
    pipe.vae.enable_tiling()
    pipe.vae.enable_slicing()

    print(f"[COG] Image: {image_path}", flush=True)
    print(f"[COG] Frames: {num_frames} | Steps: {steps}", flush=True)

    image = load_image(image_path)
    generator = torch.Generator().manual_seed(seed)

    t0 = time.time()
    result = pipe(
        image=image,
        prompt=prompt,
        num_frames=num_frames,
        num_inference_steps=steps,
        guidance_scale=guidance,
        generator=generator,
    )
    elapsed = time.time() - t0

    export_to_video(result.frames[0], output_path, fps=fps)
    print(f"[COG] OK: {output_path} ({elapsed:.1f}s)", flush=True)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: pipeline_cogvideox.py <spec.json>")
        sys.exit(1)
    run(sys.argv[1])
