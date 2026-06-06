import subprocess
import sys
import shutil
from pathlib import Path


VENV_DIR = Path(".venv")
VENV_PYTHON = VENV_DIR / "Scripts" / "python.exe"
UI_PATH = Path(__file__).resolve().parent / "GUI" / "ui_vue"


def ensure_windows():
    if not sys.platform.startswith("win"):
        print("❌ Project Iniya is only supported on Windows.")
        sys.exit(1)


def ensure_venv():
    """Phase 1: Bootstrap into venv, then re-run."""
    if sys.prefix != sys.base_prefix:
        return  # Already inside a venv

    if not VENV_DIR.exists():
        print("📦 Creating virtual environment...")
        subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)
        print("✅ Virtual environment created")

    print("🔁 Restarting setup inside virtual environment...")
    subprocess.run([str(VENV_PYTHON), *sys.argv], check=True)
    sys.exit(0)


def run(cmd, **kwargs):
    """Thin wrapper so call sites stay clean."""
    subprocess.run(cmd, check=True, **kwargs)


def ensure_torch():
    """
    Install PyTorch with CUDA only when needed.
    Handles three cases:
      - Not installed at all
      - Installed but without CUDA support
      - Already correct — skip entirely
    """
    try:
        import torch  # noqa: PLC0415
        if torch.cuda.is_available():
            print("✅ PyTorch (CUDA) already available — skipping")
            return
        print("⚠️  PyTorch found but CUDA unavailable — reinstalling...")
    except ImportError:
        print("📦 PyTorch not found — installing...")

    # Uninstall whatever is there (safe even if nothing is installed)
    run([sys.executable, "-m", "pip", "uninstall", "-y", "torch", "torchvision", "torchaudio"])
    run([sys.executable, "-m", "pip", "install", "-r", "requirements/torch_cu130.txt"])
    print("✅ PyTorch (CUDA 13.0) installed")


def main_setup():
    """Phase 2: Runs only inside venv."""
    print("=== Project Iniya Setup ===")
    print(f"🐍 Python: {sys.executable}")

    # Upgrade pip tooling
    run([sys.executable, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])
    print("✅ pip upgraded")

    # Python dependencies
    run([sys.executable, "-m", "pip", "install", "-r", "requirements/requirements.txt"])
    print("✅ Python dependencies installed")

    # PyTorch — only installs/reinstalls if needed
    ensure_torch()

    # Windows-specific setup
    run([sys.executable, "Setup/setup_windows.py"])
    print("✅ Windows setup complete")

    # Asset downloads
    run([sys.executable, "Setup/setup_assets.py"])
    print("✅ Assets downloaded")

    # Frontend — uses whatever package.json already declares
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if not npm:
        print("❌ npm not found — install Node.js and re-run setup.")
        sys.exit(1)

    run([npm, "install"], cwd=UI_PATH)
    run([npm, "run", "build"], cwd=UI_PATH)
    print("✅ GUI built")


if __name__ == "__main__":
    ensure_windows()
    ensure_venv()
    main_setup()
    print("🎉 Setup complete!")