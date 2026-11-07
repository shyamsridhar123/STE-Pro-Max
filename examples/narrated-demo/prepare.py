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
# Ensure the resolved bundle root leads import resolution ahead of any ambient CWD entry.
_ROOT_STR = str(ROOT)
if not sys.path or sys.path[0] != _ROOT_STR:
    sys.path[:] = [_ROOT_STR, *(entry for entry in sys.path if entry != _ROOT_STR)]

from ste_promax import gate, media  # noqa: E402
from ste_promax.policy_runtime import ERROR_POSTCONDITION_FAILURE, PolicyError  # noqa: E402


def synthesize(text_path: Path, audio_path: Path, voice: str | None) -> None:
    if not shutil.which("powershell.exe") or not NARRATOR.is_file():
        raise RuntimeError("This local example needs Windows PowerShell and an installed speech voice.")
    media.synthesize(text_path, audio_path, voice)


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


def _observe_files(paths: list[Path]) -> dict[str, dict[str, int | str]]:
    observed: dict[str, dict[str, int | str]] = {}
    for path in paths:
        resolved = path.resolve(strict=True)
        raw = resolved.read_bytes()
        observed[str(resolved)] = {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size": len(raw),
        }
    return observed


def _synthesize_cue_wav(text_path: Path, audio_path: Path, voice: str | None, speaker) -> None:
    if speaker is None or speaker is synthesize or speaker is media.synthesize:
        synthesize(text_path, audio_path, voice)
        return
    text_bytes = text_path.read_bytes()

    def _effect() -> None:
        speaker(text_path, audio_path, voice)

    def _validate(_result: None) -> dict:
        pcm_duration(audio_path)
        return {
            "status": "synthesized",
            "native_status": "synthesized",
            "outputs": _observe_files([audio_path]),
            "checks": ["pcm_wav_synthesized", "non_silent_pcm_verified"],
            "warnings": [],
        }

    gate.run_guarded_operation(
        "ste.synthesize_wav",
        {
            "caller_kind": "native",
            "workspace_root": str(ROOT),
            "source_paths": [str(text_path)],
            "source_digest": hashlib.sha256(text_bytes).hexdigest(),
            "target_paths": [str(audio_path)],
            "source_kind": "text",
            "text_path": str(text_path),
            "audio_path": str(audio_path),
            "voice": voice,
            "speaker_injected": True,
            "speech_available": True,
            "expected_before": {str(audio_path): None},
        },
        _effect,
        validate_result=_validate,
    )


