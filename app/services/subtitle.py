import json
import os.path
import re
from timeit import default_timer as timer

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None
from loguru import logger

from app.config import config
from app.utils import utils

model_size = config.whisper.get("model_size", "large-v3")
device = config.whisper.get("device", "cpu")
compute_type = config.whisper.get("compute_type", "int8")
model = None

# Safety-net corrections for known Whisper mishearings (e.g. "Dreamy Q" -> "DreamIQ").
# The primary bias comes from the configured [whisper] initial_prompt (see config.toml);
# this catches any mishearings that still slip through.
_DREAMIQ_CORRECTIONS = [
    (re.compile(r"dreamy q", re.IGNORECASE), "DreamIQ"),
    (re.compile(r"dream iq", re.IGNORECASE), "DreamIQ"),
    (re.compile(r"dream i\.q\.", re.IGNORECASE), "DreamIQ"),
    (re.compile(r"dreamy", re.IGNORECASE), "DreamIQ"),
]


def _correct_brand_names(text: str) -> str:
    """Fix known Whisper mishearings of the DreamIQ brand name."""
    for pattern, replacement in _DREAMIQ_CORRECTIONS:
        text = pattern.sub(replacement, text)
    return text


def _whisper_initial_prompt():
    """Return the configured Whisper initial_prompt, or None when unset."""
    return config.whisper.get("initial_prompt") or None


def create_enhanced_subtitles(audio_file, subtitle_file: str = "", params=None):
    """
    Create enhanced subtitles with word-level timing for word highlighting.
    Uses Whisper word timestamps (same model as the whisper subtitle provider).
    """
    global model
    if WhisperModel is None:
        logger.warning(
            "faster_whisper not available, skipping enhanced subtitle generation"
        )
        return []
    if not model:
        model_path = f"{utils.root_dir()}/models/whisper-{model_size}"
        model_bin_file = f"{model_path}/model.bin"
        if not os.path.isdir(model_path) or not os.path.isfile(model_bin_file):
            model_path = model_size

        logger.info(
            f"loading model: {model_path}, device: {device}, compute_type: {compute_type}"
        )
        try:
            model = WhisperModel(
                model_size_or_path=model_path, device=device, compute_type=compute_type
            )
        except Exception as e:
            logger.error(
                f"failed to load model: {e} \n\n"
                f"********************************************\n"
                f"this may be caused by network issue. \n"
                f"please download the model manually and put it in the 'models' folder. \n"
                f"see [README.md FAQ](https://github.com/harry0703/MoneyPrinterTurbo) for more details.\n"
                f"********************************************\n\n"
            )
            return []

    logger.info(f"start enhanced subtitle generation, output file: {subtitle_file}")
    if not subtitle_file:
        subtitle_file = f"{audio_file}.enhanced.json"

    max_chars_per_line = getattr(params, "max_chars_per_line", None) or 40
    max_lines_per_subtitle = getattr(params, "max_lines_per_subtitle", None) or 2
    initial_prompt = getattr(params, "whisper_initial_prompt", None) or _whisper_initial_prompt()

    segments, info = model.transcribe(
        audio_file,
        beam_size=5,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
        **({"initial_prompt": initial_prompt} if initial_prompt else {}),
    )

    logger.info(
        f"detected language: '{info.language}', probability: {info.language_probability:.2f}"
    )

    enhanced_subtitles = []
    current_subtitle = None
    current_words = []

    for segment in segments:
        if not segment.words:
            continue

        for word in segment.words:
            word_text = word.word.strip()
            if not word_text:
                continue

            word_timing = {
                "word": word_text,
                "start": word.start,
                "end": word.end,
                "line": 0,
                "position": 0,
            }

            if current_subtitle is None:
                current_subtitle = {
                    "start_time": word.start,
                    "end_time": word.end,
                    "text": "",
                    "words": [],
                }

            current_words.append(word_timing)
            current_subtitle["words"] = current_words
            current_subtitle["text"] += word_text + " "
            current_subtitle["end_time"] = word.end

            should_break = (
                utils.str_contains_punctuation(word_text)
                or len(current_subtitle["text"])
                > max_chars_per_line * max_lines_per_subtitle
            )

            if should_break:
                enhanced_subtitles.append(
                    _process_enhanced_subtitle(
                        current_subtitle, max_chars_per_line, max_lines_per_subtitle
                    )
                )
                current_subtitle = None
                current_words = []

    if current_subtitle and current_words:
        enhanced_subtitles.append(
            _process_enhanced_subtitle(
                current_subtitle, max_chars_per_line, max_lines_per_subtitle
            )
        )

    enhanced_data = [subtitle for subtitle in enhanced_subtitles]
    for entry in enhanced_data:
        entry["text"] = _correct_brand_names(entry["text"])
        entry["lines"] = [_correct_brand_names(line) for line in entry.get("lines", [])]
        for w in entry.get("words", []):
            w["word"] = _correct_brand_names(w["word"])

    with open(subtitle_file, "w", encoding="utf-8") as f:
        json.dump(enhanced_data, f, ensure_ascii=False, indent=2)

    logger.info(f"enhanced subtitle file created: {subtitle_file}")
    return enhanced_subtitles


