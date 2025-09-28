from datetime import datetime
import os
import whisper
import json
import struct
import re

import util

RESOLUTION = 20  # ms per frame
TITLE_SIZE = 64

def song_name(fn):
    base = re.sub(r"_words.*\.txt$", "", fn)
    base = os.path.splitext(base)[0]
    base = re.sub(r"\(feat[^)]*\)", "", base, flags=re.IGNORECASE).strip()
    name = base.split("-")[-1].strip()
    print(f'Song name: {name}')
    return name


def encode_word(word, duration):
    pw = util.prepare_text(word.strip(' \t')).encode()
    if duration < 256:
        return struct.pack("<BB", duration, len(pw)) + pw
    else:
        return encode_word(word, 255) + encode_word(word, duration - 255)


if __name__ == '__main__':
    AUDIO_DIR = "audio"
    model_name = 'small'  # tiny, small
    print("model_name", model_name)
    model = whisper.load_model(model_name) # small
    for fn in os.listdir(AUDIO_DIR):
        if not fn.lower().endswith(".mp3") and not fn.lower().endswith(".flac"):
            continue

        audio_path = os.path.join(AUDIO_DIR, fn)
        output_txt = os.path.join(AUDIO_DIR, fn + f"_words{model_name}.txt")

        if os.path.exists(output_txt):
            continue

        print(f"Processing {fn}...")

        result = model.transcribe('audio/' + fn, word_timestamps=True)
        with open(output_txt, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

    print('Packing')
    bb = bytearray()
    for fn in os.listdir(AUDIO_DIR):
        if not fn.lower().endswith(f"_words{model_name}.txt"):
            continue
        song_json = json.loads(open(AUDIO_DIR + '/' + fn, 'r').read())

        present_fr = 0
        sb = bytearray()
        for seg in song_json.get("segments", []):
            for w in seg.get("words", []):
                start_fr = int(w["start"] / (RESOLUTION / 1000))
                end_fr = int(w["end"] / (RESOLUTION / 1000))
                if present_fr < start_fr:
                    sb += encode_word('', start_fr - present_fr)
                    present_fr = start_fr
                sb += encode_word(w["word"], end_fr - present_fr)
                present_fr = end_fr

        goodsn = util.prepare_text(song_name(fn))
        bb += goodsn[:TITLE_SIZE].encode().ljust(TITLE_SIZE, b'\0')
        bb += struct.pack("<I", len(sb))
        bb += sb
    print('songs.bin size: ', len(bb))
    open('songs.bin', 'wb').write(bb)
