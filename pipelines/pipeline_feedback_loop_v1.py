#!/usr/bin/env python3
"""
ZAYA PIPELINE — FEEDBACK LOOP v1
Automatic generate → evaluate → correct → regenerate loop.

Accepts a spec JSON, generates an image via the appropriate pipeline,
evaluates it, applies prompt corrections based on evaluator feedback,
and retries until min_score is met or max_attempts exhausted.

All attempts are recorded to learning memory for continuous improvement.

Usage:
    python3 pipeline_feedback_loop_v1.py <spec.json>
"""
import sys
import json
import os
import time
import subprocess
import copy

# ── CONSTANTS ────────────────────────────────────────────────────────

PIPELINES = {
    "ultra": "/opt/zaya_os/hub/capabilities/pipelines/pipeline_flux1.py",
    "hq":    "/opt/zaya_os/hub/capabilities/pipelines/pipeline_juggernaut_v3.py",
    "fast":  "/opt/zaya_os/hub/capabilities/pipelines/pipeline_sdxl.py",
}

EVALUATOR = "/opt/zaya_os/hub/capabilities/image_evaluator_v1.py"

CONTRACTS_DIR = "/opt/zaya_os/hub/data/contracts"

# Canonical color terms from the Zaya Universe style environment
CANONICAL_COLORS = (
    "intense gold as sacred force, "
    "pearlescent white as primary light source in darkness, "
    "specular highlights on wet surfaces, cold iridescent shimmer, "
    "deep crimson in fabrics and emotional markers, "
    "matte black as dominant base, obsidian surfaces, "
    "neon teal as technological glow and interface light, "
    "pale violet as ambient haze and atmospheric depth"
)

# ── CORRECTION MAP ───────────────────────────────────────────────────
# Each key is a substring matched against evaluator issues (case-insensitive).
# Value is a dict with "target" (prompt or character) and "prefix"/"suffix" text.

CORRECTION_RULES = [
    {
        "match": "too bright",
        "target": "prompt",
        "prefix": "dark cinematic atmosphere, deep shadows, ",
    },
    {
        "match": "no red hair",
        "target": "character",
        "suffix": ", intense deep red hair clearly visible",
    },
    {
        "match": "red hair not detected",
        "target": "character",
        "suffix": ", intense deep red hair clearly visible",
    },
    {
        "match": "colors off-canon",
        "target": "prompt",
        "suffix": f", {CANONICAL_COLORS}",
    },
    {
        "match": "off-canon",
        "target": "prompt",
        "suffix": f", {CANONICAL_COLORS}",
    },
    {
        "match": "low contrast",
        "target": "prompt",
        "suffix": ", high contrast, dramatic directional lighting",
    },
    {
        "match": "flat lighting",
        "target": "prompt",
        "suffix": ", high contrast, dramatic directional lighting",
    },
    {
        "match": "blurry",
        "target": "prompt",
        "suffix": ", sharp focus, ultra detailed, crisp edges",
    },
    {
        "match": "overexposed",
        "target": "prompt",
        "prefix": "moody underexposed cinematic lighting, ",
    },
    {
        "match": "underexposed",
        "target": "prompt",
        "prefix": "well-lit scene, balanced exposure, ",
    },
    {
        "match": "wrong pose",
        "target": "character",
        "suffix": ", natural relaxed pose, anatomically correct",
    },
    {
        "match": "deformed",
        "target": "character",
        "suffix": ", anatomically correct, well-proportioned",
    },
]


def log(msg):
    print(f"[FEEDBACK-LOOP] {msg}", flush=True)


def ensure_dir(path):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)


def write_temp_spec(spec, attempt):
    """Write a temporary spec JSON for the sub-pipeline to consume."""
    os.makedirs(CONTRACTS_DIR, exist_ok=True)
    ts = int(time.time() * 1000)
    path = os.path.join(CONTRACTS_DIR, f"feedback_loop_spec_{ts}_attempt{attempt}.json")
    with open(path, "w") as f:
        json.dump(spec, f, indent=2)
    return path


