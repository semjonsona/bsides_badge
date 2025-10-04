import os
import shutil

# don't ask...
try:
    import nvidia.cudnn
    cudnn_path = os.path.join(os.path.dirname(nvidia.cudnn.__file__), 'bin')
    os.environ['PATH'] = cudnn_path + ';' + os.environ['PATH']
except:
    pass

import gc
import json
import struct
import re
import util
import torch
import os
import subprocess
from pathlib import Path

RESOLUTION = 20  # ms per frame
TITLE_SIZE = 64

ORIGIN_DIR = "audio/origin"
VOCALS_DIR = "audio/dm"
JSON_DIR = "audio/json"
TXT_DIR = "audio/txt"
CORRECTED_DIR = "audio/txt_corrected"

MODEL_NAME = "large-v3-turbo"
DEVICE = "cuda" if torch.cuda.is_available() else 'cpu'  # noVIDEO support


def isolate_vocals(model="htdemucs_ft"):
    global ORIGIN_DIR, VOCALS_DIR
    output_dir = Path(VOCALS_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    for file in Path(ORIGIN_DIR).iterdir():
        if file.suffix.lower() not in [".mp3", ".wav", ".flac", ".ogg"]:
            continue

        song_name = file.stem
        target_vocals = output_dir / (song_name + '.wav')
        if target_vocals.exists():
            print(f"{song_name}: skipping vocals isolation")
            continue

        print(f"{song_name}: isolating vocals")
        subprocess.run([
            "demucs",
            "-n", model,
            "--two-stems", "vocals",
            "-o", str(output_dir),
            str(file)
        ], check=True)

        no_vocals = output_dir / model / song_name / "no_vocals.wav"
        shutil.rmtree(no_vocals, ignore_errors=True)
        vocals = output_dir / model / song_name / "vocals.wav"
        shutil.move(vocals, output_dir / (song_name + '.wav'))


def transcribe_audio():
    import whisperx
    print("model_name", MODEL_NAME)
    model = whisperx.load_model(MODEL_NAME, DEVICE, compute_type='float32')

    for fn in Path(VOCALS_DIR).iterdir():
        output_txt = os.path.join(JSON_DIR, f"{fn.stem}.txt")
        if os.path.exists(output_txt):
            print(f"{fn.stem}: skipping transcribing")
            continue

        print(f"{fn.stem}: transcribing")
        audio = whisperx.load_audio(fn)
        result = model.transcribe(audio, language='en')

        model_a, metadata = whisperx.load_align_model(
            language_code='en', device=DEVICE
        )
        result_aligned = whisperx.align(
            result["segments"], model_a, metadata, audio, device=DEVICE
        )
        with open(output_txt, "w", encoding="utf-8") as f:
            json.dump(result_aligned, f, indent=2, ensure_ascii=False)


def json_to_txt():
    print('Json to text')
    os.makedirs(TXT_DIR, exist_ok=True)
    for fname in os.listdir(JSON_DIR):
        fpath = os.path.join(JSON_DIR, fname)
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
        lines = []
        for seg in data.get("word_segments", []):
            start = seg["start"]
            end = seg["end"]
            word = seg["word"]
            lines.append(f"{start:.3f},{end:.3f},{word}")
        outpath = os.path.join(TXT_DIR, os.path.splitext(fname)[0] + ".txt")
        with open(outpath, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))


def get_lyrics(audio_path):
    from mutagen import File
    audio = File(audio_path)

    # Common lyric tags
    lyric_tags = ["UNSYNCEDLYRICS", "lyrics", "LYRICS", "USLT", "USLT::eng", "COMM"]  # MP3/FLAC variations
    if not audio.tags:
        return None

    for tag in lyric_tags:
        if tag in audio.tags:
            return audio.tags[tag].text if hasattr(audio.tags[tag], "text") else str(audio.tags[tag])
    return None


