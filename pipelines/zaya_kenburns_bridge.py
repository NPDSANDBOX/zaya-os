#!/usr/bin/env python3
"""
Bridge: zaya_chat → Ken Burns animation
Triggered by <KEN_BURNS> tag in Zaya response

Padrão idêntico ao zaya_blender_bridge.py existente.

Uso direto:
    python3 zaya_kenburns_bridge.py /caminho/imagem.png [preset] [frames] [fps]

Uso via tag (chamado pelo chat da Zaya):
    <KEN_BURNS image="/opt/zaya_os/output/xyz/image.png" preset="auto" frames="450" fps="30">
"""

import subprocess
import json
import os
import datetime
import uuid
import shutil
from pathlib import Path

# ─────────────────────────────────────────────
# CONFIG — alinhado com o padrão da Zaya
# ─────────────────────────────────────────────
BLENDER       = "/usr/local/bin/blender"
MOTION_SCRIPT = "/opt/zaya_os/motion/scripts/blender_render.py"
ANALYZE_SCRIPT= "/opt/zaya_os/motion/scripts/analyze_image.py"
MOTION_INPUT  = "/opt/zaya_os/motion/input"
MOTION_OUTPUT = "/opt/zaya_os/motion/output"
MOTION_FRAMES = "/opt/zaya_os/motion/frames"

OUTPUT_BASE   = "/opt/zaya_os/hub/io/output/kenburns"
JOBS_LOG      = "/opt/zaya_os/hub/data/jobs/kenburns_jobs.jsonl"

PYTHON_BIN    = "/usr/bin/python3"


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def _ensure_log_dir():
    Path(JOBS_LOG).parent.mkdir(parents=True, exist_ok=True)


