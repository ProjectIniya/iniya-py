"""
device_profile.py — Iniya hardware profiler + auto-downloader
Windows only. Detects hardware, picks the right STT/TTS tier,
and auto-downloads any missing models/binaries.

Override the models folder via env var (optional):
    set INIYA_MODELS_DIR=D:\\MyModels

Usage:
    from device_profile import get_profile, ensure_models
    profile = get_profile(verbose=True)
    ensure_models(profile)   # downloads anything missing
"""

import ctypes
import json
import os
import shutil
import sys
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional
import urllib.request

from AI_Model.log import log

# ─────────────────────────────────────────────────────────────────────────────
#  Paths  (everything derived from THIS_DIR — no hardcoding)
# ─────────────────────────────────────────────────────────────────────────────

THIS_DIR        = Path(__file__).resolve().parent.parent.parent / "cache"
MODELS_DIR      = Path(os.environ.get("INIYA_MODELS_DIR", THIS_DIR / "models"))

VOSK_DIR        = MODELS_DIR / "vosk"
PIPER_DIR       = MODELS_DIR / "piper"
PIPER_BIN       = PIPER_DIR  / "bin" / "piper.exe"
PIPER_VOICE_DIR = PIPER_DIR  / "voices"
WHISPER_DIR     = MODELS_DIR / "whisper"

# ─────────────────────────────────────────────────────────────────────────────
#  Remote URLs
# ─────────────────────────────────────────────────────────────────────────────

PIPER_RELEASE = (
    "https://github.com/rhasspy/piper/releases/download"
    "/2023.11.14-2/piper_windows_amd64.zip"
)

VOSK_MODELS = {
    "vosk-model-small-en-us-0.15": (
        "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
    ),
}

