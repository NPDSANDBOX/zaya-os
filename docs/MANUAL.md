# Zaya OS — Technical Manual

A local AI operating system for autonomous content production.
No cloud dependencies. No API costs. Single-GPU optimized.

Created by Mike Henri — Tokyo, Japan — April 2026.

---

## Table of Contents

1. [System Rules](#system-rules)
2. [Runtime Architecture](#runtime-architecture)
3. [Capabilities Registry](#capabilities-registry)
4. [Models & Pipelines](#models--pipelines)
5. [Compute Router](#compute-router)
6. [Learning System](#learning-system)
7. [Image Pipeline](#image-pipeline)
8. [Video Engines](#video-engines)
9. [Remotion Pipeline](#remotion-pipeline)
10. [Content Production Pipeline](#content-production-pipeline)
11. [Configuration & Tuning](#configuration--tuning)

---

## System Rules

### 1. Never use /tmp
All temporary files go to `/opt/zaya_os/hub/data/contracts/`. Logs go to `/opt/zaya_os/hub/core/logs/`. Intermediate renders go to `/opt/zaya_os/hub/data/jobs/work/`.

### 2. Never use silent fallbacks
Every error must be captured, logged, and returned clearly. No silent catch blocks.

### 3. Contract-first execution
Every action requires a contract before execution. Evidence before capability promotion (3+ successful validations and >= 0.8 confidence).

### 4. Conservative delegation
The delegation guard halts execution at high severity (>= 0.90) rather than proceeding unsafely.

---

## Runtime Architecture

### Services

| Service | Type | Description |
|---------|------|-------------|
| Runtime Loop v4 | Bash daemon | Priority scheduler: high → normal → low queues |
| Heartbeat Daemon | systemd user service | 60s interval, updates self_model |
| LLM Server | llama.cpp | Port 8080, any GGUF model (tested with Qwen3-14B-Q4_K_M) |
| ComfyUI | Diffusion server | Port 8188, GPU-accelerated |

### Runtime Loop v4

Located at `/opt/zaya_os/hub/tools/runtime_loop_v4.sh`:
- Reads priority queues: `data/jobs/high/` → `data/jobs/normal/` → `data/jobs/low/`
- Moves job to `data/jobs/queue/`, dispatches `runtime_worker_v2.sh`
- Max 2 concurrent workers
- Started via `start_runtime_loop_v1.sh`

### Heartbeat Daemon

- Runs `zaya_heartbeat_daemon.sh` every 60 seconds
- Updates `worker_heartbeat.json` timestamp
- Runs `self_model_updater_v2.py` to sync self_model with real system state
- Enabled at boot via systemd user service

---

## Capabilities Registry

### Active Capabilities

| Capability | Engine | Description |
|-----------|--------|-------------|
| `voice.say` | Piper TTS (multi-language) | Text-to-speech with configurable voices |
| `voice.say_with_subtitles` | Piper TTS + Whisper STT | Audio + synchronized subtitles |
| `image.generate` | Flux1 / Juggernaut v3 / SDXL | Multi-pipeline image generation with quality routing |
| `video.render_from_images` | ffmpeg | Image sequence to video |
| `video.render_blender` | Blender headless | 3D scene rendering |
| `episode.produce` | Full pipeline v5 | End-to-end content production |
| `code.write` | Local LLM | Code generation with test → fix cycle |

### Episode Pipeline v5

```
Text extraction (.docx/.odt/.txt/.md/.pdf)
    → Scene extraction (LLM via localhost:8080)
    → Prompt building (configurable palette + style)
    → Image generation (Flux1 ultra, fallback Juggernaut hq)
    → Audio + subtitles (Piper TTS + Whisper per scene)
    → Animation: Wan2.1 I2V → SVD → Ken Burns fallback
    → FFmpeg assembly (per-scene clips with burned subtitles → concatenate)
```

### Code Write Capability

- Uses local LLM at localhost:8080
- Cycle: LLM generates code → writes file → runs test_command → if fail: LLM reads error + code → generates fix → retests (up to max_retries)
- Timeout: 300s per LLM call
- Spec files stored in `/opt/zaya_os/hub/data/contracts/`

---

## Models & Pipelines

### Image Pipelines

Located at `/opt/zaya_os/hub/capabilities/pipelines/`:

| Pipeline | Model | Resolution | Time/frame |
|----------|-------|-----------|------------|
| `pipeline_flux1.py` | Flux.1 Dev + IP-Adapter + LoRA | 1152x1536 | ~225s |
| `pipeline_juggernaut_v3.py` | Juggernaut XL v9 + LoRA | 1152x1536 | ~90s |
| `pipeline_svd.py` | Stable Video Diffusion | 1024x576, 25 frames | ~327s |
| `pipeline_svd_cinematic.py` | SVD multi-clip | Configurable | Variable |
| `pipeline_wan2gp_v1.py` | Wan2.1 I2V 14B (INT8) | 832x480, 81 frames | ~29min |
| `pipeline_cogvideox.py` | CogVideoX-5B I2V | Configurable | Tested OK |
| `pipeline_hunyuan_i2v.py` | Hunyuan 1.5 I2V Distilled | Configurable | Needs VL model |
| `pipeline_remotion.py` | Remotion + React | 1080x1920 | Seconds |
| `pipeline_book_to_video.py` | Multi-engine | Full pipeline | Variable |
| `pipeline_feedback_loop_v1.py` | Any image pipeline | Iterative refinement | Variable |

### Blender Pipelines

| Pipeline | Description |
|----------|-------------|
| `blender_futuristic_city.py` | Procedural cyberpunk city with EEVEE |
| `blender_city_realistic.py` | Realistic city with MPFB humans |

### Utility Pipelines

| Pipeline | Description |
|----------|-------------|
| `precision_engine.py` | Fine-grained parameter control |
| `flipbook_assembler.py` | Image sequence assembly |
| `zaya_kenburns_bridge.py` | Ken Burns effect (zoom/pan) via ffmpeg |

### Model Locations

| Model | Path |
|-------|------|
| LLM (GGUF) | `/opt/zaya_os/models/llm/` |
| Flux Dev | `/opt/ComfyUI/models/checkpoints/flux-dev/` |
| SVD | `/opt/zaya_os/hub/models/sd/svd/` |
| Wan2.1 I2V 14B | `/opt/zaya_os/tools/Wan2GP/ckpts/` |
| CogVideoX-5B | `/opt/zaya_os/hub/models/cogvideox-5b-i2v/` |
| Juggernaut XL | Via ComfyUI models |
| IP-Adapter | `/opt/ComfyUI/models/ipadapter/` |
| Piper voices | `/opt/zaya_os/hub/voices/` |
| Custom LoRAs | `/opt/zaya_os/hub/models/loras/` |

---

## Compute Router

Resource-aware compute scheduling for single-GPU systems. Invented by Mike Henri.

**Location:** `/opt/zaya_os/hub/kernel/zaya_compute_router.py`

### How It Works

| Task Type | Mode | VRAM Usage |
|-----------|------|------------|
| Simple LLM tasks | CPU mode | Zero VRAM (LLM runs on system RAM) |
| Complex LLM tasks | GPU mode | ~8GB VRAM |
| Render tasks (Blender, ComfyUI, Flux, Wan2.1) | Render mode | Stops LLM, frees ALL VRAM |
| Post-render | CPU restore | LLM returns in CPU mode |

### Why It's Unique

Traditional approaches either overload the GPU (OOM), underuse the GPU (CPU-only), or require multiple GPUs. This router treats VRAM as a dynamically allocated shared resource on a single consumer GPU. Any developer with limited hardware can use this.

Integrated into the Zaya AI Control Loop — automatic routing per task type.

---

## Learning System

### Phase 1 — Evaluate + Learn

| Module | Purpose |
|--------|---------|
| `image_evaluator_v1.py` | Scores images against configurable criteria (color palette, atmosphere, composition, camera angle) |
| `learning_memory_v1.py` | Records prompt → score relationships, queries best prompts, suggests improvements |
| `pipeline_feedback_loop_v1.py` | Generate → evaluate → correct → regenerate loop (max 3 attempts) |

### Phase 2 — RAG + Catalog

| Module | Purpose |
|--------|---------|
| `universe_rag_v1.py` | TF-IDF indexer, cosine similarity search over document chunks |
| `image_catalog_v1.py` | Image cataloging with visual metadata, similarity search, deduplication |

Chat and Prompt Builder use RAG for relevant context injection (not full document dumps).

### Phase 3 — Autonomous Agent

| Module | Purpose |
|--------|---------|
| `zaya_agent_v1.py` | Plan → Execute → Evaluate → Reflect → Correct loop with LLM reasoning |
| `episode_producer_v1.py` | Full episode production: text → scenes → prompts → images (with RAG + learning) |

State persistence to `agent_state.json` — fully resumable.

---

## Image Pipeline

### Direct Spec Flow

```
User → LLM → CONTRACT (direct spec JSON) → handle_image() → pipeline
```

No intermediary interpretation layers. The LLM outputs a direct specification that goes straight to the rendering pipeline.

### IP-Adapter Integration (Native Diffusers)

- IP-Adapter via diffusers native `load_ip_adapter()` API
- Uses `ip_adapter_image_embeds` for cross-attention injection
- InsightFace buffalo_l extracts 512-dim face embedding from reference image
- `faceid_scale` configurable per spec (default 0.6, recommended 0.35 for full body shots)
- IP-Adapter loaded before `enable_attention_slicing()` (incompatible processors)
- Unloaded before budget passes to avoid face interference with environment refinement

### Pipeline Strength Tuning

| Pass | Strength | Purpose |
|------|----------|---------|
| Pass 1 | 1.0 (txt2img) | Establishes composition — this is the base |
| Pass 2 | 0.35 | Lighting refinement |
| Pass 3 | 0.25 | Fine detail — never rewrite |
| Pass 4+ | 0.20 | Minimal finishing |
| Character pass | 0.35 | Identity refinement |

**Rule:** Pass 1 establishes composition — subsequent passes refine, never rewrite.

### Token Budget Planner

- Force-to-pass-1 keywords: `skull, entity, dimensional, materializing, enormous, giant, colossal, monumental`
- Terms with these keywords always go to pass 1 (never deferred to later passes)
- Ensures narrative-critical scene elements appear in the base composition

---

## Video Engines

### Engine Comparison

| Engine | Model | VRAM | Speed | Specialty |
|--------|-------|------|-------|-----------|
| Wan2.1 I2V 14B | wan2.1_image2video_480p_14B | ~12GB | ~57s/step | Semantic movement (eyes, hands, water) |
| CogVideoX-5B | Diffusers native | ~12GB | Tested OK | Quality comparable to Runway Gen4-Turbo |
| Hunyuan 1.5 I2V | Distilled model | ~12GB | TBD | Avatar, audio, edit modes |
| SVD | pipeline_svd.py | ~8GB | ~30s/clip | Camera motion, parallax |
| Remotion | React-based | CPU | Seconds | 2D/3D animation, Ken Burns, particles |

### Wan2GP Configuration

- **Location:** `/opt/zaya_os/tools/Wan2GP/`
- **Launch:** `python3 wgp.py --i2v-14B --server-port 7860 --listen`
- **Resolution:** 832x480 (sweet spot for 12GB VRAM)
- **Motion amplitude:** 1.0 recommended (1.5 causes deformation)
- **Flow shift:** 7.0 for faithful to source, 5.0 for more creative freedom
- **Output:** ~5s clips at 16fps (81 frames), slowmo via ffmpeg to match audio duration
- **Capabilities:** I2V, T2V, lip-sync, voice clone, face swap, motion transfer, VACE editing, music generation

### SVD Notes

- Suitable for environment animation only (no semantic understanding of characters)
- Multi-clip mode available via `pipeline_svd_cinematic.py` (half-cut, interpolation, crossfade)

---

## Remotion Pipeline

React-based programmatic video rendering. Renders in seconds, not hours.

### Location

- Project: `/opt/zaya_os/tools/quantum-video/`
- Pipeline: `/opt/zaya_os/hub/capabilities/pipelines/pipeline_remotion.py`

### Stack

- Remotion (core video framework)
- framer-motion (React animations)
- @emotion/react + @emotion/styled (CSS-in-JS)
- @remotion/three (3D via Three.js)
- @remotion/lottie (2D animated vectors)
- @react-three/fiber + @react-three/drei (React Three.js helpers)

### Available Effects

- **Ken Burns:** zoom_in, zoom_out, pan_left, pan_right, pan_up, parallax, pulse
- **Particles:** golden particles floating upward
- **Overlays:** pulsing golden glow, breathing light rays, cinematic vignette
- **Text:** word-by-word animation with glow effects
- **Transitions:** fade in/out between scenes
- **3D:** character animation (walk, run, idle via Mixamo models)

### Performance

| Duration | Render Time |
|----------|------------|
| 10s video | ~10 seconds |
| 40s video | ~35 seconds |

Compare: Wan2GP takes ~29 minutes for a 5s clip.

**Decision:** Remotion replaces Ken Burns for fast production. Use Wan2GP only when semantic AI animation is critical (eyes opening, water flowing, breathing).

---

## Content Production Pipeline

### Full Production Flow

```
1. Script    → Local LLM (localhost:8080) — scene breakdown
2. Audio     → Piper TTS (configurable voice/language)
3. Images    → Flux1 or Juggernaut v3 (configurable style)
4. Animation → Wan2GP I2V / Remotion / SVD / Ken Burns
5. Assembly  → ffmpeg (clips + audio + burned-in subtitles)
6. Output    → Ready for distribution
```

### Subtitle Configuration

- Format: SRT, burned-in with ffmpeg
- Font: Arial, size 11, white with thin black outline, transparent background
- Position: bottom center, MarginV=60

### Audio Mixing Rules

- Ambient audio must match Piper output: 22050Hz mono
- Ambient volume: 50% minimum relative to narration
- Always verify sample rate before mixing

---

## Configuration & Tuning

### LLM Server

- Context size: 8192 tokens (CPU mode), 32768 tokens (GPU mode)
- 8192 is sufficient for system prompt + conversation history in most cases

### LoRA Training

Zaya OS supports custom LoRA training for consistent character/style generation.

- Training data location: `/opt/zaya_os/hub/data/lora_training/`
- LoRA output: `/opt/zaya_os/hub/models/loras/`
- Recommended: ~1000+ curated images for style LoRAs

### Virtual Environments

The system uses isolated Python virtual environments per module:

```
/opt/zaya_os/venvs/
├── ai/            — General AI tools
├── kohya/         — LoRA training (Kohya SS)
├── piper/         — Text-to-speech
├── wav2lip/       — Lip sync
├── whisper/       — Speech-to-text
├── zaya_diffusion/ — Image generation
└── wan2gp/        — Wan2.1 video generation
```

### Hardware Tested

- GPU: NVIDIA RTX 3080 Ti (12GB VRAM)
- RAM: 64GB
- OS: Ubuntu Linux

### Backup Strategy

- SSD backups: `/opt/zaya_os/backups/`
- HDD backups: External drive mount point
- Recommended: full backup before major changes, incremental for daily work

---

## Session Observer

Captures runtime activity for learning and debugging.

**Location:** `/opt/zaya_os/hub/kernel/zaya_session_observer.py`

- Captures executions, errors, fixes, decisions, capabilities
- Extracts learnings to `/opt/zaya_os/hub/learning/inbox/`
- Updates cognitive memory automatically
- CLI: `start`, `log-exec`, `log-error`, `log-capability`, `log-decision`, `close`, `summary`

---

## Claude Code Integration

### Skills Available

| Skill | Description |
|-------|-------------|
| `/render-wan21` | Animate image with Wan2.1 I2V |
| `/render-blender` | 3D scene generation |
| `/render-camera` | 39 cinematic camera movements |
| `/gpu-status` | System health check |
| `/session` | Session Observer management |

### Camera Movements (39 total)

Includes standard movements (dolly, pan, tilt, zoom) plus custom signature movements (teleport arrive, portal pulse, data storm, etc.).

---

## License

MIT License. See [LICENSE](../LICENSE) for details.
