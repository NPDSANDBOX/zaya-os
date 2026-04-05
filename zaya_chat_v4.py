#!/usr/bin/env python3
import json
import re
import time
import requests
import sys
import os
import subprocess

BASE_DIR = "/opt/zaya_os/hub"
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from capabilities.zaya_chat_logger_v1 import log_turn

LLM_URL          = "http://127.0.0.1:8080/v1/chat/completions"
DIFFUSION_PYTHON = "/opt/zaya_os/venvs/zaya_diffusion/bin/python3"
PIPELINE_JUG_V3  = "/opt/zaya_os/hub/capabilities/pipelines/pipeline_juggernaut_v3.py"
PIPELINE_FLUX1   = "/opt/zaya_os/hub/capabilities/pipelines/pipeline_flux1.py"
PIPELINE_HUNYUAN = "/opt/zaya_os/hub/capabilities/pipelines/pipeline_hunyuan_i2v.py"
PIPELINE_REMOTION = "/opt/zaya_os/hub/capabilities/pipelines/pipeline_remotion.py"
PIPELINE_WAN2GP  = "/opt/zaya_os/hub/capabilities/pipelines/pipeline_wan2gp_v1.py"
WAN2GP_PYTHON    = "/opt/zaya_os/venvs/wan2gp/bin/python3"
VIDEO_OUTPUT_DIR = "/opt/zaya_os/hub/io/output/videos"
LORA_ZAYA        = "/opt/zaya_os/hub/models/loras/zaya_universe/output/custom_lora_v1.safetensors"
FACEID_ZAYA      = "/opt/zaya_os/hub/memory/universe_docs/characters/CustomCharacter/zaya_custom_faceid_reference.png"
OUTPUT_DIR       = "/opt/zaya_os/hub/io/output/images"

# ─────────────────────────────────────────────
# SYSTEM PROMPT
# ─────────────────────────────────────────────
def load_system_prompt():
    path = "/opt/zaya_os/hub/memory/zaya_system_prompt.txt"
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

