#!/usr/bin/env python3
"""
ZAYA PIPELINE v3 — Juggernaut XL v9
N passes dinâmicos via Token Budget Planner
Pass 1: txt2img (ambiente base)
Pass 2-N: img2img sequencial (cada pass refina com seu slice semântico)
"""
import sys, json, os, time, torch, warnings, numpy as np
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

sys.path.insert(0, "/opt/zaya_os/hub/capabilities")

from diffusers import StableDiffusionXLPipeline, StableDiffusionXLImg2ImgPipeline, AutoencoderKL
from PIL import Image, ImageFilter

LORA       = "/opt/zaya_os/hub/models/loras/zaya_universe/output/custom_lora_v1.safetensors"
SAFETENSOR = "/opt/zaya_os/hub/models/sd/juggernaut-xl-v9/Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors"
VAE_PATH   = "/opt/zaya_os/hub/models/sd/dreamshaper-xl-1-0/vae"

IPADAPTER_FACEID = "/opt/ComfyUI/models/ipadapter/ip-adapter-custom_faceid_sdxl.bin"
INSIGHTFACE_DIR  = "/opt/ComfyUI/models/ipadapter/buffalo_l"

REALISM = "sharp focus"


def extract_face_embedding(image_path):
    """Extract 512-dim face embedding from reference image using InsightFace."""
    from insightface.app import FaceAnalysis

    app = FaceAnalysis(name="buffalo_l", root=os.path.dirname(INSIGHTFACE_DIR),
                       providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
    app.prepare(ctx_id=0, det_size=(640, 640))

    img = np.array(Image.open(image_path).convert("RGB"))
    # InsightFace expects BGR
    img_bgr = img[:, :, ::-1]
    faces = app.get(img_bgr)
    if not faces:
        print("[JUG v3] WARNING: no face detected in reference image", flush=True)
        return None
    # Use largest face
    face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
    return torch.tensor(face.normed_embedding, dtype=torch.float16).unsqueeze(0)


def project_face_embedding(custom_faceid_embeds):
    """Project InsightFace embedding (512-dim) to SDXL cross-attention space (4 tokens x 2048)."""
    state_dict = torch.load(IPADAPTER_FACEID, map_location="cpu", weights_only=True)
    ip_proj = state_dict["image_proj"]

    proj_w0 = ip_proj["proj.0.weight"].float()   # [1024, 512]
    proj_b0 = ip_proj["proj.0.bias"].float()
    proj_w2 = ip_proj["proj.2.weight"].float()   # [8192, 1024]
    proj_b2 = ip_proj["proj.2.bias"].float()
    norm_w  = ip_proj["norm.weight"].float()      # [2048]
    norm_b  = ip_proj["norm.bias"].float()

    x = custom_faceid_embeds.float()
    x = x @ proj_w0.T + proj_b0
    x = torch.nn.functional.gelu(x)
    x = x @ proj_w2.T + proj_b2
    x = x.reshape(1, 4, 2048)
    x = torch.nn.functional.layer_norm(x, [2048], weight=norm_w, bias=norm_b)
    return x.half()

NEGATIVE_BASE = (
    "blurry, soft, low detail, painting, cartoon, anime, cgi, "
    "illustration, smooth skin, airbrushed, over-saturated, "
    "nude, naked, nsfw, revealing, explicit, sexual"
)

# Strength decresce a cada pass — passes posteriores fazem ajustes finos
STRENGTH_BY_PASS = {
    2: 0.55,  # luz/atmosfera — refinamento leve
    3: 0.70,  # personagem — strength alto para reforçar Zaya
    4: 0.45,  # style — finishing leve
    5: 0.35,
}

def run(spec_path):
    with open(spec_path) as f:
        args = json.load(f)

    prompt_full = args.get("prompt", "")
    prompt_char = args.get("prompt_character", "")
    negative    = args.get("negative", "")
    output_path = args["output"]
    width       = args.get("width", 1024)
    height      = args.get("height", 1344)
    steps_base  = args.get("steps", 40)
    cfg         = args.get("guidance", 7.6)
    seed        = args.get("seed", int(time.time()))
    lora_path   = args.get("lora", LORA)

    # ── TOKEN BUDGET PLANNER ─────────────────────────────
    from token_budget_planner_v1 import plan
    budget = plan(prompt_full, prompt_char, negative)

    passes     = budget["passes"]
    n_passes   = budget["n_passes"]
    neg_prompt = f"{NEGATIVE_BASE}, {budget['negative']}".strip(", ")

    print(f"[JUG v3] tokens={budget['token_count']} → {n_passes} passes", flush=True)
    for i, p in enumerate(passes):
        print(f"[JUG v3] pass {i+1}: {p[:80]}...", flush=True)

    t0 = time.time()
    torch.cuda.empty_cache()

    # ── LOAD PIPELINE ────────────────────────────────────
    print("[JUG v3] Loading Juggernaut XL v9...", flush=True)
    pipe = StableDiffusionXLPipeline.from_single_file(
        SAFETENSOR,
        torch_dtype=torch.float16,
        use_safetensors=True,
        variant="fp16"
    )

    print("[JUG v3] Loading VAE Dreamshaper...", flush=True)
    vae = AutoencoderKL.from_pretrained(VAE_PATH, torch_dtype=torch.float16)
    pipe.vae = vae
    pipe.enable_model_cpu_offload()
    pipe.vae.enable_slicing()
    pipe.vae.enable_tiling()
    pipe.enable_attention_slicing()

    if lora_path and os.path.exists(lora_path):
        print(f"[JUG v3] Loading LoRA: {lora_path}", flush=True)
        pipe.load_lora_weights(lora_path)
        pipe.fuse_lora(lora_scale=0.7)

    # IP-Adapter CustomFaceID — extract face identity tokens from reference image
    face_tokens = None
    custom_faceid_ref = args.get("custom_faceid_ref")
    if custom_faceid_ref and os.path.exists(custom_faceid_ref) and os.path.exists(IPADAPTER_FACEID):
        print(f"[JUG v3] Extracting face embedding from: {custom_faceid_ref}", flush=True)
        face_embed = extract_face_embedding(custom_faceid_ref)
        if face_embed is not None:
            face_tokens = project_face_embedding(face_embed)
            print(f"[JUG v3] CustomFaceID tokens ready: {face_tokens.shape}", flush=True)
        else:
            print("[JUG v3] Skipping CustomFaceID — no face found in reference", flush=True)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    generator = torch.Generator("cuda").manual_seed(seed)

    # ── PASS 1 — txt2img base ────────────────────────────
    # Pass 1: ambiente + trigger mínimo do LoRA (só 3 tokens extras)
    p1_prompt = f"{passes[0]}, customcharacter, {REALISM}"
    print(f"\n[JUG v3] PASS 1 — txt2img", flush=True)
    print(f"[JUG v3] {width}x{height} | steps={steps_base} | cfg={cfg}", flush=True)

    print("[JUG v3] Encoding prompt (long prompt support)...", flush=True)
    (
        prompt_embeds,
        negative_prompt_embeds,
        pooled_prompt_embeds,
        negative_pooled_prompt_embeds,
    ) = pipe.encode_prompt(
        prompt=p1_prompt,
        negative_prompt=neg_prompt,
        device="cuda",
        num_images_per_prompt=1,
        do_classifier_free_guidance=True,
    )

    # Inject CustomFaceID tokens into prompt embeddings
    if face_tokens is not None:
        ft = face_tokens.to(prompt_embeds.device)
        # Concat face tokens to prompt (positive only, pad negative with zeros)
        ft_pad = torch.zeros_like(ft)
        # prompt_embeds shape: [2, seq_len, 2048] (negative + positive for CFG)
        prompt_embeds = torch.cat([
            torch.cat([negative_prompt_embeds, ft_pad], dim=1),
            torch.cat([prompt_embeds, ft], dim=1),
        ], dim=0)
        # Update negative to match new shape
        negative_prompt_embeds = prompt_embeds[:1]
        prompt_embeds = prompt_embeds[1:]
        print(f"[JUG v3] CustomFaceID tokens injected into prompt embeddings", flush=True)

    image = pipe(
        prompt_embeds=prompt_embeds,
        negative_prompt_embeds=negative_prompt_embeds,
        pooled_prompt_embeds=pooled_prompt_embeds,
        negative_pooled_prompt_embeds=negative_pooled_prompt_embeds,
        width=width,
        height=height,
        num_inference_steps=steps_base,
        guidance_scale=cfg,
        generator=torch.Generator("cuda").manual_seed(seed)
    ).images[0]

    t1 = time.time()
    print(f"[JUG v3] PASS 1 done ({t1-t0:.1f}s)", flush=True)

    # ── PASS 2-N — img2img sequencial ───────────────────
    if n_passes > 1:
        pipe_i2i = StableDiffusionXLImg2ImgPipeline(
            vae=pipe.vae,
            text_encoder=pipe.text_encoder,
            text_encoder_2=pipe.text_encoder_2,
            tokenizer=pipe.tokenizer,
            tokenizer_2=pipe.tokenizer_2,
            unet=pipe.unet,
            scheduler=pipe.scheduler,
        )
        pipe_i2i.enable_model_cpu_offload()

        steps_i2i = max(20, steps_base - 10)

        for i, pass_prompt in enumerate(passes[1:], start=2):
            strength = STRENGTH_BY_PASS.get(i, 0.35)
            full_pass_prompt = f"{pass_prompt}, {REALISM}"

            print(f"\n[JUG v3] PASS {i} — img2img | strength={strength}", flush=True)
            print(f"[JUG v3] prompt: {pass_prompt[:80]}...", flush=True)

            tp = time.time()
            image = pipe_i2i(
                prompt=full_pass_prompt,
                negative_prompt=neg_prompt,
                image=image,
                strength=strength,
                num_inference_steps=steps_i2i,
                guidance_scale=cfg,
                generator=torch.Generator("cuda").manual_seed(seed + i)
            ).images[0]

            print(f"[JUG v3] PASS {i} done ({time.time()-tp:.1f}s)", flush=True)

    # ── FINISHING ────────────────────────────────────────
    image = image.filter(ImageFilter.UnsharpMask(radius=1.2, percent=130, threshold=2))
    image.save(output_path)
    print(f"\n[JUG v3] Saved: {output_path} | Total: {time.time()-t0:.1f}s", flush=True)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "error": "usage: pipeline_juggernaut_v3.py <spec_path>"}))
        sys.exit(1)
    run(sys.argv[1])
