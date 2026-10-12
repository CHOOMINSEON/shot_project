"""Reproducible comparison on a short recording with a human-verified transcript."""
import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio.settings import DATA
from studio.media import probe


def normalized(text):
    return re.sub(r'[^가-힣a-zA-Z0-9]', '', text).lower()


def character_error_rate(reference, hypothesis):
    reference, hypothesis = normalized(reference), normalized(hypothesis)
    if not reference:
        raise ValueError('검증용 정답 대본을 입력해 주세요.')
    previous = list(range(len(hypothesis) + 1))
    for i, char in enumerate(reference, 1):
        current = [i]
        for j, other in enumerate(hypothesis, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (char != other)))
        previous = current
    return previous[-1] / len(reference)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('video', type=Path)
    parser.add_argument('reference', type=Path)
    parser.add_argument('--models', nargs='+', choices=['tiny', 'base', 'small', 'medium'], default=['medium'])
    parser.add_argument('--vocabulary', default='')
    parser.add_argument('--output', type=Path, default=DATA / 'transcription-check.json')
    args = parser.parse_args()
    if probe(args.video)['duration'] > 120:
        raise SystemExit('Use a sample up to 120 seconds with a human-verified reference.')
    audio = np.frombuffer(subprocess.check_output(['ffmpeg', '-v', 'error', '-protocol_whitelist', 'file,pipe',
                          '-i', str(args.video.resolve()), '-f', 's16le', '-ar', '16000', '-ac', '1', '-']),
                          dtype='<i2').astype(np.float32) / 32768.
    reference = args.reference.read_text(encoding='utf-8').strip()
    results = []
    for name in args.models:
        directory = DATA / 'models' / f'whisper-{name}'
        if name == 'base' and not directory.exists():
            directory = DATA / 'models' / 'whisper'  # Previous installation kept for comparison.
        model = WhisperModel(str(directory), device='cpu', compute_type='int8', cpu_threads=2)
        started = time.monotonic()
        segments, _ = model.transcribe(audio, language='ko', beam_size=5, word_timestamps=True, vad_filter=True,
                                     initial_prompt=args.vocabulary, hotwords=args.vocabulary,
                                     condition_on_previous_text=False, hallucination_silence_threshold=1.)
        recognized = ''.join(s.text for s in segments).strip()
        result = {'model': name, 'reference': reference, 'recognized': recognized,
                  'character_error_rate': round(character_error_rate(reference, recognized), 4),
                  'seconds': round(time.monotonic() - started, 2),
                  'notice': '공백·문장부호 제외 문자 오류율입니다. 단일 샘플을 전체 영상 정확도로 일반화할 수 없습니다.'}
        print(json.dumps(result, ensure_ascii=False), flush=True)
        results.append(result)
        del model
    args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
