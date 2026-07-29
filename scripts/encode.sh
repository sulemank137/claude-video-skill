#!/usr/bin/env bash
# PNG sequence -> H.264. crf 16 because UI plates are full of hairline borders
# and 1px chart strokes that a looser quantiser turns to mush.
set -eu
FRAMES=${1:?usage: encode.sh FRAMES_DIR OUT.mp4 [FPS]}
OUT=${2:?usage: encode.sh FRAMES_DIR OUT.mp4 [FPS]}
FPS=${3:-30}
ffmpeg -v error -stats -r "$FPS" -i "$FRAMES/%05d.png" \
    -c:v libx264 -pix_fmt yuv420p -crf 16 -preset slow \
    -movflags +faststart "$OUT" -y
ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$OUT"
