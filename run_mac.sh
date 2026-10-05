#!/usr/bin/env bash
# macOS launcher for viXTTS. Usage:
#   ./run_mac.sh                 # web UI at http://127.0.0.1:5003
#   ./run_mac.sh cli --text script.txt --voice me.wav --out audio.wav
set -euo pipefail
cd "$(dirname "$0")"

PYTHON_VERSION=3.10

if [[ "$(uname)" != "Darwin" ]]; then
    echo "This script is for macOS. Use ./run.sh on Ubuntu/WSL2."
    exit 1
fi

if ! command -v brew &> /dev/null; then
    echo "Homebrew is required: https://brew.sh"
    exit 1
fi

for formula in "python@${PYTHON_VERSION}" ffmpeg; do
    if ! brew list --versions "$formula" &> /dev/null; then
        echo "Installing $formula with Homebrew..."
        brew install "$formula"
    fi
done

PYTHON="$(brew --prefix python@${PYTHON_VERSION})/bin/python${PYTHON_VERSION}"

if [ ! -f .env/ok ]; then
    echo "Setting up the environment (first run only)..."
    rm -rf .env
    "$PYTHON" -m venv .env
    source .env/bin/activate
    pip install -q --upgrade pip wheel setuptools
    git submodule update --init --recursive
    (cd TTS && git fetch --tags -q && git checkout -q 0.1.1)
    # TTS 0.22 breaks on torch>=2.6 (torch.load weights_only) and torchaudio>=2.9.
    echo "Installing PyTorch..."
    pip install -q -c constraints-mac.txt torch torchaudio numpy
    echo "Installing TTS..."
    pip install -q --use-deprecated=legacy-resolver -c constraints-mac.txt -e TTS
    echo "Installing other requirements..."
    pip install -q -c constraints-mac.txt -r requirements-mac.txt
    touch .env/ok
else
    source .env/bin/activate
fi

# Let PyTorch fall back to CPU for ops Apple MPS does not support.
export PYTORCH_ENABLE_MPS_FALLBACK=1

if [[ "${1:-}" == "cli" ]]; then
    shift
    python tts_cli.py "$@"
else
    python vixtts_demo.py "$@"
fi
