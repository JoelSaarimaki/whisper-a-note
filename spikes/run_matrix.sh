#!/bin/sh
# Phase 0 comparison runs; one JSON summary line per run in spikes/results/matrix.jsonl
export PYTHONIOENCODING=utf-8 HF_HUB_DISABLE_SYMLINKS_WARNING=1 PYTHONWARNINGS=ignore
FI="--audio spikes/test_audio/kuulumiset.wav --language fi --context fi"
EN="--audio spikes/test_audio/dialogue_long.wav --language en --context en"
run() { uv run python spikes/pipeline_spike.py "$@" 2>/dev/null | tail -1 >> spikes/results/matrix.jsonl; }
mkdir -p spikes/results; : > spikes/results/matrix.jsonl
# 1. Whisper models (Finnish, context as initial prompt + hotwords)
for m in small medium large-v3-turbo large-v3; do run $FI --model $m --pyannote skip; done
# 2. Context passing (Finnish, turbo)
for p in none initial hotwords; do run $FI --model large-v3-turbo --prompt-mode $p --pyannote skip; done
run $FI --model large-v3-turbo --cond-prev off --pyannote skip
# 3. Context over a long recording (English TTS, 8.6 min)
for p in none initial hotwords both; do run $EN --model small --prompt-mode $p --pyannote skip; done
# 4. pyannote versions, with and without the speaker count
for v in community-1 3.1; do
  run $FI --model small --pyannote $v
  run $FI --model small --pyannote $v --num-speakers 4 --tag _n4
done
run $EN --model small --pyannote community-1
run $EN --model small --pyannote 3.1
echo DONE >> spikes/results/matrix.jsonl
