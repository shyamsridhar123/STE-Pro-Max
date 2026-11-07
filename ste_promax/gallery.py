"""Local artifact gallery for STE-Pro-Max.

Copyright (c) 2026 Shyam Sridhar and contributors.
SPDX-License-Identifier: Apache-2.0
Source: core/gallery.py at 4b068bcab8e4dc105f0ef975ee224564f5d63383.
Modified: explicit local directory, safe YAML/links, owned-index replacement;
no Node bridge, harness discovery or persistent global artifact directories.
"""
from __future__ import annotations

import datetime
import hashlib
from pathlib import Path
import re
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader

from .policy_runtime import ERROR_POSTCONDITION_FAILURE, PolicyError
from .render import _DEFAULT_DESIGN, _TEMPLATES_DIR, _design_tokens

_GALLERY_PREFIX = "<!DOCTYPE html>\n<!-- STE-Pro-Max generated gallery -->\n"


def regenerate_gallery(artifact_dir: Path) -> Path:
    """Index only direct local sidecars. Replace only our generated gallery.html.

    Malformed metadata is skipped; I/O and design-validation errors propagate.
    Artifact filenames, never untrusted metadata slugs, determine link targets.
    """
    art_dir = Path(artifact_dir)
    if art_dir.is_symlink():
        raise FileExistsError("Refusing to use a symlink as artifact directory")
    resolved_art_dir = art_dir.resolve()
    gallery_path = art_dir / "gallery.html"
    resolved_gallery = resolved_art_dir / "gallery.html"
    if gallery_path.is_symlink():
        raise FileExistsError("Refusing to replace a symlink at gallery.html")
    expected_before_hash: str | None = None
    if gallery_path.exists():
        existing_bytes = gallery_path.read_bytes()
        try:
            existing_text = existing_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise FileExistsError("Refusing to overwrite an unowned gallery.html") from exc
        if not existing_text.startswith(_GALLERY_PREFIX):
            raise FileExistsError("Refusing to overwrite an unowned gallery.html")
        expected_before_hash = hashlib.sha256(existing_bytes).hexdigest()

    artifacts: list[dict[str, Any]] = []
    source_paths: list[str] = []
    if art_dir.exists() and art_dir.is_dir():
        for meta_file in art_dir.glob("*.meta.yaml"):
            if meta_file.is_symlink() or not meta_file.is_file():
                continue
            slug = meta_file.name.removesuffix(".meta.yaml")
            if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
                continue
            try:
                meta = yaml.safe_load(meta_file.read_text(encoding="utf-8"))
            except yaml.YAMLError:
                continue
            if not isinstance(meta, dict):
                continue
            source_paths.append(str(meta_file.resolve()))
            html_name = f"{slug}.html"
            html_path = art_dir / html_name
            artifacts.append({
                "slug": slug,
                "title": str(meta.get("title") or slug.replace("-", " ").title()),
                "generator": str(meta.get("generator", "unknown")),
                "design": str(meta.get("design", "")),
                "tier": str(meta.get("tier", "ste")),
                "created_at": str(meta.get("created_at", "")),
                "html_name": html_name,
                "html_exists": not html_path.is_symlink() and html_path.is_file(),
            })
    artifacts.sort(key=lambda art: (art["created_at"], art["slug"]), reverse=True)
    tokens = _design_tokens(_DEFAULT_DESIGN.read_text(encoding="utf-8"))
    env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)), autoescape=True)
    html_content = env.get_template("gallery.html.j2").render(
        artifacts=artifacts, tokens=tokens, total=len(artifacts),
        generated_at=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )
    guard_inputs: dict[str, Any] = {
        "caller_kind": "native",
        "workspace_root": str(Path.cwd().resolve()),
        "output_root": str(resolved_art_dir),
        "target_paths": [str(resolved_gallery)],
        "source_paths": [],
        "source_digest": hashlib.sha256(html_content.encode("utf-8")).hexdigest(),
        "source_kind": "structured",
        "trusted_html": False,
        "availability": {"render_dependencies": True},
        "proposed_contents": {str(resolved_gallery): html_content},
        "expected_before": {str(resolved_gallery): expected_before_hash},
    }

    def _effect() -> Path:
        art_dir.mkdir(parents=True, exist_ok=True)
        if gallery_path.is_symlink():
            raise FileExistsError("Refusing to replace a symlink at gallery.html")
        with gallery_path.open("r+" if gallery_path.exists() else "x", encoding="utf-8", newline="") as stream:
            if stream.readable() and stream.read(len(_GALLERY_PREFIX)) != _GALLERY_PREFIX:
                raise FileExistsError("Refusing to overwrite an unowned gallery.html")
            stream.seek(0)
            stream.write(html_content)
            stream.truncate()
        return gallery_path

    def _validate(result_path: Path) -> dict[str, Any]:
        p = Path(result_path)
        if p.is_symlink() or not p.is_file():
            raise PolicyError("gallery.html is missing or unsafe.", code=ERROR_POSTCONDITION_FAILURE)
        resolved_p = p.resolve()
        if resolved_p != resolved_gallery:
            raise PolicyError("gallery.html resolved path mismatch.", code=ERROR_POSTCONDITION_FAILURE)
        raw = p.read_bytes()
        if not raw:
            raise PolicyError("gallery.html is empty.", code=ERROR_POSTCONDITION_FAILURE)
        try:
            decoded = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PolicyError("gallery.html is not valid UTF-8.", code=ERROR_POSTCONDITION_FAILURE) from exc
        if not decoded.startswith(_GALLERY_PREFIX):
            raise PolicyError(
                "gallery.html is missing required STE-Pro-Max owned prefix.",
                code=ERROR_POSTCONDITION_FAILURE,
            )
        if decoded != html_content:
            raise PolicyError(
                "gallery.html content drifted from rendered payload.",
                code=ERROR_POSTCONDITION_FAILURE,
            )
        return {
            "status": "complete",
            "native_status": "complete",
            "outputs": {
                str(resolved_p): {
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "size": len(raw),
                }
            },
            "checks": ["gallery_present", "owned_prefix_verified", "utf8_valid"],
            "warnings": [],
        }

    from .gate import run_guarded_operation

    try:
        return run_guarded_operation("ste.regenerate_gallery", guard_inputs, _effect, validate_result=_validate)
    except Exception as exc:
        if isinstance(exc.__cause__, FileExistsError):
            raise exc.__cause__ from exc
        raise
