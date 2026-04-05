#!/usr/bin/env python3
"""
ZAYA PIPELINE — Stable Video Diffusion (SVD)
Animates a single image into a short video clip.
Full-scene animation: environment, characters, lighting — no face detection needed.
RTX 3080 Ti 12GB — sequential cpu offload + VAE slicing/tiling.

Usage:
  python3 pipeline_svd.py <spec.json>

spec.json:
  {
    "image": "/path/to/source.png",
    "output": "/path/to/output.mp4",
    "num_frames": 25,
    "fps": 7,
    "decode_chunk_size": 4,
    "motion_bucket_id": 127,
    "noise_aug_strength": 0.02,
    "steps": 25,
    "seed": 42,
    "width": 1024,
    "height": 576
  }
"""
import sys, json, os, time, torch, warnings
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

from diffusers import StableVideoDiffusionPipeline
from diffusers.utils import export_to_video
from PIL import Image

SVD_MODEL = "/opt/zaya_os/hub/models/sd/svd"


def run(spec_path):
    with open(spec_path) as f:
        args = json.load(f)

    image_path         = args["image"]
    output_path        = args["output"]
    num_frames         = args.get("num_frames", 25)
    fps                = args.get("fps", 7)
    decode_chunk_size  = args.get("decode_chunk_size", 4)
    motion_bucket_id   = args.get("motion_bucket_id", 127)
    noise_aug_strength = args.get("noise_aug_strength", 0.02)
    steps              = args.get("steps", 25)
    seed               = args.get("seed", int(time.time()))
    width              = args.get("width", 1024)
    height             = args.get("height", 576)

    print(f"[SVD] source: {image_path}", flush=True)
    print(f"[SVD] {width}x{height} | {num_frames} frames | {fps} fps | steps={steps} | motion={motion_bucket_id}", flush=True)

    t0 = time.time()
    torch.cuda.empty_cache()
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Load and resize source image
    image = Image.open(image_path).convert("RGB")
    image = image.resize((width, height), Image.LANCZOS)

    print("[SVD] Loading StableVideoDiffusionPipeline...", flush=True)
    pipe = StableVideoDiffusionPipeline.from_pretrained(
        SVD_MODEL,
        torch_dtype=torch.float16,
        variant="fp16"
    )
    pipe.enable_sequential_cpu_offload()
    pipe.unet.enable_forward_chunking()

    print("[SVD] Generating frames...", flush=True)
    generator = torch.Generator("cpu").manual_seed(seed)

    frames = pipe(
        image=image,
        num_frames=num_frames,
        decode_chunk_size=decode_chunk_size,
        motion_bucket_id=motion_bucket_id,
        noise_aug_strength=noise_aug_strength,
        num_inference_steps=steps,
        generator=generator,
    ).frames[0]

    print(f"[SVD] Generated {len(frames)} frames, exporting video...", flush=True)
    export_to_video(frames, output_path, fps=fps)

    elapsed = time.time() - t0
    size = os.path.getsize(output_path)
    print(f"[SVD] Saved: {output_path} ({size/1024:.0f}KB, {elapsed:.1f}s)", flush=True)

    result = {
        "ok": True,
        "output": output_path,
        "frames": len(frames),
        "fps": fps,
        "elapsed_s": round(elapsed, 1),
        "size_bytes": size
    }
    print(json.dumps(result))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "error": "usage: pipeline_svd.py <spec.json>"}))
        sys.exit(1)
    run(sys.argv[1])
