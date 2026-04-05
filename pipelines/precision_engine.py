#!/usr/bin/env python3
"""
ZAYA PRECISION ENGINE
Auto-selects fp16 or fp32 based on available VRAM and request.
"""
import subprocess
import torch

def get_vram_free():
    """Returns free VRAM in MB."""
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True
        )
        return int(r.stdout.strip())
    except Exception:
        return 0

def get_vram_total():
    """Returns total VRAM in MB."""
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True
        )
        return int(r.stdout.strip())
    except Exception:
        return 0

def select_precision(model_size_gb, force=None):
    """
    Select best precision based on VRAM.
    
    Args:
        model_size_gb: model size in GB (fp32)
        force: "fp16" | "fp32" | None (auto)
    
    Returns:
        dict with dtype, dtype_str, reason
    """
    if force == "fp32":
        return {
            "dtype":     torch.float32,
            "dtype_str": "fp32",
            "reason":    "forced by user"
        }

    if force == "fp16":
        return {
            "dtype":     torch.float16,
            "dtype_str": "fp16",
            "reason":    "forced by user"
        }

    # Auto detection
    vram_free_mb  = get_vram_free()
    vram_free_gb  = vram_free_mb / 1024
    model_fp16_gb = model_size_gb / 2

    if vram_free_gb >= model_size_gb:
        # Enough VRAM for fp32
        return {
            "dtype":     torch.float32,
            "dtype_str": "fp32",
            "reason":    f"sufficient VRAM ({vram_free_gb:.1f}GB free, model needs {model_size_gb}GB)"
        }
    elif vram_free_gb >= model_fp16_gb:
        # Only enough for fp16
        return {
            "dtype":     torch.float16,
            "dtype_str": "fp16",
            "reason":    f"limited VRAM ({vram_free_gb:.1f}GB free), using fp16 ({model_fp16_gb}GB)"
        }
    else:
        # Low VRAM — use bf16 + cpu offload
        return {
            "dtype":      torch.bfloat16,
            "dtype_str":  "bf16",
            "reason":     f"low VRAM ({vram_free_gb:.1f}GB free), using bf16 + cpu offload",
            "cpu_offload": True
        }

def select_flux_precision(force=None):
    """Flux Dev is 23GB fp32, 11.5GB fp16."""
    return select_precision(model_size_gb=23, force=force)

def select_sdxl_precision(force=None):
    """DreamShaper XL is 9.6GB fp32, 4.8GB fp16."""
    return select_precision(model_size_gb=9.6, force=force)

def select_flux2_precision(force=None):
    """FLUX.2 Dev is ~34GB fp32, ~17GB fp16."""
    return select_precision(model_size_gb=34, force=force)

if __name__ == "__main__":
    vram_free = get_vram_free()
    vram_total = get_vram_total()
    print(f"VRAM: {vram_free}MB free / {vram_total}MB total")
    print()
    print("SDXL precision:",  select_sdxl_precision())
    print("FLUX.1 precision:", select_flux_precision())
    print("FLUX.2 precision:", select_flux2_precision())
