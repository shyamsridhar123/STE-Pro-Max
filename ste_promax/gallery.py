"""Local artifact gallery for STE-Pro-Max.

Copyright (c) 2026 Shyam Sridhar and contributors.
SPDX-License-Identifier: Apache-2.0
Source: core/gallery.py at 4b068bcab8e4dc105f0ef975ee224564f5d63383.
Modified: explicit local directory, safe YAML/links, owned-index replacement;
no Node bridge, harness discovery or persistent global artifact directories.
"""
from __future__ import annotations

import datetime
from pathlib import Path
import re
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader

from .render import _DEFAULT_DESIGN, _TEMPLATES_DIR, _design_tokens

_GALLERY_PREFIX = "<!DOCTYPE html>\n<!-- STE-Pro-Max generated gallery -->\n"


def regenerate_gallery(artifact_dir: Path) -> Path:
    """Index only direct local sidecars. Replace only our generated gallery.html.

    Malformed metadata is skipped; I/O and design-validation errors propagate.
    Artifact filenames, never untrusted metadata slugs, determine link targets.
    """
    art_dir = Path(artifact_dir)
    art_dir.mkdir(parents=True, exist_ok=True)
    artifacts: list[dict[str, Any]] = []
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
    gallery_path = art_dir / "gallery.html"
    if gallery_path.is_symlink():
        raise FileExistsError("Refusing to replace a symlink at gallery.html")
    with gallery_path.open("r+" if gallery_path.exists() else "x", encoding="utf-8", newline="") as stream:
        if stream.readable() and stream.read(len(_GALLERY_PREFIX)) != _GALLERY_PREFIX:
            raise FileExistsError("Refusing to overwrite an unowned gallery.html")
        stream.seek(0)
        stream.write(html_content)
        stream.truncate()
    return gallery_path
