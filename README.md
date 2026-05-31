# ZAYA OS

> *The first AI operating system that turns a single machine into a complete autonomous content studio — from text to cinematic video, with no cloud dependency, no per-use cost, and no creative limits.*

---

### Project Status

**ZAYA OS has evolved significantly beyond what is represented in this repository.** The system now includes multi-agent architecture, autonomous cognition loops, real-time voice interaction, supervised process management, and production-grade video pipelines that are not reflected here.

**This repository will no longer receive updates.** What you see here is a historical snapshot of the early foundation. The project continues to grow privately.

Thank you to those who took the time to look. And thank you for the downvotes on Reddit — they were noted.

*— Mike Henri, April 2026*

---

## Copyright & Authorship

ZAYA OS was **conceived, designed and developed by Mike Henri** — the result of over a year of independent research and engineering. The architecture, source code, core concepts and design decisions are his original intellectual work.

**© 2025–2026 Mike Henri. All rights reserved**, except for the freedoms explicitly granted under the AGPL-3.0 license (see [License](#license) below). Use of this project does not transfer any ownership of the underlying ideas or implementation.

---

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

## License

ZAYA OS is licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)**. See the [LICENSE](LICENSE) file for the full text.

In short: you are free to use, study, modify and share ZAYA OS — but if you run a modified version, **including over a network or as a hosted service**, you must release your modifications under the same license. This keeps the project open and prevents anyone from taking the work, building a closed commercial product on top of it, and giving nothing back.

### Commercial licensing

The AGPL-3.0 is not suitable for every use case. If you want to use ZAYA OS inside a proprietary or closed-source product without the copyleft obligations, a separate **commercial license is available**. As the sole copyright holder, the author can grant such exceptions — contact **Mike Henri** to discuss commercial terms.

## Credits

**Created by Mike Henri**
Tokyo, Japan — April 2026

*Built from zero. No cloud. No limits. Just a machine and a vision.*