HF = "https://huggingface.co/rhasspy/piper-voices/resolve/main"
PIPER_VOICES = {
    "en_US-ryan-low": {
        "onnx":   f"{HF}/en/en_US/ryan/low/en_US-ryan-low.onnx",
        "config": f"{HF}/en/en_US/ryan/low/en_US-ryan-low.onnx.json",
    },
    "en_US-lessac-medium": {
        "onnx":   f"{HF}/en/en_US/lessac/medium/en_US-lessac-medium.onnx",
        "config": f"{HF}/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json",
    },
    "en_US-arctic-medium": {
        "onnx":   f"{HF}/en/en_US/arctic/medium/en_US-arctic-medium.onnx",
        "config": f"{HF}/en/en_US/arctic/medium/en_US-arctic-medium.onnx.json",
    },
    "en_GB-cori-medium": {
        "onnx":   f"{HF}/en/en_GB/cori/medium/en_GB-cori-medium.onnx",
        "config": f"{HF}/en/en_GB/cori/medium/en_GB-cori-medium.onnx.json",
    },
    "en_GB-cori-high": {
        "onnx":   f"{HF}/en/en_GB/cori/high/en_GB-cori-high.onnx",
        "config": f"{HF}/en/en_GB/cori/high/en_GB-cori-high.onnx.json",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
#  Tier definitions
# ─────────────────────────────────────────────────────────────────────────────

TIERS = {
    0: {
        "label": "very low",
        "description": "< 2 GB available RAM",
        "stt": {
            "engine": "vosk",
            "model":  "vosk-model-small-en-us-0.15",
            "note":   "Tiny Vosk (~40 MB). Lower accuracy, runs anywhere.",
        },
        "stt_live": {
            "engine": "vosk",
            "model":  "vosk-model-small-en-us-0.15",
            "note":   "Vosk small for live streaming.",
        },
        "tts": {
            "engine": "piper",
            "voice":  "en_US-ryan-low",
            "note":   "Smallest Piper voice — near-instant on old hardware.",
        },
    },
    1: {
        "label": "low",
        "description": "2-4 GB RAM, dual-core",
        "stt": {
            "engine": "vosk",
            "model":  "vosk-model-small-en-us-0.15",
            "note":   "Vosk small — reliable at this RAM budget.",
        },
        "stt_live": {
            "engine": "vosk",
            "model":  "vosk-model-small-en-us-0.15",
            "note":   "Vosk small for live streaming.",
        },
        "tts": {
            "engine": "piper",
            "voice":  "en_US-lessac-medium",
            "note":   "Better voice quality, still very light.",
        },
    },
    2: {
        "label": "mid",
        "description": "4-8 GB RAM, quad-core",
        "stt": {
            "engine":       "whisper",
            "model":        "tiny.en",
            "device":       "cpu",
            "compute_type": "int8",
            "note":         "Whisper tiny CPU+int8 — ~1-2 s latency per sentence.",
        },
        "stt_gpu": {
            "engine":       "whisper",
            "model":        "tiny.en",
            "device":       "cuda",
            "compute_type": "float16",
            "note":         "Whisper tiny GPU — near-instant even on mid-tier RAM.",
        },
        "stt_live": {
            "engine": "vosk",
            "model":  "vosk-model-small-en-us-0.15",
            "note":   "Vosk small for live streaming. Uses Whisper tiny for non-live tasks.",
        },
        "tts": {
            "engine": "piper",
            "voice":  "en_US-lessac-medium",
            "note":   "Piper still beats Silero on CPU-only machines.",
        },
    },
    3: {
        "label": "high",
        "description": "8+ GB RAM, modern CPU",
        "stt": {
            "engine":       "whisper",
            "model":        "base.en",
            "device":       "cpu",
            "compute_type": "int8",
            "note":         "Whisper base CPU — better accuracy than tiny.",
        },
        "stt_gpu": {
            "engine":       "whisper",
            "model":        "base.en",
            "device":       "cuda",
            "compute_type": "float16",
            "note":         "Whisper base GPU — fast and accurate.",
        },
        "stt_live": {
            "engine": "vosk",
            "model":  "vosk-model-small-en-us-0.15",
            "note":   "Vosk small for live streaming. Uses Whisper base for non-live tasks.",
        },
        "tts": {
            "engine": "piper",
            "voice":  "en_US-arctic-medium",
            "note":   "Arctic is noticeably more natural-sounding.",
        },
    },
    4: {
        "label": "high+gpu",
        "description": "8+ GB RAM + CUDA GPU",
        "stt": {
            "engine":       "whisper",
            "model":        "small.en",
            "device":       "cuda",
            "compute_type": "float16",
            "note":         "GPU-accelerated — fast and accurate.",
        },
        "stt_live": {
            "engine": "vosk",
            "model":  "vosk-model-small-en-us-0.15",
            "note":   "Vosk small for live streaming. Uses Whisper small GPU for non-live tasks.",
        },
        "tts": {
            "engine": "piper",
            "voice":  "en_GB-cori-medium",
            "note":   "Piper is already near-instant; GPU doesn't change much here.",
        },
    },
}


# ─────────────────────────────────────────────────────────────────────────────
#  Hardware detection  (Windows — pure stdlib, no psutil)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class HardwareInfo:
    ram_total_mb:      int
    ram_available_mb:  int
    cpu_cores:         int
    has_cuda:          bool
    cuda_device:       Optional[str]
    cuda_vram_mb:      Optional[int]
    whisper_available: bool
    vosk_available:    bool


def _get_ram_windows() -> tuple[int, int]:
    class _MEMSTATEX(ctypes.Structure):
        _fields_ = [
            ("dwLength",                ctypes.c_ulong),
            ("dwMemoryLoad",            ctypes.c_ulong),
            ("ullTotalPhys",            ctypes.c_ulonglong),
            ("ullAvailPhys",            ctypes.c_ulonglong),
            ("ullTotalPageFile",        ctypes.c_ulonglong),
            ("ullAvailPageFile",        ctypes.c_ulonglong),
            ("ullTotalVirtual",         ctypes.c_ulonglong),
            ("ullAvailVirtual",         ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]
    s = _MEMSTATEX()
    s.dwLength = ctypes.sizeof(s)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s))
    return int(s.ullTotalPhys) >> 20, int(s.ullAvailPhys) >> 20


def _get_cuda_info() -> tuple[bool, Optional[str], Optional[int]]:
    try:
        import torch
        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            vram = torch.cuda.get_device_properties(0).total_memory >> 20
            return True, name, vram
    except ImportError:
        pass
    return False, None, None


def _pkg_available(pkg: str) -> bool:
    import importlib.util
    return importlib.util.find_spec(pkg) is not None


def detect_hardware() -> HardwareInfo:
    ram_total, ram_avail = _get_ram_windows()
    has_cuda, cuda_device, cuda_vram = _get_cuda_info()
    return HardwareInfo(
        ram_total_mb      = ram_total,
        ram_available_mb  = ram_avail,
        cpu_cores         = os.cpu_count() or 2,
        has_cuda          = has_cuda,
        cuda_device       = cuda_device,
        cuda_vram_mb      = cuda_vram,
        whisper_available = _pkg_available("whisper"),
        vosk_available    = _pkg_available("vosk"),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Tier scoring + availability check
# ─────────────────────────────────────────────────────────────────────────────

def _score_tier(hw: HardwareInfo) -> int:
    ram = hw.ram_available_mb
    if hw.has_cuda and ram >= 6000:       return 4
    if ram >= 6000 and hw.cpu_cores >= 4: return 3
    if ram >= 3000 and hw.cpu_cores >= 2: return 2
    if ram >= 1500:                       return 1
    return 0


def _apply_availability(tier: int, hw: HardwareInfo) -> tuple[int, dict]:
    """
    Walks down from scored tier until the required engine is installed.
    If a GPU is present and the tier defines an stt_gpu override, it is
    applied before the availability check — so tiers 2 and 3 also benefit
    from CUDA acceleration when a GPU is available.
    Returns (final_tier, config_dict).
    """
    import copy

    for t in range(tier, -1, -1):
        cfg = copy.deepcopy(TIERS[t])

        # Apply GPU override for tiers that define one
        if hw.has_cuda and "stt_gpu" in cfg:
            cfg["stt"] = cfg["stt_gpu"]

        # Strip internal key — not part of the public profile
        cfg.pop("stt_gpu", None)

        engine = cfg["stt"]["engine"]

        if engine == "whisper" and not hw.whisper_available:
            continue   # try a lower tier

        if engine == "vosk" and not hw.vosk_available:
            cfg["stt"]["engine"] = "none"
            cfg["stt"]["note"]   = "No STT installed. Run: pip install vosk"

        return t, cfg

    cfg = copy.deepcopy(TIERS[0])
    cfg.pop("stt_gpu", None)
    cfg["stt"]["engine"] = "none"
    return 0, cfg


# ─────────────────────────────────────────────────────────────────────────────
#  Path helpers  (all derived from MODELS_DIR)
# ─────────────────────────────────────────────────────────────────────────────

def vosk_model_path(model_name: str) -> Path:
    return VOSK_DIR / model_name

def piper_bin_path() -> Path:
    return PIPER_BIN

def piper_voice_path(voice_name: str) -> Path:
    """Returns path to .onnx file. Config JSON is same path + '.json'."""
    return PIPER_VOICE_DIR / f"{voice_name}.onnx"

def whisper_cache_dir() -> Path:
    return WHISPER_DIR


# ─────────────────────────────────────────────────────────────────────────────
#  Downloader utilities
# ─────────────────────────────────────────────────────────────────────────────

def _progress(downloaded: int, total: int, width: int = 40) -> None:
    if total <= 0:
        log(f"\r  {downloaded >> 20} MB...", end="", flush=True)
        return
    pct  = downloaded / total
    done = int(width * pct)
    bar  = "█" * done + "░" * (width - done)
    log(f"\r  [{bar}] {downloaded/1e6:.1f}/{total/1e6:.1f} MB", end="", flush=True)


def _download(url: str, dest: Path, label: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    log(f"\n  Downloading {label}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Iniya/1.0"})
        with urllib.request.urlopen(req) as r, open(tmp, "wb") as f:
            total      = int(r.headers.get("Content-Length", 0))
            downloaded = 0
            while chunk := r.read(65536):
                f.write(chunk)
                downloaded += len(chunk)
                _progress(downloaded, total)
        log()
        tmp.rename(dest)
    except Exception as e:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Download failed ({label}): {e}") from e


# ─────────────────────────────────────────────────────────────────────────────
#  Per-engine ensure functions
# ─────────────────────────────────────────────────────────────────────────────

def _ensure_piper_binary() -> None:
    if PIPER_BIN.exists():
        return
    log("\n[Piper] Binary not found — downloading...")
    zip_path = PIPER_DIR / "piper_win.zip"
    _download(PIPER_RELEASE, zip_path, "piper binary (Windows x64)")
    log("  Extracting...")
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(PIPER_DIR / "bin")

    # Move everything from the nested piper/ folder up one level
    nested = PIPER_DIR / "bin" / "piper"
    if nested.exists():
        for item in nested.iterdir():
            dest = PIPER_DIR / "bin" / item.name
            if not dest.exists():
                shutil.move(str(item), str(dest))
        shutil.rmtree(str(nested), ignore_errors=True)

    zip_path.unlink(missing_ok=True)
    log(f"  Piper ready → models/piper/bin/piper.exe")


def _ensure_piper_voice(voice_name: str) -> None:
    onnx   = piper_voice_path(voice_name)
    config = onnx.with_suffix(".onnx.json")
    if onnx.exists() and config.exists():
        return
    urls = PIPER_VOICES.get(voice_name)
    if not urls:
        raise ValueError(f"Unknown piper voice: {voice_name}")
    log(f"\n[Piper] Voice '{voice_name}' not found — downloading...")
    _download(urls["onnx"],   onnx,   f"{voice_name}.onnx")
    _download(urls["config"], config, f"{voice_name}.onnx.json")
    log(f"  Voice ready → models/piper/voices/{voice_name}.onnx")


def _ensure_vosk_model(model_name: str) -> None:
    dest = vosk_model_path(model_name)
    if dest.exists():
        return
    url = VOSK_MODELS.get(model_name)
    if not url:
        raise ValueError(f"Unknown Vosk model: {model_name}")
    log(f"\n[Vosk] Model '{model_name}' not found — downloading...")
    zip_path = VOSK_DIR / f"{model_name}.zip"
    _download(url, zip_path, model_name)
    log("  Extracting...")
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(VOSK_DIR)
    zip_path.unlink(missing_ok=True)
    log(f"  Vosk ready → models/vosk/{model_name}/")


def _ensure_whisper_model(model_name: str) -> None:
    """
    openai-whisper handles its own download into the cache dir.
    We trigger it at startup so it doesn't happen mid-conversation.
    """
    if not _pkg_available("whisper"):
        raise RuntimeError("whisper not installed. Run: pip install openai-whisper")

    cache = whisper_cache_dir() / model_name
    if cache.exists() and any(cache.iterdir()):
        return  # already cached

    log(f"\n[Whisper] Model '{model_name}' not cached — downloading...")
    log( "  This may take a minute. Cached for future runs.")
    import whisper
    _ = whisper.load_model(
        model_name,
        device="cpu",
        download_root=str(whisper_cache_dir()),
    )
    log(f"  Whisper ready → models/whisper/{model_name}/")


# ─────────────────────────────────────────────────────────────────────────────
#  Public API
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class IniyaProfile:
    tier:       int
    tier_label: str
    hardware:   HardwareInfo
    stt:        dict
    stt_live:   dict
    tts:        dict
    warnings:   list

    # Convenience path accessors — use these instead of building paths manually
    def stt_model_path(self) -> Optional[Path]:
        """Absolute path to Vosk model dir. None for whisper (managed internally)."""
        if self.stt["engine"] == "vosk":
            return vosk_model_path(self.stt["model"])
        return None

    def stt_live_model_path(self) -> Path:   # always vosk, always a path
        return vosk_model_path(self.stt_live["model"])

    def tts_voice_path(self) -> Path:
        return piper_voice_path(self.tts["voice"])

    def tts_bin_path(self) -> Path:
        return piper_bin_path()

    def whisper_cache(self) -> Path:
        return whisper_cache_dir()


def get_profile(verbose: bool = False, force_tier: Optional[int] = None) -> IniyaProfile:

    hw = detect_hardware()

    if force_tier is not None:
        scored_tier = force_tier
    else:
        scored_tier = _score_tier(hw)

    final_tier, config = _apply_availability(scored_tier, hw)

    warnings = []
    if not hw.whisper_available and scored_tier >= 2:
        warnings.append(
            "openai-whisper not installed — fell back to Vosk. "
            "Run: pip install openai-whisper"
        )
    if not hw.vosk_available and config["stt"]["engine"] == "vosk":
        warnings.append("vosk not installed. Run: pip install vosk")

    profile = IniyaProfile(
        tier       = final_tier,
        tier_label = TIERS[final_tier]["label"],
        hardware   = hw,
        stt        = config["stt"],
        stt_live   = config["stt_live"],
        tts        = config["tts"],
        warnings   = warnings,
    )

    if verbose:
        _log_profile(profile)

    return profile


def ensure_models(profile: IniyaProfile) -> None:
    """
    Downloads any missing binaries/models for the given profile.
    Safe to call every launch — skips files that already exist.
    """
    log("[device_profile] Checking models...")

    _ensure_piper_binary()
    _ensure_piper_voice(profile.tts["voice"])

    # always download vosk — needed for live transcription on every tier
    _ensure_vosk_model(profile.stt_live["model"])

    if profile.stt["engine"] == "whisper":
        _ensure_whisper_model(profile.stt["model"])

    log("[device_profile] All models ready.\n")


def get_profile_json() -> str:
    """JSON dump for IPC with the Node/Vue frontend."""
    p = get_profile()
    return json.dumps({
        "tier":       p.tier,
        "tier_label": p.tier_label,
        "hardware":   asdict(p.hardware),
        "stt": {
            **p.stt,
            "model_path":        str(p.stt_model_path() or ""),
            "whisper_cache_dir": str(p.whisper_cache()),
        },
        "tts": {
            **p.tts,
            "voice_path": str(p.tts_voice_path()),
            "bin_path":   str(p.tts_bin_path()),
        },
        "warnings": p.warnings,
    }, indent=2)


def _log_profile(p: IniyaProfile) -> None:
    hw  = p.hardware
    sep = "─" * 54
    gpu_str = (
        f"{hw.cuda_device} ({hw.cuda_vram_mb} MB VRAM)"
        if hw.cuda_device else "none"
    )
    stt_device = p.stt.get("device", "—")
    log(f"\n{sep}")
    log(f"  Iniya  —  Tier {p.tier}  ({p.tier_label.upper()})")
    log(sep)
    log(f"  RAM    : {hw.ram_available_mb} MB free / {hw.ram_total_mb} MB total")
    log(f"  CPU    : {hw.cpu_cores} cores")
    log(f"  GPU    : {gpu_str}")
    log(f"  Models : {MODELS_DIR.relative_to(THIS_DIR)}")
    log("")
    log(f"  STT    : {p.stt['engine']}  →  {p.stt.get('model', '')}  [{stt_device}]")
    log(f"           {p.stt['note']}")
    log("")
    log(f"  TTS    : {p.tts['engine']}  →  {p.tts['voice']}")
    log(f"           {p.tts['note']}")
    if p.warnings:
        log("")
        for w in p.warnings:
            log(f"  !  {w}")
    log(sep + "\n")


# ─────────────────────────────────────────────────────────────────────────────
#  CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--json" in sys.argv:
        log(get_profile_json())
    elif "--download" in sys.argv:
        p = get_profile(verbose=True)
        ensure_models(p)
    else:
        get_profile(verbose=True)