def _process_enhanced_subtitle(subtitle_data, max_chars_per_line, max_lines_per_subtitle):
    """Split a subtitle segment into display lines and assign line/position to each word."""
    text = subtitle_data["text"].strip()
    words = subtitle_data["words"]

    display_text = text.replace(", ", " ").replace(",", " ")

    lines = _wrap_text_into_lines(text, max_chars_per_line, max_lines_per_subtitle)
    display_lines = [line.replace(", ", " ").replace(",", " ") for line in lines]

    word_index = 0

    for line_idx, line in enumerate(display_lines):
        line_words = line.strip().split()
        position = 0

        for line_word in line_words:
            while word_index < len(words):
                word_timing = words[word_index]
                timing_word_clean = (
                    word_timing["word"]
                    .replace(".", "")
                    .replace(",", "")
                    .replace("!", "")
                    .replace("?", "")
                    .strip()
                )
                line_word_clean = (
                    line_word.replace(".", "")
                    .replace(",", "")
                    .replace("!", "")
                    .replace("?", "")
                    .strip()
                )

                if timing_word_clean.lower() == line_word_clean.lower():
                    word_timing["line"] = line_idx
                    word_timing["position"] = position
                    position += 1
                    word_index += 1
                    break
                word_index += 1

    return {
        "start_time": subtitle_data["start_time"],
        "end_time": subtitle_data["end_time"],
        "text": display_text,
        "words": words,
        "lines": display_lines,
    }


def _wrap_text_into_lines(text, max_chars_per_line, max_lines):
    """Wrap text into lines respecting word boundaries and comma-based breaks."""
    comma_segments = [
        segment.strip() for segment in text.split(",") if segment.strip()
    ]

    lines = []
    current_line = ""

    for segment in comma_segments:
        words = segment.split()

        for word in words:
            test_line = current_line + (" " if current_line else "") + word

            if len(test_line) <= max_chars_per_line:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                    current_line = word
                else:
                    lines.append(word)
                    current_line = ""

                if len(lines) >= max_lines:
                    break

        if current_line and len(current_line) > max_chars_per_line * 0.6:
            lines.append(current_line)
            current_line = ""

            if len(lines) >= max_lines:
                break

    if current_line and len(lines) < max_lines:
        lines.append(current_line)

    if len(lines) > 1:
        lines = _balance_subtitle_lines(lines, max_chars_per_line)

    return lines


def _balance_subtitle_lines(lines, max_chars_per_line):
    """Balance subtitle line lengths for better center alignment."""
    if len(lines) <= 1:
        return lines

    balanced_lines = []

    for i, line in enumerate(lines):
        if i < len(lines) - 1:
            current_length = len(line)
            next_line = lines[i + 1]

            words_current = line.split()
            words_next = next_line.split()

            if current_length < max_chars_per_line * 0.7 and len(words_next) > 1:
                test_line = line + " " + words_next[0]

                if len(test_line) <= max_chars_per_line:
                    balanced_lines.append(test_line)
                    lines[i + 1] = " ".join(words_next[1:])
                    continue

        balanced_lines.append(line)

    return balanced_lines