def run_pipeline(pipeline_path, spec_path):
    """Run a generation pipeline via subprocess. Returns (ok, stdout, stderr)."""
    log(f"Running pipeline: {os.path.basename(pipeline_path)}")
    result = subprocess.run(
        ["python3", pipeline_path, spec_path],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        log(f"Pipeline FAILED (rc={result.returncode})")
        if result.stderr:
            log(f"stderr: {result.stderr[-500:]}")
        return False, result.stdout, result.stderr
    log("Pipeline completed successfully")
    return True, result.stdout, result.stderr


def run_evaluator(image_path, prompt, prompt_character="", zaya_in_scene=False):
    """
    Run the image evaluator via subprocess.
    Expected evaluator output: JSON with {"score": float, "issues": [...], "suggestions": [...]}
    """
    if not os.path.exists(EVALUATOR):
        log(f"WARNING: Evaluator not found at {EVALUATOR} — returning default score 0.5")
        return {
            "score": 0.5,
            "issues": ["evaluator_not_available"],
            "suggestions": [],
        }

    eval_spec = {
        "image": image_path,
        "prompt": prompt,
        "prompt_character": prompt_character,
        "zaya_in_scene": zaya_in_scene,
    }
    os.makedirs(CONTRACTS_DIR, exist_ok=True)
    ts = int(time.time() * 1000)
    eval_spec_path = os.path.join(CONTRACTS_DIR, f"feedback_eval_spec_{ts}.json")
    with open(eval_spec_path, "w") as f:
        json.dump(eval_spec, f, indent=2)

    try:
        result = subprocess.run(
            ["python3", EVALUATOR, eval_spec_path],
            capture_output=True,
            text=True,
            timeout=120,
        )
        # Try to parse JSON from stdout (last line or full output)
        stdout = result.stdout.strip()
        # Find JSON in output — evaluator may print logs before JSON
        for line in reversed(stdout.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        # Try full output
        try:
            return json.loads(stdout)
        except json.JSONDecodeError:
            log(f"WARNING: Could not parse evaluator output — returning default")
            return {"score": 0.5, "issues": ["evaluator_parse_error"], "suggestions": []}
    except subprocess.TimeoutExpired:
        log("WARNING: Evaluator timed out")
        return {"score": 0.5, "issues": ["evaluator_timeout"], "suggestions": []}
    except Exception as e:
        log(f"WARNING: Evaluator error: {e}")
        return {"score": 0.5, "issues": [f"evaluator_error: {e}"], "suggestions": []}
    finally:
        # Clean up eval spec
        try:
            os.remove(eval_spec_path)
        except OSError:
            pass


def apply_corrections(prompt, prompt_character, issues, suggestions):
    """
    Apply cumulative corrections to prompts based on evaluator issues.
    Returns (corrected_prompt, corrected_character, list_of_corrections_applied).
    """
    corrections_applied = []
    all_issue_text = " ".join(issues).lower()
    all_suggest_text = " ".join(suggestions).lower() if suggestions else ""
    combined_text = f"{all_issue_text} {all_suggest_text}"

    for rule in CORRECTION_RULES:
        if rule["match"] in combined_text:
            target = rule["target"]
            correction_desc = f"{rule['match']} → "

            if target == "prompt":
                prefix = rule.get("prefix", "")
                suffix = rule.get("suffix", "")
                if prefix and not prompt.startswith(prefix):
                    prompt = prefix + prompt
                    correction_desc += f"prepend to prompt"
                if suffix and suffix not in prompt:
                    prompt = prompt + suffix
                    correction_desc += f"append to prompt"
                corrections_applied.append(correction_desc)

            elif target == "character":
                prefix = rule.get("prefix", "")
                suffix = rule.get("suffix", "")
                if prefix and not prompt_character.startswith(prefix):
                    prompt_character = prefix + prompt_character
                    correction_desc += f"prepend to character"
                if suffix and suffix not in prompt_character:
                    prompt_character = prompt_character + suffix
                    correction_desc += f"append to character"
                corrections_applied.append(correction_desc)

    # Also incorporate any direct suggestions from evaluator that don't match rules
    # by appending them as general quality terms
    if not corrections_applied and suggestions:
        for s in suggestions[:2]:  # Limit to avoid prompt bloat
            if len(s) < 100:  # Only short, actionable suggestions
                prompt = prompt + f", {s}"
                corrections_applied.append(f"evaluator suggestion: {s}")

    return prompt, prompt_character, corrections_applied


def record_to_learning_memory(history, final_result):
    """Record all attempts to learning memory for future improvement."""
    try:
        sys.path.insert(0, "/opt/zaya_os/hub/capabilities")
        from learning_memory_v1 import record
        record({
            "type": "feedback_loop",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "ok": final_result["ok"],
            "attempts": final_result["attempts"],
            "final_score": final_result["final_score"],
            "history": history,
        })
        log("Recorded to learning memory")
    except ImportError:
        log("WARNING: learning_memory_v1 not available — writing to fallback log")
        fallback_path = "/opt/zaya_os/hub/data/contracts/feedback_loop_learning_log.jsonl"
        os.makedirs(os.path.dirname(fallback_path), exist_ok=True)
        with open(fallback_path, "a") as f:
            f.write(json.dumps({
                "type": "feedback_loop",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "ok": final_result["ok"],
                "attempts": final_result["attempts"],
                "final_score": final_result["final_score"],
                "history": history,
            }) + "\n")
        log(f"Fallback log written to {fallback_path}")
    except Exception as e:
        log(f"WARNING: Failed to record learning memory: {e}")


def run(spec_path):
    with open(spec_path) as f:
        spec = json.load(f)

    # ── Parse spec ───────────────────────────────────────────────
    original_prompt     = spec.get("prompt", "")
    original_character  = spec.get("prompt_character", "")
    negative            = spec.get("negative", "")
    output_path         = spec["output"]
    width               = spec.get("width", 1152)
    height              = spec.get("height", 1536)
    quality             = spec.get("quality", "hq")
    max_attempts        = spec.get("max_attempts", 3)
    min_score           = spec.get("min_score", 0.7)
    zaya_in_scene       = spec.get("zaya_in_scene", False)

    # Validate quality tier
    if quality not in PIPELINES:
        log(f"ERROR: Unknown quality '{quality}' — must be one of: {list(PIPELINES.keys())}")
        result = {"ok": False, "error": f"Unknown quality: {quality}", "attempts": 0,
                  "final_score": 0.0, "final_image": None, "history": []}
        print(json.dumps(result))
        return result

    pipeline_path = PIPELINES[quality]
    if not os.path.exists(pipeline_path):
        log(f"ERROR: Pipeline not found: {pipeline_path}")
        result = {"ok": False, "error": f"Pipeline not found: {pipeline_path}", "attempts": 0,
                  "final_score": 0.0, "final_image": None, "history": []}
        print(json.dumps(result))
        return result

    ensure_dir(output_path)

    log(f"Starting feedback loop: quality={quality}, max_attempts={max_attempts}, min_score={min_score}")
    log(f"Pipeline: {os.path.basename(pipeline_path)}")
    log(f"Output: {output_path}")

    # ── Main loop ────────────────────────────────────────────────
    current_prompt = original_prompt
    current_character = original_character
    history = []
    final_score = 0.0
    accepted = False
    base_seed = int(time.time())

    for attempt in range(1, max_attempts + 1):
        log(f"")
        log(f"{'='*60}")
        log(f"ATTEMPT {attempt}/{max_attempts}")
        log(f"{'='*60}")

        # Build per-attempt spec with different seed each time
        attempt_spec = {
            "prompt": current_prompt,
            "prompt_character": current_character,
            "negative": negative,
            "output": output_path,
            "width": width,
            "height": height,
            "seed": base_seed + (attempt - 1) * 1337,
        }

        # Copy through any extra keys the pipeline might need
        for key in ("steps", "guidance", "lora", "custom_faceid_ref", "custom_faceid_scale"):
            if key in spec:
                attempt_spec[key] = spec[key]

        # Write temp spec
        temp_spec_path = write_temp_spec(attempt_spec, attempt)

        try:
            # ── GENERATE ─────────────────────────────────────
            ok, stdout, stderr = run_pipeline(pipeline_path, temp_spec_path)
            if not ok:
                entry = {
                    "attempt": attempt,
                    "score": 0.0,
                    "issues": ["pipeline_failed"],
                    "corrections_applied": [],
                    "prompt_used": current_prompt,
                    "prompt_character_used": current_character,
                }
                history.append(entry)
                log(f"Attempt {attempt} FAILED — pipeline error")
                continue

            # Verify output exists
            if not os.path.exists(output_path):
                entry = {
                    "attempt": attempt,
                    "score": 0.0,
                    "issues": ["output_file_not_created"],
                    "corrections_applied": [],
                    "prompt_used": current_prompt,
                    "prompt_character_used": current_character,
                }
                history.append(entry)
                log(f"Attempt {attempt} FAILED — output file not created")
                continue

            # ── EVALUATE ─────────────────────────────────────
            log(f"Evaluating attempt {attempt}...")
            eval_result = run_evaluator(
                output_path, current_prompt, current_character, zaya_in_scene
            )
            score = eval_result.get("score", 0.0)
            issues = eval_result.get("issues", [])
            suggestions = eval_result.get("suggestions", [])

            log(f"Score: {score:.2f} (min: {min_score})")
            if issues:
                log(f"Issues: {issues}")

            entry = {
                "attempt": attempt,
                "score": score,
                "issues": issues,
                "prompt_used": current_prompt,
                "prompt_character_used": current_character,
            }

            if score >= min_score:
                # ── ACCEPT ───────────────────────────────────
                log(f"ACCEPTED at attempt {attempt} with score {score:.2f}")
                entry["corrections_applied"] = []
                history.append(entry)
                final_score = score
                accepted = True
                break
            else:
                # ── CORRECT ──────────────────────────────────
                log(f"Score {score:.2f} < {min_score} — applying corrections...")
                corrected_prompt, corrected_character, corrections = apply_corrections(
                    current_prompt, current_character, issues, suggestions
                )
                entry["corrections_applied"] = corrections

                if corrections:
                    for c in corrections:
                        log(f"  Correction: {c}")
                else:
                    log("  No matching corrections — will retry with different seed")

                history.append(entry)
                final_score = score

                # Update prompts for next attempt (cumulative)
                current_prompt = corrected_prompt
                current_character = corrected_character

        finally:
            # Clean up temp spec
            try:
                os.remove(temp_spec_path)
            except OSError:
                pass

    # ── Final report ─────────────────────────────────────────────
    if not accepted and final_score > 0:
        log(f"Max attempts reached. Best score: {final_score:.2f}")

    result = {
        "ok": accepted,
        "attempts": len(history),
        "final_score": final_score,
        "final_image": output_path if os.path.exists(output_path) else None,
        "history": history,
    }

    # ── Record to learning memory ────────────────────────────────
    record_to_learning_memory(history, result)

    # ── Auto-generate scene audio ────────────────────────────────
    audio_path = None
    if accepted and result["final_image"]:
        try:
            scene_spec = {
                "description": spec.get("prompt", ""),
                "scene_type": spec.get("scene_type", ""),
                "characters": spec.get("characters", []),
                "location": spec.get("location", ""),
                "time_of_day": spec.get("time_of_day", "night"),
                "mood": spec.get("mood", ""),
            }
            scene_spec_path = os.path.join(
                "/opt/zaya_os/hub/data/contracts",
                f"audio_scene_{int(time.time())}.json"
            )
            with open(scene_spec_path, "w") as f:
                json.dump(scene_spec, f)
            audio_path = result["final_image"].replace(".png", "_audio.wav").replace(".jpg", "_audio.wav")
            audio_cmd = [
                "python3", "/opt/zaya_os/hub/capabilities/sound_design_v1.py",
                "scene", scene_spec_path,
                "--output", audio_path,
                "--duration", "15"
            ]
            audio_result = subprocess.run(audio_cmd, capture_output=True, text=True, timeout=30)
            if audio_result.returncode == 0 and os.path.exists(audio_path):
                log(f"Scene audio generated: {audio_path}")
                result["audio"] = audio_path
            else:
                log(f"Audio generation skipped: {audio_result.stderr[:200] if audio_result.stderr else 'unknown'}")
        except Exception as e:
            log(f"Audio generation failed: {e}")

    # ── Output ───────────────────────────────────────────────────
    log("")
    log(f"{'='*60}")
    log(f"FEEDBACK LOOP COMPLETE")
    log(f"  OK: {result['ok']}")
    log(f"  Attempts: {result['attempts']}")
    log(f"  Final score: {result['final_score']:.2f}")
    log(f"  Final image: {result['final_image']}")
    if audio_path and os.path.exists(audio_path):
        log(f"  Scene audio: {audio_path}")
    log(f"{'='*60}")

    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({
            "ok": False,
            "error": "usage: pipeline_feedback_loop_v1.py <spec.json>"
        }))
        sys.exit(1)

    spec_path = sys.argv[1]
    if not os.path.exists(spec_path):
        print(json.dumps({
            "ok": False,
            "error": f"spec file not found: {spec_path}"
        }))
        sys.exit(1)

    result = run(spec_path)
    if not result["ok"]:
        sys.exit(1)
