"""
Download Qwen2.5-14B-Instruct Q4_K_M (split) and nomic-embed-text GGUF models.
Files are saved to ~/models/ by default (cross-platform).
Override with: LOCAL_MODEL_PATH env var or edit MODELS_DIR below.
"""
import os
from pathlib import Path
from huggingface_hub import hf_hub_download

# ~/models works on Windows, macOS, and Linux automatically
MODELS_DIR = Path(os.environ.get("LOCAL_MODELS_DIR", str(Path.home() / "models")))
MODELS_DIR.mkdir(parents=True, exist_ok=True)

# ── 1. Qwen2.5-14B-Instruct Q4_K_M (3 shards) ──────────────────────────────
QWEN_REPO  = "Qwen/Qwen2.5-14B-Instruct-GGUF"
QWEN_FILES = [
    "qwen2.5-14b-instruct-q4_k_m-00001-of-00003.gguf",
    "qwen2.5-14b-instruct-q4_k_m-00002-of-00003.gguf",
    "qwen2.5-14b-instruct-q4_k_m-00003-of-00003.gguf",
]

print("=" * 60)
print("Downloading Qwen2.5-14B-Instruct Q4_K_M (3 shards)...")
print("=" * 60)
for fname in QWEN_FILES:
    dest = MODELS_DIR / fname
    if dest.exists():
        print(f"  [SKIP] {fname} already exists")
        continue
    print(f"  Downloading {fname} ...")
    hf_hub_download(
        repo_id=QWEN_REPO,
        filename=fname,
        local_dir=str(MODELS_DIR),
        local_dir_use_symlinks=False,
    )
    print(f"  [OK] {fname}")

# ── 2. nomic-embed-text-v1.5 Q4_K_M ─────────────────────────────────────────
NOMIC_REPO = "nomic-ai/nomic-embed-text-v1.5-GGUF"

print()
print("=" * 60)
print("Checking nomic-embed-text-v1.5-GGUF file list...")
print("=" * 60)
from huggingface_hub import list_repo_files
nomic_files = list(list_repo_files(NOMIC_REPO))
print("Available files:")
for f in nomic_files:
    print(f"  {f}")

# Pick Q4_K_M variant
nomic_target = next(
    (f for f in nomic_files if "q4_k_m" in f.lower() and f.endswith(".gguf")),
    None,
)
if nomic_target is None:
    # fallback: first gguf
    nomic_target = next((f for f in nomic_files if f.endswith(".gguf")), None)

if nomic_target:
    dest = MODELS_DIR / nomic_target
    if dest.exists():
        print(f"\n[SKIP] {nomic_target} already exists")
    else:
        print(f"\nDownloading {nomic_target} ...")
        hf_hub_download(
            repo_id=NOMIC_REPO,
            filename=nomic_target,
            local_dir=str(MODELS_DIR),
            local_dir_use_symlinks=False,
        )
        print(f"[OK] {nomic_target}")
else:
    print("ERROR: No GGUF file found in nomic repo!")

print()
print("=" * 60)
print(f"Download complete. Files in {MODELS_DIR}:")
for f in sorted(MODELS_DIR.iterdir()):
    size_mb = f.stat().st_size / 1024 / 1024
    print(f"  {f.name:60s}  {size_mb:8.1f} MB")
print("=" * 60)