def correct_transcription():
    # maybe just host it yourself
    # llama-server.exe --host 127.0.0.1 --port 7860 --ctx-size 32768 --n-gpu-layers 99 --model Qwen3-4B-Instruct-2507-Q6_K.gguf
    import requests
    import os

    print('Correcting does not work yet...')

    os.makedirs(TXT_DIR, exist_ok=True)

    port = 7860

    for fn in os.listdir(TXT_DIR):
        audio_path = None
        for f in ['.mp3', '.flac', '.wav']:
            audio_path = os.path.join(ORIGIN_DIR, os.path.splitext(fn)[0] + f)
            if os.path.exists(audio_path):
                break
        if not audio_path:
            raise Exception('Original file not found')

        lyrics = get_lyrics(audio_path)
        if not lyrics:
            print(f'{fn}: lyrics not found')
            continue

        print(f'{fn}: correcting')
        with open(os.path.join(TXT_DIR, fn), "r", encoding="utf-8") as f:
            timestamped = f.read()
        timestamped_lined = "\n".join([f"{i+1}:{line}" for i, line in enumerate(timestamped.splitlines())])

        prompt = f"""<human>Task: correct the minor mistakes of TIMESTAMPED,
using ORIGINAL. Fix minor issues, like one or multiple incorrect words at a time,
but do not attempt to insert sections of lyrics missing from the transcription.
Remove unnecessary words like "Thank you" or "Bye" if they are not in the lyrics.

Format: Output the corrected TIMESTAMPED and nothing else.

<TIMESTAMPED>
{timestamped}
</TIMESTAMPED>

<ORIGINAL>
{lyrics}
</ORIGINAL>
</human>
<assistant>"""

        resp = requests.post(
            f"http://127.0.0.1:{port}/completion",
            json={
                "prompt": prompt,
                "n_predict": 12000,
                "temperature": 0.0,
                'end': 'END'
            },
            timeout=300
        )
        data = resp.json()
        corrected = data["content"].strip()

        with open(os.path.join(CORRECTED_DIR, fn), "w", encoding="utf-8") as f:
            f.write(corrected)


def song_name(fn):
    base = re.sub(r"_words.*\.txt$", "", fn)
    base = os.path.splitext(base)[0]
    base = re.sub(r"\(feat[^)]*\)", "", base, flags=re.IGNORECASE).strip()
    name = base.split(" - ")[-1].strip()
    print(f'Song name: {name}')
    return name


def encode_word(word, duration):
    pw = util.prepare_text(word.strip(' \t')).encode()
    pw = pw[:50]
    if duration < 256:
        return struct.pack("<BB", duration, len(pw)) + pw
    else:
        return encode_word(word, 255) + encode_word(word, duration - 255)


def txt_to_bin():
    print('Packing')
    bb = bytearray()
    for fn in os.listdir(TXT_DIR):
        with open(os.path.join(TXT_DIR, fn), "r", encoding="utf-8") as f:
            lines = f.read().splitlines()

        present_fr = 0
        sb = bytearray()
        for line in lines:
            if not line.strip():
                continue
            start_str, end_str, word = line.split(",", 2)
            start_fr = int(float(start_str) / (RESOLUTION / 1000))
            end_fr = int(float(end_str) / (RESOLUTION / 1000))

            if present_fr < start_fr:
                sb += encode_word('', start_fr - present_fr)
                present_fr = start_fr
            sb += encode_word(word, end_fr - present_fr)
            present_fr = end_fr
        goodsn = util.prepare_text(song_name(fn))
        print(f'len: {len(sb)}')
        bb += goodsn[:TITLE_SIZE].encode().ljust(TITLE_SIZE, b'\0')
        bb += struct.pack("<I", len(sb))
        bb += sb
    print('songs.bin size: ', len(bb))
    open('songs.bin', 'wb').write(bb)


if __name__ == '__main__':
    #isolate_vocals()
    #transcribe_audio()
    #json_to_txt()
    #correct_transcription()
    txt_to_bin()
