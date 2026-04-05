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

REALISM = "sharp focus, deep depth of field, sharp background, detailed environment, everything in focus, f/11 aperture"


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


def build_custom_faceid_embeds(face_embed):
    """Build ip_adapter_image_embeds tensor from InsightFace embedding for diffusers native API.
    Returns [neg_embed, pos_embed] stacked for classifier-free guidance."""
    pos = face_embed.unsqueeze(0).unsqueeze(0)   # [1, 1, 1, 512]
    neg = torch.zeros_like(pos)
    return torch.cat([neg, pos]).to(dtype=torch.float16)

NEGATIVE_BASE = (
    "blurry, soft, low detail, painting, cartoon, anime, cgi, "
    "illustration, smooth skin, airbrushed, over-saturated, "
    "nude, naked, nsfw, revealing, explicit, sexual, "
    "blurry background, bokeh, shallow depth of field, out of focus background, "
    "depth of field blur, lens blur, background blur"
)

# Strength decresce a cada pass — passes posteriores fazem ajustes finos
STRENGTH_BY_PASS = {
    2: 0.35,  # luz/atmosfera — refinamento leve
    3: 0.25,  # personagem — ajuste fino, nunca reescrever
    4: 0.20,  # style — finishing mínimo
    5: 0.20,
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

    if lora_path and os.path.exists(lora_path):
        print(f"[JUG v3] Loading LoRA: {lora_path}", flush=True)
        pipe.load_lora_weights(lora_path)
        pipe.fuse_lora(lora_scale=0.7)

    # IP-Adapter CustomFaceID — native diffusers integration
    # Must be loaded BEFORE enable_attention_slicing (incompatible processors)
    custom_faceid_embeds = None
    custom_faceid_ref = args.get("custom_faceid_ref")
    custom_faceid_scale = args.get("custom_faceid_scale", 0.6)
    if custom_faceid_ref and os.path.exists(custom_faceid_ref) and os.path.exists(IPADAPTER_FACEID):
        print(f"[JUG v3] Extracting face embedding from: {custom_faceid_ref}", flush=True)
        face_embed = extract_face_embedding(custom_faceid_ref)
        if face_embed is not None:
            print(f"[JUG v3] Loading IP-Adapter CustomFaceID (scale={custom_faceid_scale})...", flush=True)
            pipe.load_ip_adapter(
                os.path.dirname(IPADAPTER_FACEID),
                subfolder="",
                weight_name=os.path.basename(IPADAPTER_FACEID),
                image_encoder_folder=None,
            )
            pipe.set_ip_adapter_scale(custom_faceid_scale)
            custom_faceid_embeds = build_custom_faceid_embeds(face_embed)
            print(f"[JUG v3] CustomFaceID ready: embeds={custom_faceid_embeds.shape}, scale={custom_faceid_scale}", flush=True)
        else:
            print("[JUG v3] Skipping CustomFaceID — no face found in reference", flush=True)
    else:
        # Only enable attention slicing when no IP-Adapter (they conflict)
        pipe.enable_attention_slicing()

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    generator = torch.Generator("cuda").manual_seed(seed)

    # ── PASS 1 — txt2img ───────────────────────────────────
    p1_prompt = f"{passes[0]}, single person, one woman, customcharacter, {REALISM}"
    print(f"\n[JUG v3] PASS 1 — txt2img", flush=True)
    print(f"[JUG v3] {width}x{height} | steps={steps_base} | cfg={cfg}", flush=True)

    # Build generation kwargs — CustomFaceID embeds injected via native cross-attention
    gen_kwargs = dict(
        prompt=p1_prompt,
        negative_prompt=neg_prompt,
        width=width,
        height=height,
        num_inference_steps=steps_base,
        guidance_scale=cfg,
        generator=torch.Generator("cuda").manual_seed(seed),
    )
    if custom_faceid_embeds is not None:
        gen_kwargs["ip_adapter_image_embeds"] = [custom_faceid_embeds.to("cuda")]

    image = pipe(**gen_kwargs).images[0]

    t1 = time.time()
    print(f"[JUG v3] PASS 1 done ({t1-t0:.1f}s)", flush=True)

    # ── img2img pipeline (shared for character pass + budget passes) ──
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

    # ── CHARACTER PASS — refine identity with CustomFaceID ─────
    if custom_faceid_embeds is not None and prompt_char:
        char_prompt = f"{prompt_char}, customcharacter, {REALISM}"
        char_neg = f"{neg_prompt}, multiple people, two women, crowd, duplicate person"
        char_strength = 0.35

        print(f"\n[JUG v3] CHARACTER PASS — img2img | strength={char_strength}", flush=True)
        print(f"[JUG v3] prompt: {prompt_char[:80]}...", flush=True)

        tp = time.time()
        image = pipe_i2i(
            prompt=char_prompt,
            negative_prompt=char_neg,
            image=image,
            strength=char_strength,
            num_inference_steps=max(20, steps_base - 10),
            guidance_scale=cfg,
            generator=torch.Generator("cuda").manual_seed(seed + 100),
            ip_adapter_image_embeds=[custom_faceid_embeds.to("cuda")],
        ).images[0]
        print(f"[JUG v3] CHARACTER PASS done ({time.time()-tp:.1f}s)", flush=True)

    # ── PASS 2-N — budget planner passes ──────────────────
    if n_passes > 1:
        # Unload IP-Adapter for budget passes to avoid face interference with environment
        if custom_faceid_embeds is not None:
            pipe.unload_ip_adapter()

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