def create(audio_file, subtitle_file: str = ""):
    global model
    if WhisperModel is None:
        logger.warning("faster_whisper not available, skipping whisper subtitle generation")
        return ""
    if not model:
        model_path = f"{utils.root_dir()}/models/whisper-{model_size}"
        model_bin_file = f"{model_path}/model.bin"
        if not os.path.isdir(model_path) or not os.path.isfile(model_bin_file):
            model_path = model_size

        logger.info(
            f"loading model: {model_path}, device: {device}, compute_type: {compute_type}"
        )
        try:
            model = WhisperModel(
                model_size_or_path=model_path, device=device, compute_type=compute_type
            )
        except Exception as e:
            logger.error(
                f"failed to load model: {e} \n\n"
                f"********************************************\n"
                f"this may be caused by network issue. \n"
                f"please download the model manually and put it in the 'models' folder. \n"
                f"see [README.md FAQ](https://github.com/harry0703/MoneyPrinterTurbo) for more details.\n"
                f"********************************************\n\n"
            )
            return None

    logger.info(f"start, output file: {subtitle_file}")
    if not subtitle_file:
        subtitle_file = f"{audio_file}.srt"

    initial_prompt = getattr(params, "whisper_initial_prompt", None) or _whisper_initial_prompt()

    segments, info = model.transcribe(
        audio_file,
        beam_size=5,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
        **({"initial_prompt": initial_prompt} if initial_prompt else {}),
    )

    logger.info(
        f"detected language: '{info.language}', probability: {info.language_probability:.2f}"
    )

    start = timer()
    subtitles = []

    def recognized(seg_text, seg_start, seg_end):
        seg_text = _correct_brand_names(seg_text.strip())
        if not seg_text:
            return

        msg = "[%.2fs -> %.2fs] %s" % (seg_start, seg_end, seg_text)
        logger.debug(msg)

        subtitles.append(
            {"msg": seg_text, "start_time": seg_start, "end_time": seg_end}
        )

    for segment in segments:
        words_idx = 0
        words_len = len(segment.words)

        seg_start = 0
        seg_end = 0
        seg_text = ""

        if segment.words:
            is_segmented = False
            for word in segment.words:
                if not is_segmented:
                    seg_start = word.start
                    is_segmented = True

                seg_end = word.end
                # If it contains punctuation, then break the sentence.
                seg_text += word.word

                if utils.str_contains_punctuation(word.word):
                    # remove last char
                    seg_text = seg_text[:-1]
                    if not seg_text:
                        continue

                    recognized(seg_text, seg_start, seg_end)

                    is_segmented = False
                    seg_text = ""

                if words_idx == 0 and segment.start < word.start:
                    seg_start = word.start
                if words_idx == (words_len - 1) and segment.end > word.end:
                    seg_end = word.end
                words_idx += 1

        if not seg_text:
            continue

        recognized(seg_text, seg_start, seg_end)

    end = timer()

    diff = end - start
    logger.info(f"complete, elapsed: {diff:.2f} s")

    idx = 1
    lines = []
    for subtitle in subtitles:
        text = subtitle.get("msg")
        if text:
            lines.append(
                utils.text_to_srt(
                    idx, text, subtitle.get("start_time"), subtitle.get("end_time")
                )
            )
            idx += 1

    sub = "\n".join(lines) + "\n"
    with open(subtitle_file, "w", encoding="utf-8") as f:
        f.write(sub)
    logger.info(f"subtitle file created: {subtitle_file}")


def file_to_subtitles(filename):
    if not filename or not os.path.isfile(filename):
        return []

    times_texts = []
    current_times = None
    current_text = ""
    index = 0
    with open(filename, "r", encoding="utf-8") as f:
        for line in f:
            times = re.findall("([0-9]*:[0-9]*:[0-9]*,[0-9]*)", line)
            if times:
                current_times = line
            elif line.strip() == "" and current_times:
                index += 1
                times_texts.append((index, current_times.strip(), current_text.strip()))
                current_times, current_text = None, ""
            elif current_times:
                current_text += line

    # Flush the final block. SRT files whose last subtitle is not followed by a
    # trailing blank line never hit the blank-line branch above, so without this
    # the last subtitle would be silently dropped.
    if current_times:
        index += 1
        times_texts.append((index, current_times.strip(), current_text.strip()))
    return times_texts


