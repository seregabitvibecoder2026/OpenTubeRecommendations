"""Hardware detection (GPU / VRAM) without importing heavy libraries."""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import time

_cache: dict = {"ts": 0, "v": None}


def gpu_info(force: bool = False) -> dict:
    """{'gpu': bool, 'name', 'total_gb', 'free_gb', 'source'}"""
    if not force and _cache["v"] and time.time() - _cache["ts"] < 30:
        return _cache["v"]
    info = {"gpu": False, "name": None, "total_gb": 0.0, "free_gb": 0.0, "source": None}
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            out = subprocess.run([smi, "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=5).stdout.strip().splitlines()
            if out:
                name, total, free = [x.strip() for x in out[0].split(",")]
                info = {"gpu": True, "name": name, "total_gb": round(float(total) / 1024, 2),
                        "free_gb": round(float(free) / 1024, 2), "source": "nvidia-smi"}
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    _cache.update(ts=time.time(), v=info)
    return info


def has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def torch_device(pref: str = "auto") -> str:
    if pref in ("cpu", "cuda"):
        return pref
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:  # noqa: BLE001
        return "cpu"


def ram_gb() -> float:
    try:
        with open("/proc/meminfo") as f:
            for ln in f:
                if ln.startswith("MemTotal"):
                    return round(int(ln.split()[1]) / 1024 / 1024, 1)
    except OSError:
        pass
    return 0.0
