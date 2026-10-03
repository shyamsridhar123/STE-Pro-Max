"""Prepare local, evidence-linked story media. Never render, publish, or fetch assets."""
from __future__ import annotations

import hashlib
import html
import json
import os
from pathlib import Path
import shutil
import stat
import struct
import subprocess
from typing import cast
import unicodedata
import xml.etree.ElementTree as ET

from jinja2 import Environment, FileSystemLoader

from .json_input import loads_json
from .stories import render_story, story_companions, validate_story

MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_AUDIO_BYTES = 32 * 1024 * 1024
MAX_TOTAL_AUDIO_BYTES = 256 * 1024 * 1024
NARRATOR = Path(__file__).resolve().parent / "scripts/narrate.ps1"


def _local_path(value: Path) -> Path:
    """Reject traversal, links (including Windows junctions), devices and UNC paths."""
    path = Path(value)
    if ".." in path.parts or str(path).startswith(("\\\\", "//")):
        raise ValueError("Use local paths without parent traversal or network shares.")
    path = path.absolute()
    for part in path.parts[1:]:
        if ":" in part or part.endswith((" ", ".")):
            raise ValueError("Alternate streams and ambiguous path components are not supported.")
        if part.split(".")[0].upper() in {
            "CON", "PRN", "AUX", "NUL",
            *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10)),
        }:
            raise ValueError("Device paths are not supported.")
    for component in (*reversed(path.parents), path):
        try:
            info = component.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("Symlinks and reparse points are not supported.")
    return path


def _read_bounded(path: Path, limit: int) -> bytes:
    path = _local_path(path)
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError(f"Expected a regular file: {path.name}")
    with path.open("rb") as handle:
        if os.fstat(handle.fileno()).st_size > limit:
            raise ValueError(f"File exceeds the {limit}-byte limit: {path.name}")
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"File exceeds the {limit}-byte limit: {path.name}")
    return data


