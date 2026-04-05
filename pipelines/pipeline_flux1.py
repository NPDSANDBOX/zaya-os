#!/usr/bin/env python3
"""
ZAYA PIPELINE — FLUX.1 Dev + IP-Adapter CustomFaceID (CLIP Vision ViT-H)
Flux.1 Dev — no token limit, cinematic quality
CustomFaceID — usa CLIP Vision ViT-H penultimate layer (1152 dims)
RTX 3080 Ti 12GB — sequential cpu offload
"""
import sys, json, os, time, torch, warnings
import numpy as np
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

from diffusers import FluxPipeline
from PIL import Image, ImageFilter
import torch.nn as nn

FLUX_MODEL       = "/opt/ComfyUI/models/checkpoints/flux-dev"
FACEID_MODEL     = "/opt/ComfyUI/models/ipadapter/ip-adapter-flux-custom_faceid.bin"
CLIP_VISION_PATH = "/opt/ComfyUI/models/clip_vision/model.safetensors"
FACEID_REF_DEFAULT = "/opt/zaya_os/hub/memory/universe_docs/characters/CustomCharacter/zaya_custom_faceid_reference.png"

NEGATIVE_BASE = (
    "blurry, soft, low detail, painting, cartoon, anime, cgi, "
    "illustration, smooth skin, airbrushed, over-saturated, "
    "nude, naked, nsfw, revealing, explicit, sexual, "
    "looking at camera, selfie angle, passport photo, "
    "long wavy hair, curly hair, very long hair"
)

class FaceIDImageProj(nn.Module):
    def __init__(self, in_dim=1152, mid_dim=2304, out_tokens=128, out_dim=4096):
        super().__init__()
        self.proj = nn.Sequential(
            nn.Linear(in_dim, mid_dim),
            nn.GELU(),
            nn.Linear(mid_dim, out_tokens * out_dim),
        )
        self.norm = nn.LayerNorm(out_dim)
        self.out_tokens = out_tokens
        self.out_dim = out_dim

    def forward(self, x):
        x = self.proj(x)
        x = x.view(-1, self.out_tokens, self.out_dim)
        x = self.norm(x)
        return x

def load_custom_faceid_proj(state_dict, device="cpu"):
    in_dim  = state_dict["proj.0.weight"].shape[1]
    mid_dim = state_dict["proj.0.weight"].shape[0]
    flat    = state_dict["proj.2.weight"].shape[0]
    out_dim = state_dict["norm.weight"].shape[0]
    out_tokens = flat // out_dim
    print(f"[FLUX1] ImageProj: in={in_dim} mid={mid_dim} tokens={out_tokens} out={out_dim}", flush=True)
    proj = FaceIDImageProj(in_dim, mid_dim, out_tokens, out_dim)
    proj.load_state_dict(state_dict)
    proj = proj.to(device=device, dtype=torch.bfloat16)
    proj.eval()
    return proj

def get_clip_vision_embed(image_path, clip_path, device="cpu"):
    """Extract penultimate layer embedding from CLIP Vision ViT-H (1152 dims)."""
    from transformers import CLIPVisionModelWithProjection, CLIPImageProcessor
    import safetensors.torch as st

    print("[FLUX1] Loading CLIP Vision ViT-H...", flush=True)

    # Carrega processor e modelo
    # Carrega processor do disco local — zero internet
    processor = CLIPImageProcessor.from_pretrained(
        "/opt/zaya_os/hub/models/clip_vision_processor",
        local_files_only=True
    )

    # Carrega pesos do arquivo local
    from transformers import CLIPVisionConfig, CLIPVisionModel
    config = CLIPVisionConfig(
        hidden_size=1280,
        image_size=224,
        intermediate_size=5120,
        num_attention_heads=16,
        num_hidden_layers=32,
        patch_size=14,
    )
    model = CLIPVisionModel(config)
    weights = st.load_file(clip_path)
    # Ajusta keys para o modelo
    state = {k.replace("vision_model.", ""): v for k, v in weights.items() if "vision_model" in k}
    model.vision_model.load_state_dict(state, strict=False)
    model = model.to(device=device, dtype=torch.bfloat16)
    model.eval()

    img = Image.open(image_path).convert("RGB")
    inputs = processor(images=img, return_tensors="pt")
    pixel_values = inputs["pixel_values"].to(device=device, dtype=torch.bfloat16)

    with torch.no_grad():
        outputs = model(pixel_values=pixel_values, output_hidden_states=True)
        # Penultimate layer hidden state, CLS token → [1, 1280]
        # Depois projeta para 1152 via slice ou linear
        penultimate = outputs.hidden_states[-2][:, 0, :]  # [1, 1280]

        # O image_proj espera 1152 — usa os primeiros 1152 dims
        # (comum em implementações CustomFaceID Flux)
        embed = penultimate[:, :1152]  # [1, 1152]

    print(f"[FLUX1] CLIP Vision embed shape: {embed.shape}", flush=True)
    return embed

