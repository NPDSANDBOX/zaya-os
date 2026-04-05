#!/usr/bin/env python3
"""
ZAYA PIPELINE — Scene-to-Wan2GP Bridge
Reads scene_to_prompt_v3 output and creates Wan2GP queue entries.
Injects the canonical Custom Character Universe chromatic system into every prompt.

Usage:
  python3 pipeline_scene_to_wan2gp.py <scenes.json> [--output /path/to/queue/]

Input: JSON from scene_to_prompt_v3 (list of scenes with prompts)
Output: Wan2GP queue JSON files ready for batch processing

Author: Mike Henri
System: Zaya OS
"""
import sys
import json
import os
import time
from pathlib import Path

sys.path.insert(0, "/opt/zaya_os/hub/capabilities/scene_to_prompt")
from scene_to_prompt_v3 import UNIVERSE_STYLE_ENV, UNIVERSE_STYLE_CHAR, UNIVERSE_NEGATIVE

WAN2GP_QUEUE_DIR = "/opt/zaya_os/tools/Wan2GP/outputs"
WORK_DIR = "/opt/zaya_os/hub/data/contracts/scene_to_wan2gp"
LORA_NAME = "custom_lora_v1"

# Canonical style suffix injected into EVERY Wan2GP prompt
CANONICAL_VIDEO_STYLE = (
    "cinematic video, smooth natural motion, atmospheric depth, "
    "petroleum blue environment, intense gold accents, deep iridescent blue shadows, "
    "oil-water spectral sheen on wet surfaces, electric cyan glitch traces, "
    "deep purple dimensional echoes, cold directional lighting, "
    "volumetric fog, rain reflections, 35mm film grain, "
    "dark cinematic atmosphere, photorealistic"
)


def log(msg):
    print(f"[SCENE2WAN] {msg}", flush=True)


def build_wan2gp_entry(scene, index, output_dir):
    """Convert a scene_to_prompt_v3 scene into a Wan2GP queue entry."""
    prompt = scene.get("prompt", "")
    negative = scene.get("negative", UNIVERSE_NEGATIVE)
    image_path = scene.get("image", "")

    # Inject canonical video style
    full_prompt = f"{prompt}, {CANONICAL_VIDEO_STYLE}"

    entry = {
        "id": f"scene_{index:03d}_{int(time.time())}",
        "prompt": full_prompt,
        "negative_prompt": negative,
        "resolution": scene.get("resolution", "832x480"),
        "num_frames": scene.get("num_frames", 33),
        "fps": scene.get("fps", 16),
        "steps": scene.get("steps", 30),
        "guidance": scene.get("guidance", 5.0),
        "seed": scene.get("seed", -1),
        "lora": LORA_NAME,
        "lora_strength": scene.get("lora_strength", 0.7),
    }

    if image_path and os.path.exists(image_path):
        entry["image"] = image_path
        entry["type"] = "i2v"
    else:
        entry["type"] = "t2v"

    return entry


def process_scenes(scenes_path, output_dir=None):
    with open(scenes_path) as f:
        data = json.load(f)

    scenes = data if isinstance(data, list) else data.get("scenes", [])
    if not scenes:
        log("ERROR: No scenes found in input")
        return

    if output_dir is None:
        output_dir = WORK_DIR
    os.makedirs(output_dir, exist_ok=True)

    queue = []
    for i, scene in enumerate(scenes):
        entry = build_wan2gp_entry(scene, i, output_dir)
        queue.append(entry)
        log(f"Scene {i}: {entry['type']} | {entry['prompt'][:80]}...")

    # Save queue file
    timestamp = time.strftime("%Y%m%dT%H%M%SZ")
    queue_file = os.path.join(output_dir, f"wan2gp_queue_{timestamp}.json")
    with open(queue_file, "w", encoding="utf-8") as f:
        json.dump({"queue": queue, "total": len(queue), "created": timestamp}, f, ensure_ascii=False, indent=2)

    log(f"Queue saved: {queue_file}")
    log(f"Total scenes: {len(queue)}")
    return queue_file


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: pipeline_scene_to_wan2gp.py <scenes.json> [--output /path/]")
        sys.exit(1)

    scenes_path = sys.argv[1]
    output_dir = None
    if "--output" in sys.argv:
        idx = sys.argv.index("--output")
        if idx + 1 < len(sys.argv):
            output_dir = sys.argv[idx + 1]

    process_scenes(scenes_path, output_dir)
