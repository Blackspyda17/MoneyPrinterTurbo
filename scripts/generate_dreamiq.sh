#!/usr/bin/env bash
# Generate a DreamIQ marketing video with the project's standard settings.
#
# Usage:
#   scripts/generate_dreamiq.sh "Tema del video" [es|en|pt] [output-name]
#
# Defaults: language es, output outputs/dreamiq_<slug>.mp4
# Settings: pixabay, es-GT Andres voice, 9:16, edge subtitles with
# word-by-word highlighting (from config.toml), Whisper brand bias prompt.
set -euo pipefail

cd "$(dirname "$0")/.."

SUBJECT="${1:?usage: scripts/generate_dreamiq.sh \"subject\" [lang] [name]}"
LANG_CODE="${2:-es}"
NAME="${3:-}"

case "$LANG_CODE" in
  es) VOICE="es-GT-AndresNeural-Male" ;;
  en) VOICE="en-US-AriaNeural-Female" ;;
  pt) VOICE="pt-BR-FranciscaNeural-Female" ;;
  *) echo "unsupported language: $LANG_CODE (use es|en|pt)"; exit 1 ;;
esac

if [ -z "$NAME" ]; then
  NAME=$(echo "$SUBJECT" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]+/-/g' | sed 's/^-//;s/-$//')
  NAME="${NAME:-video}"
fi

mkdir -p outputs

LOG_FILE="/tmp/dreamiq_generate_$$.log"
echo "==> generating: '$SUBJECT' ($LANG_CODE) -> outputs/dreamiq_${NAME}.mp4"
if ! uv run python cli.py \
  --video-subject "$SUBJECT" \
  --video-language "$LANG_CODE" \
  --voice-name "$VOICE" \
  --video-aspect "9:16" \
  --video-source "pixabay" \
  --font-name "MicrosoftYaHeiBold.ttc" \
  --subtitle-enabled \
  2>"$LOG_FILE" | tee /tmp/dreamiq_generate_json_$$.log | python3 -c "
import json, sys
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        continue
    if isinstance(data, dict) and 'task_id' in data:
        print(data['task_id'], end='')
        sys.exit(0)
sys.exit(2)
" > /tmp/dreamiq_task_id_$$; then
  echo "!! generation failed — last lines:"
  tail -20 "$LOG_FILE"
  rm -f "$LOG_FILE" /tmp/dreamiq_generate_json_$$.log /tmp/dreamiq_task_id_$$
  exit 1
fi

TASK_ID=$(cat /tmp/dreamiq_task_id_$$)
if [ -n "$TASK_ID" ] && [ -f "storage/tasks/$TASK_ID/final-1.mp4" ]; then
  cp "storage/tasks/$TASK_ID/final-1.mp4" "outputs/dreamiq_${NAME}.mp4"
  echo "==> done: outputs/dreamiq_${NAME}.mp4"
else
  echo "!! could not locate output video (task_id=$TASK_ID)"
  tail -20 "$LOG_FILE"
  exit 1
fi
rm -f "$LOG_FILE" /tmp/dreamiq_generate_json_$$.log /tmp/dreamiq_task_id_$$