# ─────────────────────────────────────────────
# CONTRACT EXTRACTION
# ─────────────────────────────────────────────
def extract_contract(text):
    # Remove think blocks
    if "<think>" in text and "</think>" in text:
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    match = re.search(r"<CONTRACT>(.*?)</CONTRACT>", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except:
            return None
    match = re.search(r"<CONTRACT>(.*)", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except:
            return None
    return None

# ─────────────────────────────────────────────
# IMAGE HANDLER — direct spec to pipeline
# ─────────────────────────────────────────────
def handle_image(contract):
    print("[ZAYA] dispatch → image (direct spec)")

    # Free GPU for render via Compute Router
    print("[ZAYA] Compute Router: freeing GPU for render...")
    subprocess.run(["python3", "/opt/zaya_os/hub/kernel/zaya_compute_router.py", "free"],
                   capture_output=True, timeout=30)

    input_data = contract.get("input", {})
    if not input_data.get("prompt"):
        print("[ERROR] missing prompt in contract")
        return

    # Select pipeline — Flux1 is default, Juggernaut v3 is alternative
    pipeline_name = input_data.get("pipeline", "flux1")
    if "juggernaut" in pipeline_name:
        pipeline_script = PIPELINE_JUG_V3
    else:
        pipeline_script = PIPELINE_FLUX1

    # Resolve CustomFaceID reference — always use canonical when zaya is the character
    characters = input_data.get("characters", ["zaya"])
    char_name = characters[0].lower() if characters else "zaya"
    if char_name == "zaya":
        custom_faceid_ref = FACEID_ZAYA
    else:
        custom_faceid_ref = input_data.get("custom_faceid_ref", "")

    # Hardcoded canonical layers — injected regardless of LLM output
    GLITCH_LAYER = "Glitch dimensional artifacts, edge misalignment, reality fractures, subtle dimensional instability"
    CAMERA_FINISH = "dark cinematic atmosphere, deep depth of field, sharp background, detailed environment, everything in focus, f/11 aperture, 35mm film grain"

    # Force Glitch + camera finishing into prompt
    raw_prompt = input_data.get("prompt", "")
    if GLITCH_LAYER not in raw_prompt:
        raw_prompt = f"{raw_prompt}, {GLITCH_LAYER}"
    if "f/11" not in raw_prompt:
        raw_prompt = f"{raw_prompt}, {CAMERA_FINISH}"

    # Build pipeline spec directly from contract
    output_path = f"{OUTPUT_DIR}/chat_{int(time.time())}.png"
    spec = {
        "prompt":           raw_prompt,
        "prompt_character": input_data.get("prompt_character", ""),
        "negative":         input_data.get("negative", ""),
        "output":           output_path,
        "width":            int(input_data.get("width", 1152)),
        "height":           int(input_data.get("height", 1536)),
        "steps":            int(input_data.get("steps", 50)),
        "guidance":         float(input_data.get("guidance", 7.6)),
        "lora":             LORA_ZAYA if char_name == "zaya" else "",
        "custom_faceid_ref":       custom_faceid_ref,
        "custom_faceid_scale":     float(input_data.get("custom_faceid_scale", 0.6)),
    }

    # Write spec and run pipeline
    spec_path = f"{OUTPUT_DIR}/spec_chat_{int(time.time())}.json"
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(spec_path, "w") as f:
        json.dump(spec, f)

    print(f"[ZAYA] pipeline: {pipeline_name} | spec: {spec_path}")
    result = subprocess.run(
        [DIFFUSION_PYTHON, pipeline_script, spec_path],
        timeout=600
    )

    try:
        os.remove(spec_path)
    except Exception:
        pass

    if result.returncode == 0 and os.path.exists(output_path):
        print(f"[IMAGE GENERATED] {output_path}")
    else:
        print(f"[IMAGE ERROR] pipeline {pipeline_name} failed (exit {result.returncode})")

    post_image_cleanup()

    # Restore LLM after render
    print("[ZAYA] Compute Router: restoring LLM...")
    subprocess.run(["python3", "/opt/zaya_os/hub/kernel/zaya_compute_router.py", "restore"],
                   capture_output=True, timeout=60)

# ─────────────────────────────────────────────
# ANIMATION HANDLER
# ─────────────────────────────────────────────
def handle_animation(contract):
    print("[ZAYA] dispatch → animation_tool")
    from capabilities.zaya_image_animation_tool_v1 import generate_animation
    from capabilities.zaya_image_tool_v2 import generate_image

    input_data = contract.get("input", {})
    image  = input_data.get("image")
    prompt = next((v for v in input_data.values() if isinstance(v, str)), None)

    if not image and prompt:
        print("[ZAYA] no image → generating first")
        img_path, err = generate_image(prompt=prompt)
        if err:
            print("[ERROR]", err)
            return
        image = img_path

    path, err = generate_animation(image_path=image, prompt=prompt)
    if err:
        print("[ANIMATION ERROR]", err)
    else:
        print("[ANIMATION GENERATED]", path)

# ─────────────────────────────────────────────
# KEN BURNS HANDLER
# ─────────────────────────────────────────────
def handle_kenburns(contract):
    print("[ZAYA] dispatch → kenburns")
    from capabilities.pipelines.zaya_kenburns_bridge import render

    input_data = contract.get("input", {})
    image  = input_data.get("image")
    preset = input_data.get("preset", "auto")
    frames = int(input_data.get("frames", 450))
    fps    = int(input_data.get("fps", 30))

    if not image:
        from capabilities.zaya_image_tool_v2 import generate_image
        prompt = next((v for v in input_data.values() if isinstance(v, str)), None)
        if not prompt:
            print("[ERROR] ken_burns: no image and no prompt")
            return
        print("[ZAYA] ken_burns: generating image first")
        img_path, err = generate_image(prompt=prompt)
        if err:
            print("[ERROR]", err)
            return
        image = img_path

    result = render(image_path=image, preset=preset, frames=frames, fps=fps)
    if result["ok"]:
        print(f"[KEN BURNS] OK {result['video']}")
    else:
        print(f"[KEN BURNS] FAIL {result.get('error', '?')}")

# ─────────────────────────────────────────────
# VIDEO HANDLER — Remotion / Wan2GP
# ─────────────────────────────────────────────
def handle_video(contract):
    input_data = contract.get("input", {})
    engine = input_data.get("engine", "remotion")
    scenes = input_data.get("scenes", [])
    output = input_data.get("output", f"{VIDEO_OUTPUT_DIR}/video_{int(time.time())}.mp4")

    os.makedirs(os.path.dirname(output), exist_ok=True)

    print(f"[ZAYA] dispatch → video ({engine})", flush=True)

    spec = {
        "scenes": scenes,
        "audio_file": input_data.get("audio_file", ""),
        "ambient_file": input_data.get("ambient_file", ""),
        "output": output,
        "fps": int(input_data.get("fps", 30)),
        "width": int(input_data.get("width", 1080)),
        "height": int(input_data.get("height", 1920)),
    }

    spec_path = f"{VIDEO_OUTPUT_DIR}/spec_video_{int(time.time())}.json"
    with open(spec_path, "w") as f:
        json.dump(spec, f)

    if engine == "remotion":
        result = subprocess.run(
            ["python3", PIPELINE_REMOTION, spec_path],
            timeout=300
        )
    elif engine == "wan2gp":
        # Wan2GP handles one scene at a time
        for scene in scenes:
            wan_spec = {
                "image_path": scene.get("image", ""),
                "prompt": scene.get("text", ""),
                "output": scene.get("image", "").replace(".png", "_anim.mp4"),
                "resolution": "832x480",
                "video_length": 81,
                "num_inference_steps": 30,
                "flow_shift": 7.0,
                "motion_amplitude": 1.0,
            }
            wan_spec_path = spec_path.replace(".json", f"_wan.json")
            with open(wan_spec_path, "w") as f:
                json.dump(wan_spec, f)
            subprocess.run([WAN2GP_PYTHON, PIPELINE_WAN2GP, wan_spec_path], timeout=2400)
        result = type("R", (), {"returncode": 0})()
    else:
        print(f"[ZAYA] Unknown video engine: {engine}")
        return

    try:
        os.remove(spec_path)
    except Exception:
        pass

    if result.returncode == 0 and os.path.exists(output):
        print(f"[VIDEO GENERATED] {output}")
    else:
        print(f"[VIDEO ERROR] engine {engine} failed")

# ─────────────────────────────────────────────
# DISPATCH
# ─────────────────────────────────────────────
def dispatch(contract):
    t = contract.get("type", "").lower()
    if "image" in t:
        handle_image(contract)
        return
    if "video" in t:
        handle_video(contract)
        return
    if "animation" in t:
        handle_animation(contract)
        return
    if "ken_burns" in t or "kenburns" in t:
        handle_kenburns(contract)
        return
    print("[ZAYA] Unknown contract:", t)

# ─────────────────────────────────────────────
# CLEANUP GPU
# ─────────────────────────────────────────────
def post_image_cleanup():
    subprocess.run([
        "python3",
        "/opt/zaya_os/hub/kernel/zaya_gpu_manager_v1.py",
        "prepare_pipeline"
    ])

# ─────────────────────────────────────────────
# CHAT CORE
# ─────────────────────────────────────────────
def chat(user_input, history):
    system = load_system_prompt()
    messages = [{"role": "system", "content": system}]
    messages += history[-6:]
    messages.append({"role": "user", "content": user_input + " /no_think"})
    payload = {
        "model": "Qwen3-14B-Q4_K_M.gguf",
        "messages": messages,
        "max_tokens": 1200,
        "temperature": 0.3,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False}
    }
    try:
        r = requests.post(LLM_URL, json=payload, timeout=1200)
        r.raise_for_status()
        data = r.json()
        if "choices" not in data:
            print("[LLM ERROR] invalid response:", data)
            return ""
        msg = data["choices"][0]["message"]
        raw = msg.get("content") or msg.get("reasoning_content", "")
    except Exception as e:
        print("[LLM ERROR]", e)
        return ""

    raw = raw.strip()
    contract = extract_contract(raw)
    if contract:
        dispatch(contract)
        log_turn(user_input, raw, contract)
        return raw
    return raw

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    history = []
    print(
        "╔══════════════════════════════════════╗\n"
        "║       ZAYA OS  --  CHAT v4           ║\n"
        "║  Semantic contracts + Auto Pipeline  ║\n"
        "╚══════════════════════════════════════╝\n"
        "  'exit' to quit | 'clear' to reset\n"
    )
    while True:
        try:
            user = input("Mike: ").strip()
            if not user:
                continue
            if user.lower() in ["exit", "quit"]:
                print("Goodbye!")
                break
            if user.lower() == "clear":
                history = []
                print("[ZAYA] context cleared")
                continue
            reply = chat(user, history)
            if reply and "<CONTRACT>" not in reply:
                print(f"\nZaya: {reply}\n")
            history.append({"role": "Mike", "content": user})
            history.append({"role": "assistant", "content": reply})
            if len(history) > 20:
                history = history[-20:]
        except KeyboardInterrupt:
            print("\n[ZAYA] interrupted")
            break
        except Exception as e:
            print("[ZAYA ERROR]", e)

if __name__ == "__main__":
    main()