def prepare(output: Path, voice: str | None = None, speaker=synthesize) -> dict:
    output = media._local_path(Path(output)).resolve()
    if output.exists():
        raise ValueError("Use a new output directory; existing output is never overwritten.")
    if voice is not None and (not isinstance(voice, str) or not voice.strip() or "\x00" in voice):
        raise ValueError("Voice must be a nonempty name.")
    script_path = media._local_path(HERE / "script.json").resolve(strict=True)
    composition_path = media._local_path(HERE / "composition.html").resolve(strict=True)
    script_bytes = media._read_bounded(script_path, media.MAX_SOURCE_BYTES)
    composition_bytes = media._read_bounded(composition_path, media.MAX_SOURCE_BYTES)
    script_sha256 = hashlib.sha256(script_bytes).hexdigest()
    composition_sha256 = hashlib.sha256(composition_bytes).hexdigest()
    cues = json.loads(script_bytes.decode("utf-8"))
    if len(cues) != 4 or any(not isinstance(cue.get("text"), str) or not cue["text"].strip() for cue in cues):
        raise ValueError("This example needs four nonempty narration cues.")
    template = composition_bytes.decode("utf-8")
    for marker in ("@@DURATION@@", "@@AUDIOS@@", "@@CAPTIONS@@", "@@TIMINGS@@"):
        if marker not in template:
            raise ValueError(f"Missing composition template marker: {marker}")

    def _verify_source_origins_unchanged() -> None:
        current_script = media._read_bounded(media._local_path(HERE / "script.json"), media.MAX_SOURCE_BYTES)
        current_comp = media._read_bounded(media._local_path(HERE / "composition.html"), media.MAX_SOURCE_BYTES)
        if hashlib.sha256(current_script).hexdigest() != script_sha256:
            raise PolicyError(
                f"Source script.json changed during preparation: {script_path}",
                code=ERROR_POSTCONDITION_FAILURE,
            )
        if hashlib.sha256(current_comp).hexdigest() != composition_sha256:
            raise PolicyError(
                f"Source composition.html changed during preparation: {composition_path}",
                code=ERROR_POSTCONDITION_FAILURE,
            )

    source_origins = [str(script_path), str(composition_path)]
    source_digest = hashlib.sha256(script_bytes + b"\x00" + composition_bytes).hexdigest()
    cue_files = {
        output / f"voice-{index:02}.txt": cue["text"] + "\n"
        for index, cue in enumerate(cues, 1)
    }

    def _write_cue_batch() -> None:
        _verify_source_origins_unchanged()
        output.mkdir(parents=True, exist_ok=False)
        for path, content in cue_files.items():
            with path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(content)

    def _validate_cue_batch(_res: None) -> dict:
        _verify_source_origins_unchanged()
        return {
            "status": "written",
            "native_status": "written",
            "outputs": _observe_files(list(cue_files)),
            "checks": ["cue_text_batch_written", "source_origins_unchanged"],
            "warnings": [],
        }

    gate.run_guarded_operation(
        "ste.host_write_artifact",
        {
            "caller_kind": "native",
            "workspace_root": str(ROOT),
            "output_root": str(output),
            "source_paths": source_origins,
            "source_digest": source_digest,
            "source_kind": "structured",
            "trusted_html": False,
            "target_paths": [str(p) for p in cue_files],
            "proposed_contents": {str(p): content for p, content in cue_files.items()},
            "expected_before": {str(p): None for p in cue_files},
        },
        _write_cue_batch,
        validate_result=_validate_cue_batch,
    )

    audios, captions, timestamps, records, subtitles = [], [], [], [], ["WEBVTT\n"]
    wav_paths: list[Path] = []
    clock = 0.35
    for index, cue in enumerate(cues, 1):
        text_path = output / f"voice-{index:02}.txt"
        audio_path = output / f"voice-{index:02}.wav"
        _synthesize_cue_wav(text_path, audio_path, voice, speaker)
        duration = pcm_duration(audio_path)
        wav_paths.append(audio_path)
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

    _verify_source_origins_unchanged()

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

    result = {
        "status": "prepared_not_rendered",
        "output": str(output),
        "duration_seconds": duration,
        "audio": records,
        "narration": "local Windows System.Speech",
        "voice": voice or "installed default",
    }
    final_files = {
        output / "index.html": template,
        output / "transcript.txt": "\n\n".join(cue["text"] for cue in cues) + "\n",
        output / "captions.vtt": "\n".join(subtitles),
        output / "manifest.json": json.dumps(result, indent=2) + "\n",
    }

    def _write_final_bundle() -> dict:
        _verify_source_origins_unchanged()
        for path, content in final_files.items():
            with path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
        return result

    def _validate_final_bundle(res: dict) -> dict:
        _verify_source_origins_unchanged()
        for wav_path, record in zip(wav_paths, records):
            pcm_duration(wav_path)
            if hashlib.sha256(wav_path.read_bytes()).hexdigest() != record["sha256"]:
                raise ValueError(f"Synthesized audio changed during preparation: {wav_path.name}")
        return {
            "status": "written",
            "native_status": res["status"],
            "outputs": _observe_files(list(final_files)),
            "checks": [
                "composition_written",
                "captions_written",
                "manifest_written",
                "pcm_audio_verified",
                "source_origins_unchanged",
            ],
            "warnings": [],
        }

    return gate.run_guarded_operation(
        "ste.host_write_artifact",
        {
            "caller_kind": "native",
            "workspace_root": str(ROOT),
            "output_root": str(output),
            "source_paths": source_origins,
            "source_digest": source_digest,
            "source_kind": "host_content",
            "trusted_html": False,
            "target_paths": [str(p) for p in final_files],
            "proposed_contents": {str(p): content for p, content in final_files.items()},
            "expected_before": {str(p): None for p in final_files},
        },
        _write_final_bundle,
        validate_result=_validate_final_bundle,
    )


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