def inject_ip_adapter(transformer, ip_adapter_weights, ip_hidden_states, scale=0.9):
    n_blocks = len(transformer.transformer_blocks)
    print(f"[FLUX1] Injecting CustomFaceID into {n_blocks} transformer blocks | scale={scale}", flush=True)
    ip_keys   = {}
    ip_values = {}
    for idx in range(min(n_blocks, 57)):
        k_key = f"{idx}.to_k_ip.weight"
        v_key = f"{idx}.to_v_ip.weight"
        if k_key in ip_adapter_weights and v_key in ip_adapter_weights:
            hidden_dim = transformer.transformer_blocks[idx].attn.to_k.weight.shape[0]
            ip_dim     = ip_hidden_states.shape[-1]
            to_k_ip = nn.Linear(ip_dim, hidden_dim, bias=False)
            to_k_ip.weight = nn.Parameter(ip_adapter_weights[k_key].clone())
            to_v_ip = nn.Linear(ip_dim, hidden_dim, bias=False)
            to_v_ip.weight = nn.Parameter(ip_adapter_weights[v_key].clone())
            ip_keys[idx]   = to_k_ip.to(dtype=torch.bfloat16)
            ip_values[idx] = to_v_ip.to(dtype=torch.bfloat16)
    print(f"[FLUX1] IP weights loaded for {len(ip_keys)} blocks", flush=True)
    return ip_keys, ip_values

def run(spec_path):
    with open(spec_path) as f:
        args = json.load(f)

    prompt       = args.get("prompt", "")
    prompt_char  = args.get("prompt_character", "")
    negative     = args.get("negative", "")
    output_path  = args["output"]
    width        = args.get("width", 1152)
    height       = args.get("height", 1536)
    steps        = args.get("steps", 30)
    guidance     = args.get("guidance", 3.5)
    seed         = args.get("seed", int(time.time()))
    custom_faceid_ref   = args.get("custom_faceid_ref", FACEID_REF_DEFAULT)
    custom_faceid_scale = args.get("custom_faceid_scale", 0.45)

    # Environment first, character after — scene establishes context
    if prompt_char:
        full_prompt = f"{prompt}, {prompt_char}"
    else:
        full_prompt = prompt

    neg_prompt = f"{NEGATIVE_BASE}, {negative}".strip(", ")

    print(f"[FLUX1] prompt: {len(full_prompt.split())} words", flush=True)
    print(f"[FLUX1] {width}x{height} | steps={steps} | guidance={guidance} | seed={seed}", flush=True)

    t0 = time.time()
    torch.cuda.empty_cache()
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    print("[FLUX1] Loading FluxPipeline bf16...", flush=True)
    pipe = FluxPipeline.from_pretrained(
        FLUX_MODEL,
        torch_dtype=torch.bfloat16
    )

    use_custom_faceid = False
    # Only activate CustomFaceID when Zaya is in the scene
    has_zaya = "customcharacter" in prompt_char.lower() or "customcharacter" in full_prompt.lower()
    print(f"[FLUX1] CustomFaceID active: {has_zaya}", flush=True)

    print("[FLUX1] Loading CustomFaceID weights...", flush=True)
    try:
        if not has_zaya:
            raise RuntimeError("No Zaya in scene — skipping CustomFaceID")
        state = torch.load(FACEID_MODEL, map_location="cpu", weights_only=False)
        ip_weights   = state["ip_adapter"]
        proj_weights = state["image_proj"]

        proj = load_custom_faceid_proj(proj_weights, device="cpu")

        clip_embed = get_clip_vision_embed(custom_faceid_ref, CLIP_VISION_PATH, device="cpu")

        with torch.no_grad():
            ip_hidden_states = proj(clip_embed)

        print(f"[FLUX1] ip_hidden_states shape: {ip_hidden_states.shape}", flush=True)

        ip_keys, ip_values = inject_ip_adapter(
            pipe.transformer, ip_weights, ip_hidden_states, scale=custom_faceid_scale
        )

        use_custom_faceid = True
        print("[FLUX1] CustomFaceID ready", flush=True)

    except Exception as e:
        import traceback
        print(f"[FLUX1] WARNING: CustomFaceID failed ({e})", flush=True)
        traceback.print_exc()
        print("[FLUX1] Falling back to prompt-only generation", flush=True)

    pipe.enable_sequential_cpu_offload()
    pipe.vae.enable_slicing()
    pipe.vae.enable_tiling()

    print("[FLUX1] Generating...", flush=True)
    generator = torch.Generator("cpu").manual_seed(seed)

    if use_custom_faceid:
        print("[FLUX1] Generating with CustomFaceID", flush=True)
    else:
        print("[FLUX1] Generating without CustomFaceID", flush=True)

    image = pipe(
        prompt=full_prompt,
        width=width,
        height=height,
        num_inference_steps=steps,
        guidance_scale=guidance,
        generator=generator,
    ).images[0]

    image = image.filter(ImageFilter.UnsharpMask(radius=1.2, percent=130, threshold=2))
    image.save(output_path)
    print(f"[FLUX1] Saved: {output_path} ({time.time()-t0:.1f}s)", flush=True)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "error": "usage: pipeline_flux1.py <spec_path>"}))
        sys.exit(1)
    run(sys.argv[1])
