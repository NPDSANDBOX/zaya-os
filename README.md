# ZAYA OS

> *The first open-source AI operating system that turns a single machine into a complete autonomous content studio — from text to cinematic video, with no cloud dependency, no per-use cost, and no creative limits.*

## What is ZAYA OS?

ZAYA OS is a modular, local-first AI operating system built for autonomous content production. It runs entirely on your own hardware — no cloud, no API costs, no limits.

A single machine becomes a complete studio:
- generates images
- animates them into cinematic video
- narrates with cloned voices
- assembles the final video automatically
- all orchestrated by a local LLM

## Why ZAYA OS?

| | Cloud AI Tools | ZAYA OS |
|---|---|---|
| Cost | Per minute / per image | Zero |
| Privacy | Your data on their servers | 100% local |
| Limits | Rate limits, quotas | Unlimited |
| Speed | Depends on internet | Your hardware |
| Control | Black box | Full control |

## Hardware Requirements

### Minimum
- **GPU:** 8GB VRAM (NVIDIA)
- **RAM:** 32GB
- **Storage:** 500GB SSD
- **OS:** Ubuntu 22.04 / 24.04

### Recommended
- **GPU:** 12GB VRAM (NVIDIA RTX 3080/4080)
- **RAM:** 64GB
- **Storage:** 1TB SSD + 1TB HDD
- **OS:** Ubuntu 24.04

### ZAYA OS Reference Build *(used in development)*
- **GPU:** NVIDIA 12GB VRAM
- **RAM:** 64GB
- **Storage:** 914GB SSD + 466GB HDD
- **OS:** Ubuntu 24.04
- **Location:** Tokyo, Japan 🇯🇵

## Software Requirements
- Python 3.12
- CUDA 12.x
- Node.js 20+
- ffmpeg
- Git

## Installation

\`\`\`bash
# 1 — Clone the repository
git clone https://github.com/NPDSANDBOX/zaya-os.git
cd zaya-os

# 2 — Run the installer
chmod +x install.sh
./install.sh

# 3 — Download models
python3 scripts/download_models.py

# 4 — Test the system
python3 scripts/test_pipeline.py

# 5 — Start ZAYA OS
python3 hub/capabilities/zaya_chat_v4.py
\`\`\`

> ⚡ Full installation takes approximately 2-4 hours depending on your internet speed (model downloads).

## Pipelines

### Image Generation
| Pipeline | Model | Resolution | Time |
|----------|-------|-----------|------|
| \`pipeline_flux1.py\` | Flux.1 Dev | 1152x1536 | ~225s |
| \`pipeline_juggernaut_v3.py\` | Juggernaut XL v9 | 1152x1536 | ~90s |

### Image to Video
| Pipeline | Model | Resolution | Time |
|----------|-------|-----------|------|
| \`pipeline_cogvideox.py\` | CogVideoX-5B | 720x480 | ~variable |
| \`pipeline_wan2gp_v1.py\` | Wan2.1 I2V 14B | 832x480 | ~29min |
| \`pipeline_hunyuan_i2v.py\` | Hunyuan 1.5 Distilled | 832x480 | ~8 steps |
| \`pipeline_svd.py\` | Stable Video Diffusion | 1024x576 | ~5min |
| \`pipeline_svd_cinematic.py\` | SVD Multi-clip | 1024x576 | ~30-40s |

### Video & Effects
| Pipeline | Model | Output |
|----------|-------|--------|
| \`pipeline_remotion.py\` | Remotion + React | Instant render |

### Audio
| Pipeline | Model | Output |
|----------|-------|--------|
| Piper TTS | Local TTS | Natural narration |
| XTTS | Voice cloning | Custom voices |

## Architecture

\`\`\`
ZAYA OS
│
├── INPUT — text, image, prompt
│
├── ORCHESTRATOR — zaya_chat_v4.py
│   └── LLM (Qwen3-14B local) — understands intent
│       └── generates CONTRACT (JSON)
│
├── DISPATCHER — reads CONTRACT, routes to pipeline
│   ├── type: "image"  → pipeline_flux1.py / pipeline_juggernaut_v3.py
│   ├── type: "video"  → pipeline_cogvideox.py / pipeline_wan2gp_v1.py
│   ├── type: "audio"  → piper TTS / XTTS
│   └── type: "render" → pipeline_remotion.py
│
├── PIPELINES — execute the task
│   └── output: image / video / audio
│
├── ASSEMBLER — ffmpeg mounts final video
│   ├── clips + narration + ambient sound
│   └── crossfade, transitions, subtitles
│
└── OUTPUT — final cinematic video
\`\`\`

## Contract System

\`\`\`json
{
  "type": "video",
  "input": {
    "image": "/path/to/image.png",
    "prompt": "cinematic motion description",
    "output": "/path/to/output.mp4",
    "engine": "cogvideox",
    "num_frames": 49,
    "fps": 8
  }
}
\`\`\`

## Multi-Agent System

\`\`\`
Orchestrator
├── Agent 1 — image generation
├── Agent 2 — video animation
├── Agent 3 — audio narration
└── Agent 4 — final assembly
\`\`\`

## Contributing

\`\`\`bash
git fork https://github.com/NPDSANDBOX/zaya-os.git
git checkout -b feature/my-new-pipeline
git commit -m "Add: my new pipeline"
git push origin feature/my-new-pipeline
\`\`\`

### Ways to contribute:
- New pipelines
- New models integration
- Documentation improvements
- Bug fixes
- Performance optimizations

## License

MIT License — free to use, modify and distribute.

## Credits

**Created by Mike Henri**
Tokyo, Japan 🇯🇵 — April 2026

*Built from zero. No cloud. No limits. Just a machine and a vision.*