def levenshtein_distance(s1, s2):
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def similarity(a, b):
    distance = levenshtein_distance(a.lower(), b.lower())
    max_length = max(len(a), len(b))
    return 1 - (distance / max_length)


def correct(subtitle_file, video_script):
    subtitle_items = file_to_subtitles(subtitle_file)
    normalized_script = utils.normalize_script_for_subtitle_matching(video_script)
    script_lines = utils.split_string_by_punctuations(normalized_script)

    corrected = False
    new_subtitle_items = []
    script_index = 0
    subtitle_index = 0

    while script_index < len(script_lines) and subtitle_index < len(subtitle_items):
        script_line = script_lines[script_index].strip()
        subtitle_line = subtitle_items[subtitle_index][2].strip()

        if script_line == subtitle_line:
            new_subtitle_items.append(subtitle_items[subtitle_index])
            script_index += 1
            subtitle_index += 1
        else:
            combined_subtitle = subtitle_line
            start_time = subtitle_items[subtitle_index][1].split(" --> ")[0]
            end_time = subtitle_items[subtitle_index][1].split(" --> ")[1]
            next_subtitle_index = subtitle_index + 1

            while next_subtitle_index < len(subtitle_items):
                next_subtitle = subtitle_items[next_subtitle_index][2].strip()
                if similarity(
                    script_line, combined_subtitle + " " + next_subtitle
                ) > similarity(script_line, combined_subtitle):
                    combined_subtitle += " " + next_subtitle
                    end_time = subtitle_items[next_subtitle_index][1].split(" --> ")[1]
                    next_subtitle_index += 1
                else:
                    break

            if similarity(script_line, combined_subtitle) > 0.8:
                logger.warning(
                    f"Merged/Corrected - Script: {script_line}, Subtitle: {combined_subtitle}"
                )
                new_subtitle_items.append(
                    (
                        len(new_subtitle_items) + 1,
                        f"{start_time} --> {end_time}",
                        script_line,
                    )
                )
                corrected = True
            else:
                logger.warning(
                    f"Mismatch - Script: {script_line}, Subtitle: {combined_subtitle}"
                )
                new_subtitle_items.append(
                    (
                        len(new_subtitle_items) + 1,
                        f"{start_time} --> {end_time}",
                        script_line,
                    )
                )
                corrected = True

            script_index += 1
            subtitle_index = next_subtitle_index

    # Process the remaining lines of the script.
    while script_index < len(script_lines):
        logger.warning(f"Extra script line: {script_lines[script_index]}")
        if subtitle_index < len(subtitle_items):
            new_subtitle_items.append(
                (
                    len(new_subtitle_items) + 1,
                    subtitle_items[subtitle_index][1],
                    script_lines[script_index],
                )
            )
            subtitle_index += 1
        else:
            new_subtitle_items.append(
                (
                    len(new_subtitle_items) + 1,
                    "00:00:00,000 --> 00:00:00,000",
                    script_lines[script_index],
                )
            )
        script_index += 1
        corrected = True

    if corrected:
        with open(subtitle_file, "w", encoding="utf-8") as fd:
            for i, item in enumerate(new_subtitle_items):
                fd.write(f"{i + 1}\n{item[1]}\n{item[2]}\n\n")
        logger.info("Subtitle corrected")
    else:
        logger.success("Subtitle is correct")


if __name__ == "__main__":
    task_id = "c12fd1e6-4b0a-4d65-a075-c87abe35a072"
    task_dir = utils.task_dir(task_id)
    subtitle_file = f"{task_dir}/subtitle.srt"
    audio_file = f"{task_dir}/audio.mp3"

    subtitles = file_to_subtitles(subtitle_file)
    print(subtitles)

    script_file = f"{task_dir}/script.json"
    with open(script_file, "r") as f:
        script_content = f.read()
    s = json.loads(script_content)
    script = s.get("script")

    correct(subtitle_file, script)

    subtitle_file = f"{task_dir}/subtitle-test.srt"
    create(audio_file, subtitle_file)