def _log_job(entry: dict):
    _ensure_log_dir()
    with open(JOBS_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


# ─────────────────────────────────────────────
# RENDER
# ─────────────────────────────────────────────
def render(image_path: str, preset: str = "auto", frames: int = 450,
           fps: int = 30, extra: dict = None) -> dict:
    """
    Anima uma imagem com Ken Burns e retorna dict com resultado.

    Args:
        image_path: caminho absoluto da imagem de entrada
        preset:     auto | center_push | low_angle_dolly | reveal_vertical |
                    pan_follow | diagonal_drift | pull_out
        frames:     número de frames (450 = 15s a 30fps)
        fps:        frames por segundo
        extra:      dados adicionais para o spec (opcional)

    Returns:
        dict com ok, job_id, video, gif, dir
    """
    image_path = os.path.abspath(image_path)

    if not os.path.exists(image_path):
        return {"ok": False, "error": f"imagem nao encontrada: {image_path}"}

    if not os.path.exists(BLENDER):
        return {"ok": False, "error": f"blender nao encontrado em: {BLENDER}"}

    # ── job identity ──────────────────────────
    stamp  = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
    job_id = f"kenburns_{stamp}_{uuid.uuid4().hex[:6]}"
    out_dir = os.path.join(OUTPUT_BASE, job_id)
    os.makedirs(out_dir, exist_ok=True)

    print(f"\n[KEN_BURNS] Starting job: {job_id}")
    print(f"[KEN_BURNS] Image:  {image_path}")
    print(f"[KEN_BURNS] Preset: {preset} | Frames: {frames} | FPS: {fps}")
    print(f"[KEN_BURNS] Output: {out_dir}")

    # ── spec ──────────────────────────────────
    spec = {
        "job_id":     job_id,
        "image_path": image_path,
        "preset":     preset,
        "frames":     frames,
        "fps":        fps,
    }
    if extra:
        spec.update(extra)

    spec_path = os.path.join(out_dir, "spec.json")
    with open(spec_path, "w", encoding="utf-8") as f:
        json.dump(spec, f, indent=2)

    # ── step 1: copiar imagem para motion/input ──
    dest_image = os.path.join(MOTION_INPUT, "image.png")
    os.makedirs(MOTION_INPUT, exist_ok=True)
    if os.path.abspath(image_path) != os.path.abspath(dest_image):
        if os.path.realpath(image_path) != os.path.realpath(dest_image):
                shutil.copy2(image_path, dest_image)
    print(f"[KEN_BURNS] Imagem copiada para {dest_image}")

    # ── step 2: analyze_image ────────────────
    print(f"[KEN_BURNS] Analisando imagem...")
    r_analyze = subprocess.run(
        [PYTHON_BIN, ANALYZE_SCRIPT],
        capture_output=True, text=True, timeout=60
    )
    if r_analyze.returncode != 0:
        err = r_analyze.stderr[-300:]
        print(f"[KEN_BURNS] WARN analyze falhou: {err}")
        # não fatal — blender_render.py tem fallback interno

    analysis_path = os.path.join(MOTION_INPUT, "analysis.json")
    analysis = {}
    if os.path.exists(analysis_path):
        with open(analysis_path, "r", encoding="utf-8") as f:
            analysis = json.load(f)
        strategy = analysis.get("camera_strategy", "")
        print(f"[KEN_BURNS] Strategy: {strategy}")
        if preset == "auto":
            strategy_map = {
                "center_lock_slow_push":  "center_push",
                "low_angle_push":         "low_angle_dolly",
                "vertical_reveal":        "reveal_vertical",
                "pan_horizontal":         "pan_follow",
                "diagonal_drift":         "diagonal_drift",
                "pull_back":              "pull_out",
            }
            preset = strategy_map.get(strategy, "center_push")
            print(f"[KEN_BURNS] Preset resolvido: {preset}")

    # ── step 3: limpar frames antigos ────────
    frames_dir = Path(MOTION_FRAMES)
    frames_dir.mkdir(parents=True, exist_ok=True)
    for old in frames_dir.glob("frame_*.png"):
        old.unlink()

    # ── step 4: blender render ────────────────
    print(f"[KEN_BURNS] Iniciando Blender...")
    cmd = [
        BLENDER, "-b", "-P", MOTION_SCRIPT,
        "--",
        "--frames", str(frames),
        "--fps",    str(fps),
        "--preset", preset,
        "--label",  job_id,
    ]

    log_stdout = os.path.join(out_dir, "blender_stdout.log")
    log_stderr = os.path.join(out_dir, "blender_stderr.log")

    with open(log_stdout, "w") as fout, open(log_stderr, "w") as ferr:
        r_blender = subprocess.run(
            cmd, stdout=fout, stderr=ferr, timeout=3600
        )

    if r_blender.returncode != 0:
        with open(log_stderr) as f:
            err_tail = f.read()[-500:]
        print(f"[KEN_BURNS] ❌ Blender falhou:\n{err_tail}")
        entry = {
            "job_id": job_id, "timestamp": stamp, "spec": spec,
            "ok": False, "error": err_tail
        }
        _log_job(entry)
        return {"ok": False, "job_id": job_id, "error": err_tail}

    # contar frames gerados
    n_frames = len(list(frames_dir.glob("frame_*.png")))
    print(f"[KEN_BURNS] {n_frames} frames gerados")

    # ── step 5: ffmpeg → mp4 ─────────────────
    video_path = os.path.join(out_dir, "kenburns.mp4")
    print(f"[KEN_BURNS] Compondo MP4...")
    r_mp4 = subprocess.run([
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", os.path.join(MOTION_FRAMES, "frame_%03d.png"),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        video_path
    ], capture_output=True, text=True, timeout=300)

    if r_mp4.returncode != 0:
        print(f"[KEN_BURNS] ❌ ffmpeg mp4 falhou: {r_mp4.stderr[-200:]}")
        _log_job({"job_id": job_id, "timestamp": stamp, "spec": spec,
                  "ok": False, "error": r_mp4.stderr[-200:]})
        return {"ok": False, "job_id": job_id, "error": r_mp4.stderr[-200:]}

    # ── step 6: ffmpeg → gif ─────────────────
    gif_path = os.path.join(out_dir, "kenburns.gif")
    print(f"[KEN_BURNS] Compondo GIF...")
    subprocess.run([
        "ffmpeg", "-y", "-i", video_path, gif_path
    ], capture_output=True, timeout=300)

    # ── step 7: copiar também para motion/output (compatibilidade) ──
    shutil.copy2(video_path, os.path.join(MOTION_OUTPUT, "animation.mp4"))
    shutil.copy2(gif_path,   os.path.join(MOTION_OUTPUT, "animation.gif"))

    # ── step 8: summary ──────────────────────
    summary = {
        "job_id":       job_id,
        "status":       "success",
        "image_input":  image_path,
        "preset":       preset,
        "frames":       n_frames,
        "fps":          fps,
        "analysis":     analysis,
        "artifacts": {
            "video": video_path,
            "gif":   gif_path,
        }
    }
    summary_path = os.path.join(out_dir, "summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    # ── log ──────────────────────────────────
    _log_job({
        "job_id":    job_id,
        "timestamp": stamp,
        "spec":      spec,
        "ok":        True,
        "frames":    n_frames,
        "video":     video_path,
        "gif":       gif_path,
    })

    print(f"[KEN_BURNS] ✅ Concluído!")
    print(f"[KEN_BURNS] Video: {video_path}")
    print(f"[KEN_BURNS] GIF:   {gif_path}")

    return {
        "ok":     True,
        "job_id": job_id,
        "video":  video_path,
        "gif":    gif_path,
        "dir":    out_dir,
        "summary": summary,
    }


# ─────────────────────────────────────────────
# ENTRY POINT DIRETO
# ─────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Uso: python3 zaya_kenburns_bridge.py <image_path> [preset] [frames] [fps]")
        print("Presets: auto center_push low_angle_dolly reveal_vertical pan_follow diagonal_drift pull_out")
        sys.exit(1)

    image  = sys.argv[1]
    preset = sys.argv[2] if len(sys.argv) > 2 else "auto"
    frames = int(sys.argv[3]) if len(sys.argv) > 3 else 450
    fps    = int(sys.argv[4]) if len(sys.argv) > 4 else 30

    result = render(image, preset, frames, fps)
    sys.exit(0 if result["ok"] else 1)