def _pcm_info(data: bytes) -> dict:
    """Validate the entire RIFF container, PCM header, frames and changing signal."""
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("Expected a RIFF/WAVE PCM file.")
    if struct.unpack_from("<I", data, 4)[0] != len(data) - 8:
        raise ValueError("Truncated or inconsistent RIFF/WAVE length.")
    offset, fmt, frames = 12, None, None
    while offset < len(data):
        if offset + 8 > len(data):
            raise ValueError("Truncated WAV chunk header.")
        kind, size = struct.unpack_from("<4sI", data, offset)
        start, end = offset + 8, offset + 8 + size
        if end + size % 2 > len(data):
            raise ValueError("Truncated WAV chunk.")
        if kind == b"fmt ":
            if fmt is not None or size < 16:
                raise ValueError("Invalid or duplicate PCM format.")
            fmt = struct.unpack_from("<HHIIHH", data, start)
        elif kind == b"data":
            if frames is not None or fmt is None:
                raise ValueError("Expected one PCM data chunk after its format.")
            frames = data[start:end]
        offset = end + size % 2
    if fmt is None or frames is None:
        raise ValueError("Missing PCM format or data.")
    tag, channels, rate, byte_rate, block, bits = fmt
    if (tag != 1 or channels not in (1, 2) or bits not in (8, 16, 24, 32)
            or not 8000 <= rate <= 192000 or block != channels * bits // 8
            or byte_rate != rate * block):
        raise ValueError("Use integer PCM, mono/stereo, 8–32 bits, 8000–192000 Hz.")
    if len(frames) < 2 * block or len(frames) % block:
        raise ValueError("Empty, truncated or misaligned PCM frames.")
    if not any(frames[i:i + block] != frames[:block] for i in range(block, len(frames), block)):
        raise ValueError("Silent or constant PCM audio.")
    duration = len(frames) / byte_rate
    if duration < .001:
        raise ValueError("Audio is shorter than the one-millisecond caption resolution.")
    if duration > 600:
        raise ValueError("Audio exceeds the 600-second per-beat limit.")
    return {"duration": duration, "frames": len(frames) // block, "sample_rate": rate,
            "channels": channels, "sample_width": bits // 8, "non_silent_pcm": True}


def synthesize(text_path: Path, audio_path: Path, voice: str | None) -> None:
    """Call the existing offline Windows System.Speech helper, without a shell."""
    shell = shutil.which("powershell.exe")
    if not shell or not NARRATOR.is_file():
        raise RuntimeError("Local System.Speech helper unavailable; provide --audio-dir with PCM WAV files.")
    command = [shell, "-NoProfile", "-NonInteractive", "-File", str(NARRATOR),
               "-InputPath", str(text_path), "-OutputPath", str(audio_path)]
    if voice is not None:
        command.extend(["-Voice", voice])
    result = subprocess.run(command, capture_output=True, text=True, timeout=180, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Local System.Speech narration failed.")


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def _vtt_time(seconds: float) -> str:
    hours, rest = divmod(round(seconds * 1000), 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    seconds, milliseconds = divmod(rest, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02}.{milliseconds:03}"


def _fits(text: str, columns: int, lines: int) -> bool:
    # Deliberately conservative; no font shrinking or clipping to accommodate prose.
    widths = [sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in line)
              for line in text.expandtabs(8).splitlines()]
    return sum(max(1, (width + columns - 1) // columns) for width in widths) <= lines


def _beat_paragraphs(beat: dict, claims: dict) -> list[str]:
    paragraphs = [beat["text"]] if beat.get("text") else []
    for key in beat["claim_ids"]:
        claim = claims[key]
        parts = [f"[{claim['type'].upper()} · {key}] {claim['text']}"]
        for field, label in (("attributed_to", "Attribution"), ("basis", "Basis"),
                             ("scope", "Scope"), ("uncertainty", "Qualification")):
            if claim.get(field):
                parts.append(f"{label}: {claim[field]}")
        parts.append("Source IDs: " + (", ".join(claim["source_ids"]) or "none; proposal"))
        paragraphs.append("\n".join(parts))
    if beat.get("question"):
        paragraphs.append("Check: " + beat["question"]["prompt"])
        if "answer" in beat["question"]:
            paragraphs.append("Answer: " + beat["question"]["answer"])
    if beat.get("visual"):
        paragraphs.append("Visual description: " + beat["visual"]["description"])
        if beat["visual"].get("caption"):
            paragraphs.append("Source caption: " + beat["visual"]["caption"])
    return paragraphs


def _check_svg_size(svg: str, width: int, height: int, beat_id: str) -> None:
    root = ET.fromstring(svg)
    _, _, natural_width, natural_height = map(float, root.attrib["viewBox"].split())
    sizes = [float(node.attrib["font-size"]) for node in root.iter() if "font-size" in node.attrib]
    if min(width / natural_width, height / natural_height) * min(sizes) < 14:
        raise ValueError(f"{beat_id}: visual text would be below 14px; split the visual before preparation.")


def _visual(beat: dict, claims: dict) -> dict:
    if not _fits(beat["title"], 40, 1):
        raise ValueError(f"{beat['id']}: title exceeds the one-line video budget; author a shorter title.")
    paragraphs = _beat_paragraphs(beat, claims)
    result = {"title": beat["title"], "svg": "", "paragraphs": paragraphs, "stages": []}
    visual = beat.get("visual")
    sequence = (visual and visual["kind"] == "diagram" and visual["type"] == "sequence"
                and bool(visual["messages"]))
    columns, lines = (90, 12) if sequence else (40, 32) if visual else (60, 14)
    if not _fits("\n\n".join(paragraphs), columns, lines):
        raise ValueError(
            f"{beat['id']}: complete text, source caption and claim qualifications exceed the "
            f"{lines}-line video budget; split the beat without removing qualifications."
        )
    if visual:
        if visual["kind"] == "diagram":
            from .diagrams import diagram_svg
            if sequence and visual["messages"]:
                for number, message in enumerate(visual["messages"], 1):
                    # Keep participants and the authored message unmodified; no inferred arrows.
                    svg = diagram_svg({**visual, "messages": [message]})
                    _check_svg_size(svg, 1800, 360, beat["id"])
                    result["stages"].append({"number": number, "message": message, "svg": svg})
            else:
                result["svg"] = diagram_svg(visual)
        else:
            from .charts import chart_svg
            result["svg"] = chart_svg(visual)  # Stable exact values, never interpolated.
        if result["svg"]:
            _check_svg_size(result["svg"], 1040, 760, beat["id"])
    return result


def _time_stages(visual: dict, record: dict) -> list[dict]:
    count = len(visual["stages"])
    if not count:
        return []
    if record["frames"] < count * record["sample_rate"]:
        raise ValueError(
            f"{record['id']}: sequence needs at least one second of audio per message; "
            "provide longer narration/audio or split the beat. Speech-to-message alignment is unverified."
        )
    stages = []
    for index, stage in enumerate(visual["stages"]):
        first = record["frames"] * index // count
        last = record["frames"] * (index + 1) // count
        start = record["start"] + first / record["sample_rate"]
        end = record["start"] + last / record["sample_rate"]
        stages.append({**stage, "count": count, "start": start, "end": end,
                       "duration": end - start, "audio_frame_start": first, "audio_frame_end": last,
                       "speech_to_message_alignment": "unverified"})
    return stages


def prepare_story_media(source: Path, output: Path, voice: str | None = None,
                        speaker=None, audio_dir: Path | None = None) -> dict:
    """Prepare a new directory from a native story and local PCM; return its manifest.

    ``speaker(text_path, audio_path, voice)`` is a test seam only. Audio-directory
    files must be named ``<beat-id>.wav``. The existing parent directory must exist.
    Only the composition and its audio live in ``video/``; review/evidence stay
    at the output root so Studio can open ``video/`` as a composition-only project.
    Raises on failure; after directory creation, manifest.json records partial
    failure and only successfully validated audio. No speech alignment is inferred.
    """
    original = _read_bounded(Path(source), MAX_SOURCE_BYTES)
    story = loads_json(original.decode("utf-8-sig"))
    validate_story(story)  # Complete native validation precedes ALL output I/O.
    story = cast(dict, story)  # The native validator guarantees an object.
    companions = story_companions(story)
    cues = json.loads(companions["narration.json"])["cues"]
    if audio_dir is not None and (voice is not None or speaker is not None):
        raise ValueError("Choose audio_dir OR local speech; do not combine audio_dir with voice/speaker.")
    if voice is not None and (not isinstance(voice, str) or not voice.strip() or "\x00" in voice):
        raise ValueError("Voice must be a nonempty name.")
    audio_root = _local_path(audio_dir) if audio_dir is not None else None
    if audio_root is not None and not audio_root.is_dir():
        raise ValueError("audio_dir must be an existing local directory.")
    output = _local_path(output)
    if output.exists():
        raise ValueError("Use a new output directory; existing output is never overwritten.")
    if not output.parent.is_dir():
        raise ValueError("The output parent directory must already exist.")
    warnings = [
        "Prepared only: no HyperFrames check, preview, rendered movie or listening review has run.",
        "Audio is nonconstant PCM, not verified speech or verified correspondence to the transcript.",
        "Captions are whole-beat cues, not word-aligned. Long cues are sidecar-only and explicitly labeled.",
        "Source truth, narration fidelity and author-supplied free narration require human review.",
    ]
    claims = {claim["id"]: claim for claim in story["claims"]}
    visuals = [_visual(beat, claims) for beat in story["beats"]]
    environment = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"),
                              autoescape=True)
    template = environment.get_template("story-video.html.j2")
    review = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
              '<meta name="viewport" content="width=device-width,initial-scale=1">'
              '<title>Story evidence and limits</title><style>'
              ':root{color-scheme:dark;--surface:#171513;--text-1:#f4eee7;--text-2:#c8c2ba;'
              '--line-strong:#554b42;--amber:#efa276;--font-body:system-ui,sans-serif}'
              '*{box-sizing:border-box}body{margin:0;padding:24px clamp(16px,4vw,60px);'
              'background:var(--surface);color:var(--text-1);font:16px/1.6 var(--font-body);'
              'overflow-wrap:anywhere}a{color:#efa276}a:focus-visible{outline:3px solid #efa276}'
              '</style></head><body>'
              '<p>Prepared, not rendered. Review narration and audio against this complete story. '
              'Source registration is not verification.</p>' + render_story(story) + "</body></html>")
    output.mkdir(exist_ok=False)
    identity = output.stat()

    def write(name: str, value: str | bytes):
        target = _local_path(output / name)
        current = output.stat()
        if (current.st_dev, current.st_ino) != (identity.st_dev, identity.st_ino):
            raise ValueError("Output directory identity changed.")
        target.relative_to(output)
        with target.open("xb") as handle:
            handle.write(value.encode("utf-8") if isinstance(value, str) else value)

    manifest = {"version": 1, "status": "preparing_not_rendered", "output": str(output),
                "source_file": "source.json", "normalized_story": "story.json",
                "source_sha256": hashlib.sha256(original).hexdigest(),
                "narration": "provided PCM" if audio_root else "local Windows System.Speech",
                "voice": voice, "audio": [], "warnings": warnings,
                "review_required": True, "source_verification": "not_performed"}
    if speaker is not None:
        manifest["narration"] = "injected test speaker"
    # Keep our exclusive file descriptor: failure reporting never follows a replaced manifest path.
    with (output / "manifest.json").open("x", encoding="utf-8") as manifest_file:
        def checkpoint():
            manifest_file.seek(0)
            manifest_file.write(_json(manifest))
            manifest_file.truncate()
            manifest_file.flush()

        checkpoint()
        active_beat = None
        try:
            write("source.json", original)
            write("story.json", _json(story))
            for name, content in companions.items():
                write(name, content)
            write("review.html", review)
            _local_path(output / "video").mkdir(exist_ok=False)
            timeline, subtitles = [], ["WEBVTT", ""]
            clock, total_bytes = 0.0, 0
            for cue, visual in zip(cues, visuals):
                active_beat = cue["id"]
                audio_src = f"beat-{active_beat}.wav"
                audio_name = f"video/{audio_src}"
                text_name = f"beat-{active_beat}.txt"
                write(text_name, cue["text"])
                if audio_root:
                    data = _read_bounded(audio_root / f"{active_beat}.wav", MAX_AUDIO_BYTES)
                else:
                    (speaker or synthesize)(output / text_name, output / audio_name, voice)
                    data = _read_bounded(output / audio_name, MAX_AUDIO_BYTES)
                info = _pcm_info(data)
                total_bytes += len(data)
                if total_bytes > MAX_TOTAL_AUDIO_BYTES:
                    raise ValueError("Total audio exceeds the 256 MiB preparation limit.")
                if audio_root:
                    write(audio_name, data)
                record = {"id": active_beat, "file": audio_name, "audio_src": audio_src, "start": clock,
                          **info, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                manifest["audio"].append(record)
                end = clock + info["duration"]
                caption_visible = _fits(cue["text"], 90, 3)
                if not caption_visible:
                    warnings.append(f"{active_beat}: caption exceeds three lines; complete cue in captions.vtt.")
                stages = _time_stages(visual, record)
                if stages:
                    warnings.append(f"{active_beat}: demonstration pacing, not measured event time; "
                                    "speech-to-message alignment is unverified.")
                timeline.append({**record, "end": end, "text": cue["text"], "stages": stages,
                                 "review_required": cue["review_required"], "origin": cue["origin"],
                                 "claim_ids": cue["claim_ids"], "caption_visible": caption_visible,
                                 "visual": visual})
                # Escape VTT markup and flatten blank lines so hostile text cannot create extra cues.
                caption = html.escape(cue["text"].replace("\r", " ").replace("\n", " "), quote=False)
                subtitles.extend([active_beat, f"{_vtt_time(clock)} --> {_vtt_time(end)}", caption, ""])
                clock = end
                checkpoint()
            write("timeline.json", _json({"version": 1, "duration_seconds": clock,
                                         "caption_timing": "whole-beat-not-word-aligned", "beats": timeline}))
            write("transcript.txt", "\n\n".join(cue["text"] for cue in cues) + "\n")
            write("captions.vtt", "\n".join(subtitles))
            write("video/index.html", template.render(story=story, beats=timeline, duration=clock))
            manifest.update(status="prepared_not_rendered", duration_seconds=clock,
                            composition="video/index.html", video_directory="video", timeline="timeline.json",
                            transcript="transcript.txt", captions="captions.vtt", review="review.html")
            checkpoint()
        except Exception as error:
            manifest.update(status="partial_failure_not_rendered", failed_beat_id=active_beat,
                            error={"type": type(error).__name__, "message": str(error)[:2000]})
            checkpoint()
            raise
    return manifest
