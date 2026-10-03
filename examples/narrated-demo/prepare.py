"""Prepare the local narrated HyperFrames example; does not render or publish."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import shutil
import subprocess
import sys
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NARRATOR = ROOT / "ste_promax/scripts/narrate.ps1"


def synthesize(text_path: Path, audio_path: Path, voice: str | None) -> None:
    shell = shutil.which("powershell.exe")
    if not shell:
        raise RuntimeError("This local example needs Windows PowerShell and an installed speech voice.")
    command = [shell, "-NoProfile", "-File", str(NARRATOR),
               "-InputPath", str(text_path), "-OutputPath", str(audio_path)]
    if voice:
        command.extend(["-Voice", voice])
    completed = subprocess.run(command, capture_output=True, text=True, timeout=90, check=False)
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or "Local narration failed.")


def vtt_time(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, rest = divmod(milliseconds, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, ms = divmod(rest, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02}.{ms:03}"


def pcm_duration(path: Path) -> float:
    """Reject truncated PCM and constant/silent frames, not just empty headers."""
    with wave.open(str(path), "rb") as audio:
        count = audio.getnframes()
        block = audio.getnchannels() * audio.getsampwidth()
        if audio.getcomptype() != "NONE" or count < 2 or block <= 0:
            raise ValueError(f"Empty or non-PCM audio: {path.name}")
        frames = audio.readframes(count)
        if len(frames) != count * block:
            raise ValueError(f"Truncated PCM audio: {path.name}")
        first = frames[:block]
        if not any(frames[offset:offset + block] != first for offset in range(block, len(frames), block)):
            raise ValueError(f"Silent or constant PCM audio: {path.name}")
        return count / audio.getframerate()


def prepare(output: Path, voice: str | None = None, speaker=synthesize) -> dict:
    output = output.resolve()
    if output.exists():
        raise ValueError("Use a new output directory; existing output is never overwritten.")
    cues = json.loads((HERE / "script.json").read_text(encoding="utf-8"))
    if len(cues) != 4 or any(not isinstance(cue.get("text"), str) or not cue["text"].strip() for cue in cues):
        raise ValueError("This example needs four nonempty narration cues.")
    template = (HERE / "composition.html").read_text(encoding="utf-8")
    output.mkdir(parents=True, exist_ok=False)
    audios, captions, timestamps, records, subtitles = [], [], [], [], ["WEBVTT\n"]
    clock = 0.35
    for index, cue in enumerate(cues, 1):
        text_path = output / f"voice-{index:02}.txt"
        audio_path = output / f"voice-{index:02}.wav"
        text_path.write_text(cue["text"] + "\n", encoding="utf-8")
        speaker(text_path, audio_path, voice)
        duration = pcm_duration(audio_path)
        timestamps.append(round(clock, 3))
        end = clock + duration
        audios.append(f'<audio id="voice-{index}" src="{audio_path.name}" data-start="{clock:.3f}" '
                      f'data-duration="{duration:.3f}" data-track-index="1"></audio>')
        captions.append(f'<p id="caption-{index}" class="clip caption" data-start="{clock:.3f}" '
                        f'data-duration="{duration:.3f}" data-track-index="2">{html.escape(cue["text"])}</p>')
        subtitles.append(f"{index}\n{vtt_time(clock)} --> {vtt_time(end)}\n{cue['text']}\n")
        records.append({"file": audio_path.name, "start": round(clock, 3),
                        "duration": round(duration, 3),
                        "non_silent_pcm": True,
                        "sha256": hashlib.sha256(audio_path.read_bytes()).hexdigest()})
        clock = end + 0.2
    duration = round(clock + 0.7, 3)
    replacements = {
        "@@DURATION@@": str(duration),
        "@@AUDIOS@@": "\n  ".join(audios),
        "@@CAPTIONS@@": "\n  ".join(captions),
        "@@TIMINGS@@": json.dumps(timestamps),
    }
    for marker, value in replacements.items():
        template = template.replace(marker, value)
    if "@@" in template:
        raise ValueError("Unresolved composition template marker.")
    (output / "index.html").write_text(template, encoding="utf-8")
    (output / "transcript.txt").write_text("\n\n".join(cue["text"] for cue in cues) + "\n", encoding="utf-8")
    (output / "captions.vtt").write_text("\n".join(subtitles), encoding="utf-8")
    result = {"status": "prepared_not_rendered", "output": str(output),
              "duration_seconds": duration, "audio": records,
              "narration": "local Windows System.Speech", "voice": voice or "installed default"}
    (output / "manifest.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--voice")
    args = parser.parse_args()
    try:
        print(json.dumps(prepare(args.output_dir, args.voice), indent=2))
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired, wave.Error) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
