"""Command-line viXTTS: script text + reference voice -> WAV (+ sentence timings).

Example:
    python tts_cli.py --text script.txt --voice my_voice.wav --out audio.wav \
        --timings timings.json
"""

import argparse
import json
import os
import subprocess
import sys
import time

import torch
import torchaudio
from huggingface_hub import hf_hub_download, snapshot_download
from underthesea import sent_tokenize

from TTS.tts.configs.xtts_config import XttsConfig
from TTS.tts.models.xtts import Xtts
from vi_normalizer import TTSnorm

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SAMPLE_RATE = 24000
REQUIRED_FILES = ["model.pth", "config.json", "vocab.json", "speakers_xtts.pth"]


def get_device(requested):
    if requested != "auto":
        return requested
    if torch.cuda.is_available():
        return "cuda"
    # XTTS is unreliable on Apple MPS, so default to CPU on macOS.
    return "cpu"


def load_model(model_dir, device, repo_id="capleaf/viXTTS"):
    os.makedirs(model_dir, exist_ok=True)
    if not all(f in os.listdir(model_dir) for f in REQUIRED_FILES):
        print(f"Downloading model from {repo_id}...", file=sys.stderr)
        snapshot_download(repo_id=repo_id, repo_type="model", local_dir=model_dir)
        hf_hub_download(repo_id="coqui/XTTS-v2", filename="speakers_xtts.pth", local_dir=model_dir)

    config = XttsConfig()
    config.load_json(os.path.join(model_dir, "config.json"))
    model = Xtts.init_from_config(config)
    model.load_checkpoint(config, checkpoint_dir=model_dir, use_deepspeed=False)
    model.to(device)
    model.eval()
    return model


def normalize_vietnamese_text(text):
    return (
        TTSnorm(text)
        .replace("..", ".")
        .replace("!.", "!")
        .replace("?.", "?")
        .replace(" .", ".")
        .replace(" ,", ",")
        .replace('"', "")
        .replace("'", "")
    )


def calculate_keep_len(text):
    """Trim trailing noise on short sentences (same hack as the upstream demo)."""
    word_count = len(text.split())
    num_punct = sum(text.count(p) for p in ".!?,")
    if word_count < 5:
        return 15000 * word_count + 2000 * num_punct
    if word_count < 10:
        return 13000 * word_count + 2000 * num_punct
    return -1


def denoise(voice_path):
    out_dir = os.path.dirname(os.path.abspath(voice_path))
    subprocess.run(["deepFilter", voice_path, "-o", out_dir], check=True)
    return os.path.join(out_dir, os.path.splitext(os.path.basename(voice_path))[0] + "_DeepFilterNet3.wav")


def synthesize(model, text, voice_path, lang="vi", normalize=True, pause=0.25):
    gpt_cond_latent, speaker_embedding = model.get_conditioning_latents(
        audio_path=voice_path,
        gpt_cond_len=model.config.gpt_cond_len,
        max_ref_length=model.config.max_ref_len,
        sound_norm_refs=model.config.sound_norm_refs,
    )
    if normalize and lang == "vi":
        text = normalize_vietnamese_text(text)

    sentences = [s for s in sent_tokenize(text) if s.strip()]
    silence = torch.zeros(int(pause * SAMPLE_RATE))
    chunks, timings, cursor = [], [], 0
    for i, sentence in enumerate(sentences, 1):
        print(f"[{i}/{len(sentences)}] {sentence}", file=sys.stderr)
        out = model.inference(
            text=sentence,
            language=lang,
            gpt_cond_latent=gpt_cond_latent,
            speaker_embedding=speaker_embedding,
            # Values tuned by the viXTTS authors
            temperature=0.3,
            length_penalty=1.0,
            repetition_penalty=10.0,
            top_k=30,
            top_p=0.85,
            enable_text_splitting=True,
        )
        wav = torch.tensor(out["wav"][: calculate_keep_len(sentence)]).cpu()
        timings.append({
            "text": sentence,
            "start": round(cursor / SAMPLE_RATE, 3),
            "end": round((cursor + len(wav)) / SAMPLE_RATE, 3),
        })
        chunks += [wav, silence]
        cursor += len(wav) + len(silence)

    return torch.cat(chunks[:-1]).unsqueeze(0), timings


def main():
    parser = argparse.ArgumentParser(description="viXTTS command-line synthesis")
    parser.add_argument("--text", required=True, help="Path to a UTF-8 text file, or '-' for stdin")
    parser.add_argument("--voice", default=os.path.join(SCRIPT_DIR, "assets", "vixtts_sample_female.wav"),
                        help="Reference voice WAV (6-30s of clean speech)")
    parser.add_argument("--out", default="output.wav", help="Output WAV path")
    parser.add_argument("--timings", help="Optional JSON file for per-sentence start/end times")
    parser.add_argument("--lang", default="vi")
    parser.add_argument("--model-dir", default=os.path.join(SCRIPT_DIR, "model"))
    parser.add_argument("--device", default="auto", choices=["auto", "cpu", "mps", "cuda"])
    parser.add_argument("--denoise", action="store_true", help="Denoise the reference voice with DeepFilterNet")
    parser.add_argument("--no-normalize", action="store_true", help="Skip Vietnamese text normalization")
    parser.add_argument("--pause", type=float, default=0.25, help="Silence between sentences (seconds)")
    args = parser.parse_args()

    text = sys.stdin.read() if args.text == "-" else open(args.text, encoding="utf-8").read()
    voice = denoise(args.voice) if args.denoise else args.voice
    device = get_device(args.device)

    started = time.time()
    model = load_model(args.model_dir, device)
    print(f"Model loaded on {device} in {time.time() - started:.1f}s", file=sys.stderr)

    started = time.time()
    wav, timings = synthesize(model, text, voice, args.lang, not args.no_normalize, args.pause)
    torchaudio.save(args.out, wav, SAMPLE_RATE)
    duration = wav.shape[-1] / SAMPLE_RATE
    elapsed = time.time() - started
    print(f"Saved {args.out}: {duration:.1f}s audio in {elapsed:.1f}s (RTF {elapsed / duration:.2f})", file=sys.stderr)

    if args.timings:
        with open(args.timings, "w", encoding="utf-8") as f:
            json.dump(timings, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
