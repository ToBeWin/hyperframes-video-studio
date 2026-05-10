#!/usr/bin/env python3
"""Hyperframes project generator for Video Studio.

The JSON file is an intermediate manifest. The renderable output is the
generated HTML project directory containing index.html and relative assets.
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import re
import shutil
import subprocess
import sys
import time
import wave
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
CACHE_DIR = BASE_DIR / ".cache"
ASSET_DIR = CACHE_DIR / "assets"
PROJECT_DIR = CACHE_DIR / "hyperframes"
RENDER_DIR = CACHE_DIR / "renders"
TEMPLATE_FILE = BASE_DIR / "templates" / "video_templates.json"
EMBED_LIMIT_BYTES = 128 * 1024


FALLBACK_TEMPLATES = {
    "product_launch": {
        "name": "Product Launch",
        "resolution": {"width": 1920, "height": 1080},
        "style": {"palette": ["#0B0F19", "#F8FAFC", "#22D3EE", "#A3E635"], "font": "Inter"},
        "frames": [
            {"id": "hook", "role": "hook", "duration": 3, "motion": "depth_push"},
            {"id": "problem", "role": "problem", "duration": 4, "motion": "parallax_reveal"},
            {"id": "solution", "role": "solution", "duration": 5, "motion": "3d_like_orbit"},
            {"id": "feature_grid", "role": "feature_grid", "duration": 6, "motion": "staggered_cards"},
            {"id": "cta", "role": "cta", "duration": 3, "motion": "logo_lockup"},
        ],
    },
    "data_story": {
        "name": "Data Story",
        "resolution": {"width": 1920, "height": 1080},
        "style": {"palette": ["#111827", "#F9FAFB", "#38BDF8", "#F59E0B"], "font": "Inter"},
        "frames": [
            {"id": "headline_metric", "role": "headline_metric", "duration": 3, "motion": "count_up"},
            {"id": "kpi_progress", "role": "kpi_progress", "duration": 5, "motion": "bar_fill"},
            {"id": "chart_sequence", "role": "chart_sequence", "duration": 6, "motion": "axis_draw"},
            {"id": "insight", "role": "insight", "duration": 4, "motion": "callout_focus"},
            {"id": "summary", "role": "summary", "duration": 3, "motion": "ranked_list"},
        ],
    },
    "minimalist_quote": {
        "name": "Minimalist Quote",
        "resolution": {"width": 1080, "height": 1920},
        "style": {"palette": ["#050505", "#F5F5F4", "#D4AF37"], "font": "Geist"},
        "frames": [
            {"id": "silence_open", "role": "silence_open", "duration": 2, "motion": "fade_in"},
            {"id": "quote_part_1", "role": "quote_part_1", "duration": 4, "motion": "kinetic_type"},
            {"id": "quote_part_2", "role": "quote_part_2", "duration": 4, "motion": "slow_tracking"},
            {"id": "attribution", "role": "attribution", "duration": 3, "motion": "soft_lockup"},
        ],
    },
}


def load_templates() -> dict:
    if TEMPLATE_FILE.exists():
        with TEMPLATE_FILE.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    return FALLBACK_TEMPLATES


def _print(payload: dict) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _read_json(path: Path) -> dict:
    with path.expanduser().open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _safe_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in ("-", "_") else "-" for char in value).strip("-")[:60] or "video"


def _resolve_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    return path


def _asset_to_payload(path: Path, embed: bool) -> dict:
    payload = {
        "source": str(path.resolve()),
        "name": path.name,
        "mime": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        "exists": path.exists(),
    }
    if embed and path.exists() and path.stat().st_size <= EMBED_LIMIT_BYTES:
        payload["base64"] = base64.b64encode(path.read_bytes()).decode("ascii")
    return payload


def _html_escape(value: object) -> str:
    return (
        str(value if value is not None else "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _css_string(value: object) -> str:
    return str(value if value is not None else "").replace("\\", "\\\\").replace('"', '\\"')


def _script_json(value: object) -> str:
    return json.dumps(value, sort_keys=True).replace("</", "<\\/")


def _slug_words(value: str, limit: int = 16) -> list[str]:
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9+.#%/-]*", value)
    return words[:limit] or ["Video", "Studio"]


def _clean_prompt_prefix(value: str) -> str:
    return re.sub(r"^(video\s+theme|theme|topic|title|subject|brief)\s*[:：-]\s*", "", value.strip(), flags=re.I)


def _brief_sentences(value: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", value).strip()
    chunks = re.split(r"(?<=[.!?。！？])\s+|[\n;；]+", cleaned)
    sentences = [_clean_prompt_prefix(chunk.strip(" -")) for chunk in chunks if chunk.strip(" -")]
    sentences = [sentence for sentence in sentences if sentence]
    if len(sentences) >= 2:
        return sentences
    words = _slug_words(cleaned, 80)
    if not words:
        return ["A clear story for the audience."]
    return [" ".join(words[index : index + 10]) for index in range(0, len(words), 10)]


def _title_from_brief(value: str, fallback: str) -> str:
    sentences = _brief_sentences(value)
    first = sentences[0] if sentences else fallback
    first = _clean_prompt_prefix(first)
    first = re.sub(r"^(create|make|build|generate|turn)\s+(a|an|the)?\s*", "", first, flags=re.I)
    words = first.split()
    return " ".join(words[:7]).strip(" .,:;") or fallback


ROLE_HEADLINES = {
    "hook": "Open With The Promise",
    "problem": "Name The Pain",
    "solution": "Reveal The Solution",
    "feature_grid": "Show The Proof",
    "cta": "Make The Next Step Clear",
    "title": "Feature In Focus",
    "before_state": "Before The Change",
    "demo_step": "Show The Workflow",
    "after_state": "After The Change",
    "takeaway": "What Viewers Remember",
    "headline_metric": "Lead With The Number",
    "kpi_progress": "Track The Momentum",
    "chart_sequence": "Show The Trend",
    "insight": "Explain What It Means",
    "summary": "Close With The Takeaway",
    "question": "Start With The Question",
    "definition": "Define The Idea",
    "key_point": "Make The Point Concrete",
    "example": "Ground It In An Example",
    "recap": "Recap The Lesson",
    "quote": "Let The Quote Breathe",
    "quote_part_1": "Set The Line",
    "quote_part_2": "Land The Thought",
    "attribution": "Credit The Voice",
    "event_hook": "Announce The Moment",
    "speaker_intro": "Introduce The Host",
    "agenda": "Preview The Agenda",
    "date_time": "Lock The Date",
    "version_title": "New Release",
    "update_item": "What Changed",
    "availability": "Available Now",
    "product_hero": "Lead With The Product",
    "benefit": "Why It Matters",
    "offer": "Make The Offer Clear",
}


def _frame_copy(frame: dict, project: dict, index: int) -> dict:
    item = dict(frame)
    role = str(item.get("role") or "scene")

    # Priority 1: explicit frame_contents from the request (agent-generated per-frame copy)
    frame_contents = project.get("frame_contents") or []
    if index < len(frame_contents):
        fc = frame_contents[index]
        item["headline"] = item.get("headline") or fc.get("headline") or ""
        item["caption"] = item.get("caption") or fc.get("caption") or ""
        return item

    # Priority 2: brief-driven content (improved extraction)
    sentences = _brief_sentences(str(project.get("brief") or ""))
    title = _title_from_brief(str(project.get("brief") or ""), str(project.get("template_name") or "Video"))

    # Headline: first frame gets the title; subsequent frames get brief sentences
    if index == 0:
        default_headline = title
    elif index <= len(sentences) and index > 0:
        # Use brief sentences as headlines for subsequent frames, capped at 8 words
        sentence = sentences[index] if index < len(sentences) else sentences[-1]
        words = sentence.split()
        default_headline = " ".join(words[:8]).strip(" .,:;") or ROLE_HEADLINES.get(role, role.replace("_", " ").title())
    else:
        default_headline = ROLE_HEADLINES.get(role, role.replace("_", " ").title())

    # Caption: distribute brief sentences across frames
    if sentences:
        if len(sentences) == 1:
            # Single sentence: use it for all frames
            caption_source = sentences[0]
        elif index < len(sentences):
            caption_source = sentences[index]
        else:
            # More frames than sentences: cycle through remaining sentences
            caption_source = sentences[(index - 1) % len(sentences)]
    else:
        caption_source = str(project.get("best_for") or "")

    item["headline"] = item.get("headline") or default_headline
    item["caption"] = item.get("caption") or caption_source
    return item


def _generated_visual(project: dict, frame: dict, index: int) -> str:
    template = str(project.get("template") or "")
    words = _slug_words(str(frame.get("caption") or project.get("brief") or ""), 12)
    label = _html_escape(frame.get("headline") or frame.get("role") or "Scene")
    chips = "".join(f"<span>{_html_escape(word)}</span>" for word in words[:5])
    number = f"{index + 1:02d}"
    if template == "data_story":
        bars = "".join(
            f'<i style="--bar:{min(92, 32 + i * 14)}%"><b>{_html_escape(words[i % len(words)] if words else "KPI")}</b></i>'
            for i in range(4)
        )
        return f'<div class="visual-panel data-panel"><strong>{label}</strong><div class="bars">{bars}</div><em>{number}</em></div>'
    if template in {"explainer", "feature_demo", "changelog"}:
        nodes = "".join(f"<span>{_html_escape(word)}</span>" for word in words[:4])
        return f'<div class="visual-panel diagram-panel"><strong>{label}</strong><div class="nodes">{nodes}</div><em>{number}</em></div>'
    if template == "minimalist_quote":
        quote = _html_escape(" ".join(words[:9]) or label)
        return f'<div class="visual-panel quote-panel"><strong>“{quote}”</strong><em>{number}</em></div>'
    return f'<div class="visual-panel card-panel"><strong>{label}</strong><div class="chips">{chips}</div><em>{number}</em></div>'


def resolve_assets(assets: list[str], embed: bool) -> list[dict]:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    resolved = []
    for asset in assets:
        path = _resolve_path(asset)
        resolved.append(_asset_to_payload(path, embed))
    return resolved


def _media_kind(asset: dict) -> str:
    mime = str(asset.get("mime") or "")
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("audio/"):
        return "audio"
    if mime.startswith("video/"):
        return "video"
    return "other"


def _copy_render_assets(project: dict, html_dir: Path) -> tuple[list[dict], dict]:
    asset_out_dir = html_dir / "assets"
    asset_out_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    used_names: set[str] = set()
    for asset in project.get("assets", []):
        source = Path(str(asset.get("source", "")))
        item = dict(asset)
        item["render_src"] = None
        if source.exists() and source.is_file() and _media_kind(asset) in {"image", "video"}:
            name = source.name
            stem = source.stem
            suffix = source.suffix
            index = 1
            while name in used_names:
                name = f"{stem}-{index}{suffix}"
                index += 1
            used_names.add(name)
            target = asset_out_dir / name
            shutil.copy2(source, target)
            item["render_src"] = f"assets/{name}"
        copied.append(item)

    audio_info = dict(project.get("audio") or {})
    audio_path = Path(str(audio_info.get("path") or ""))
    if audio_path.exists() and audio_path.is_file():
        audio_name = audio_path.name
        target = asset_out_dir / audio_name
        if target.resolve() != audio_path.resolve():
            shutil.copy2(audio_path, target)
        audio_info["render_src"] = f"assets/{audio_name}"
    else:
        audio_info["render_src"] = None
    return copied, audio_info


def _render_html(project: dict, html_dir: Path) -> Path:
    copied_assets, audio_info = _copy_render_assets(project, html_dir)
    width = int(project["resolution"]["width"])
    height = int(project["resolution"]["height"])
    duration = float(project["duration"])
    fps = int(project.get("fps", 30))
    palette = list((project.get("style") or {}).get("palette") or ["#0B0F19", "#F8FAFC", "#22D3EE", "#A3E635"])
    while len(palette) < 4:
        palette.append(palette[-1])

    image_assets = [asset for asset in copied_assets if _media_kind(asset) == "image" and asset.get("render_src")]
    frames = [_frame_copy(frame, project, index) for index, frame in enumerate(project.get("frames", []))]
    title = project.get("title") or project.get("template_name") or "Hyperframes Video Studio"
    audio_tag = ""
    if audio_info.get("render_src"):
        audio_tag = (
            f'<audio id="narration" src="{_html_escape(audio_info["render_src"])}" '
            f'data-start="0" data-duration="{duration:.3f}" data-track-index="{len(frames) + 2}" '
            'data-volume="1" preload="auto"></audio>'
        )

    frame_html = []
    for index, frame in enumerate(frames):
        media = image_assets[index % len(image_assets)] if image_assets else None
        media_html = _generated_visual(project, frame, index)
        if media:
            media_html = f'<img class="visual" src="{_html_escape(media["render_src"])}" alt="">'
        start = float(frame.get("start", 0))
        scene_duration = float(frame.get("duration", 1))
        frame_html.append(
            f'''
      <div id="scene-{index}" class="clip scene scene-{index}" data-start="{start:.3f}" data-duration="{scene_duration:.3f}" data-track-index="{index + 1}">
        <div class="backdrop"></div>
        <div class="scene-content">
          <div class="copy">
            <p class="eyebrow">{_html_escape(project.get("template_name"))}</p>
            <h1>{_html_escape(frame.get("headline"))}</h1>
            <p class="caption">{_html_escape(frame.get("caption"))}</p>
          </div>
          <div class="visual-block">{media_html}</div>
        </div>
      </div>'''
        )

    html = f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="hyperframes:duration" content="{duration:.3f}">
  <meta name="hyperframes:fps" content="{fps}">
  <meta name="hyperframes:width" content="{width}">
  <meta name="hyperframes:height" content="{height}">
  <title>{_html_escape(title)}</title>
  <style>
    :root {{
      --w: {width}px;
      --h: {height}px;
      --duration: {duration:.3f}s;
      --bg: {_css_string(palette[0])};
      --fg: {_css_string(palette[1])};
      --accent: {_css_string(palette[2])};
      --accent-2: {_css_string(palette[3])};
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    * {{ box-sizing: border-box; }}
    html, body {{
      margin: 0;
      width: 100%;
      height: 100%;
      overflow: hidden;
      background: var(--bg);
      color: var(--fg);
    }}
    body {{
      width: var(--w);
      height: var(--h);
      transform-origin: top left;
    }}
    #main {{
      position: relative;
      width: var(--w);
      height: var(--h);
      overflow: hidden;
      isolation: isolate;
      background:
        radial-gradient(circle at 75% 18%, color-mix(in srgb, var(--accent) 30%, transparent), transparent 28%),
        linear-gradient(135deg, color-mix(in srgb, var(--bg) 88%, #000), var(--bg));
    }}
    .scene {{
      position: absolute;
      inset: 0;
      overflow: hidden;
      pointer-events: none;
    }}
    .backdrop {{
      position: absolute;
      inset: 0;
      background:
        linear-gradient(90deg, color-mix(in srgb, var(--accent) 12%, transparent), transparent 55%),
        repeating-linear-gradient(90deg, transparent 0 86px, color-mix(in srgb, var(--fg) 6%, transparent) 86px 87px);
      opacity: .75;
    }}
    .scene-content {{
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      display: grid;
      grid-template-columns: 1.02fr .98fr;
      gap: 4%;
      align-items: center;
      padding: 7%;
      box-sizing: border-box;
      z-index: 2;
    }}
    .copy {{
      max-width: 92%;
    }}
    .eyebrow {{
      margin: 0 0 22px;
      color: var(--accent);
      font-size: clamp(22px, 2vw, 38px);
      font-weight: 750;
      text-transform: uppercase;
      letter-spacing: 0;
    }}
    h1 {{
      margin: 0;
      font-size: clamp(64px, 6.4vw, 138px);
      line-height: .95;
      letter-spacing: 0;
      text-wrap: balance;
    }}
    .caption {{
      margin: 30px 0 0;
      max-width: 820px;
      font-size: clamp(28px, 2.3vw, 48px);
      line-height: 1.18;
      color: color-mix(in srgb, var(--fg) 78%, transparent);
    }}
    .visual-block {{
      position: relative;
      aspect-ratio: 4 / 3;
      display: grid;
      place-items: center;
      min-width: 0;
      border: 1px solid color-mix(in srgb, var(--fg) 18%, transparent);
      background:
        linear-gradient(135deg, color-mix(in srgb, var(--fg) 10%, transparent), color-mix(in srgb, var(--accent) 10%, transparent));
      box-shadow: 0 40px 120px color-mix(in srgb, #000 34%, transparent);
      overflow: hidden;
    }}
    .visual {{
      width: 100%;
      height: 100%;
      object-fit: cover;
    }}
    .visual-panel {{
      width: 100%;
      height: 100%;
      padding: 8%;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      background:
        radial-gradient(circle at 20% 12%, color-mix(in srgb, var(--accent) 28%, transparent), transparent 34%),
        linear-gradient(160deg, color-mix(in srgb, var(--fg) 10%, transparent), color-mix(in srgb, var(--bg) 72%, transparent));
    }}
    .visual-panel strong {{
      font-size: clamp(34px, 3vw, 64px);
      line-height: 1.02;
      max-width: 86%;
    }}
    .visual-panel em {{
      align-self: flex-end;
      font-style: normal;
      font-size: clamp(54px, 5vw, 108px);
      font-weight: 850;
      color: var(--accent-2);
    }}
    .chips, .nodes {{
      display: flex;
      flex-wrap: wrap;
      gap: 14px;
      max-width: 90%;
    }}
    .chips span, .nodes span {{
      padding: 12px 16px;
      border: 1px solid color-mix(in srgb, var(--fg) 22%, transparent);
      background: color-mix(in srgb, var(--bg) 55%, transparent);
      font-size: clamp(20px, 1.5vw, 32px);
    }}
    .nodes span {{
      border-color: color-mix(in srgb, var(--accent) 48%, transparent);
    }}
    .bars {{
      display: grid;
      gap: 18px;
      width: 88%;
    }}
    .bars i {{
      position: relative;
      display: block;
      height: 38px;
      background: color-mix(in srgb, var(--fg) 10%, transparent);
      overflow: hidden;
    }}
    .bars i::before {{
      content: "";
      position: absolute;
      inset: 0 auto 0 0;
      width: var(--bar);
      background: linear-gradient(90deg, var(--accent), var(--accent-2));
    }}
    .bars b {{
      position: relative;
      z-index: 1;
      padding-left: 14px;
      line-height: 38px;
      font-size: 20px;
      color: var(--fg);
    }}
    .quote-panel strong {{
      font-size: clamp(48px, 4vw, 86px);
      line-height: 1.06;
    }}
    .progress {{
      position: absolute;
      left: 0;
      bottom: 0;
      height: 10px;
      width: 100%;
      transform: scaleX(0);
      transform-origin: left center;
      background: linear-gradient(90deg, var(--accent), var(--accent-2));
      z-index: 8;
    }}
    @media (max-aspect-ratio: 1/1) {{
      .scene-content {{
        grid-template-columns: 1fr;
        grid-template-rows: auto 1fr;
        padding: 8%;
      }}
      .visual-block {{ width: 100%; align-self: end; }}
    }}
  </style>
</head>
<body>
  <div id="main" data-composition-id="main" data-start="0" data-duration="{duration:.3f}" data-width="{width}" data-height="{height}">
    {"".join(frame_html)}
    <div class="progress"></div>
    {audio_tag}
  </div>
  <script id="video-project" type="application/json">{_script_json(project)}</script>
  <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
  <script>
    window.__timelines = window.__timelines || {{}};
    const tl = gsap.timeline({{ paused: true }});
    tl.set(".scene .copy, .scene .visual-block", {{ opacity: 1, x: 0, y: 0, scale: 1 }}, 0);
    tl.fromTo(".progress", {{ scaleX: 0, transformOrigin: "left center" }}, {{ scaleX: 1, duration: {duration:.6f}, ease: "none" }}, 0);
'''
    for index, frame in enumerate(frames):
        start = float(frame.get("start", 0))
        scene_duration = float(frame.get("duration", 1))
        exit_time = max(start + scene_duration - 0.45, start + 0.1)
        html += f'''
    tl.from("#scene-{index} .copy", {{ y: 60, opacity: 0, duration: 0.55, ease: "power3.out" }}, {start + 0.12:.3f});
    tl.from("#scene-{index} .visual-block", {{ y: 48, scale: 0.96, opacity: 0, duration: 0.55, ease: "power3.out" }}, {start + 0.22:.3f});
    tl.to("#scene-{index} .copy", {{ y: -32, opacity: 0, duration: 0.35, ease: "power2.in" }}, {exit_time:.3f});
    tl.to("#scene-{index} .visual-block", {{ y: -24, opacity: 0, duration: 0.35, ease: "power2.in" }}, {exit_time + 0.05:.3f});
    tl.set("#scene-{index} .copy", {{ opacity: 0 }}, {start + scene_duration:.3f});
    tl.set("#scene-{index} .visual-block", {{ opacity: 0 }}, {start + scene_duration:.3f});
'''
    html += f'''
    window.__timelines["main"] = tl;
  </script>
</body>
</html>
'''
    html_dir.mkdir(parents=True, exist_ok=True)
    html_path = html_dir / "index.html"
    html_path.write_text(html, encoding="utf-8")
    (html_dir / "project.json").write_text(json.dumps(project, indent=2, sort_keys=True), encoding="utf-8")
    return html_path


def _load_manifest(path_value: str) -> dict | None:
    path = _resolve_path(path_value)
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _assets_from_manifest(manifest: dict | None) -> list[str]:
    if not manifest:
        return []
    values = []
    for item in manifest.get("items", []):
        if item.get("kind") in {"image", "audio", "video", "document", "text"} and item.get("path"):
            values.append(item["path"])
    return values


def _content_brief_from_manifest(manifest: dict | None) -> str:
    if not manifest:
        return ""
    excerpts = []
    for item in manifest.get("items", []):
        text = str(item.get("text_excerpt") or "").strip()
        if text:
            excerpts.append(f"{item.get('name')}: {text[:800]}")
        if len(excerpts) >= 8:
            break
    return "\n".join(excerpts)


def _wav_duration(path: Path) -> float | None:
    try:
        with wave.open(str(path), "rb") as handle:
            return handle.getnframes() / float(handle.getframerate())
    except Exception:
        return None


def _ffprobe_duration(path: Path) -> float | None:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe or not path.exists():
        return _wav_duration(path)
    command = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    try:
        return float(subprocess.check_output(command, text=True).strip())
    except Exception:
        return _wav_duration(path)


def _scale_frames(frames: list[dict], target_duration: float | None) -> list[dict]:
    if not target_duration:
        return frames
    current = sum(float(frame["duration"]) for frame in frames)
    if current <= 0:
        return frames
    scale = target_duration / current
    scaled = []
    start = 0.0
    for frame in frames:
        duration = round(max(0.5, float(frame["duration"]) * scale), 3)
        item = dict(frame)
        item["duration"] = duration
        item["start"] = round(start, 3)
        start += duration
        item["end"] = round(start, 3)
        scaled.append(item)
    return scaled


def _resolution_for_aspect(aspect_ratio: str | None, default: dict) -> dict:
    mapping = {
        "16:9": {"width": 1920, "height": 1080},
        "9:16": {"width": 1080, "height": 1920},
        "1:1": {"width": 1080, "height": 1080},
        "4:5": {"width": 1080, "height": 1350},
    }
    return mapping.get(str(aspect_ratio or ""), default)


def build_project(request: dict) -> dict:
    templates = load_templates()
    template_key = request.get("template")
    if template_key not in templates:
        return {
            "status": "invalid_request",
            "message": f"Unknown template '{template_key}'.",
            "templates": sorted(templates),
        }

    template = templates[template_key]
    asset_manifest = None
    if request.get("asset_manifest"):
        asset_manifest = _load_manifest(str(request["asset_manifest"]))

    manifest_brief = _content_brief_from_manifest(asset_manifest)
    brief = str(request.get("brief", "")).strip()
    if manifest_brief:
        brief = f"{brief}\n\nSource material excerpts:\n{manifest_brief}".strip()
    if not brief:
        return {"status": "invalid_request", "message": "Missing non-empty brief."}

    audio = request.get("audio")
    audio_path = _resolve_path(audio) if audio else None
    audio_duration = _ffprobe_duration(audio_path) if audio_path else None
    target_duration = request.get("duration_seconds") or audio_duration
    if target_duration is not None:
        target_duration = float(target_duration)

    frames = _scale_frames([dict(frame) for frame in template["frames"]], target_duration)
    asset_values = list(request.get("assets", [])) + _assets_from_manifest(asset_manifest)
    resolved_assets = resolve_assets(asset_values, bool(request.get("embed_assets", False)))
    resolution = _resolution_for_aspect(request.get("aspect_ratio"), template["resolution"])

    total_duration = round(sum(float(frame["duration"]) for frame in frames), 3)

    # frame_contents: optional per-frame headline/caption from the calling agent
    frame_contents = request.get("frame_contents") or []

    project = {
        "schema": "hyperframes.video_studio.v1",
        "created_at": int(time.time()),
        "template": template_key,
        "template_name": template.get("name", template_key),
        "category": template.get("category"),
        "best_for": template.get("best_for"),
        "title": request.get("title") or template["name"],
        "brief": brief,
        "frame_contents": frame_contents,
        "resolution": resolution,
        "fps": int(request.get("fps", 30)),
        "duration": total_duration,
        "style": template["style"],
        "assets": resolved_assets,
        "asset_manifest": asset_manifest.get("manifest_path") if asset_manifest else None,
        "asset_summary": asset_manifest.get("summary") if asset_manifest else None,
        "audio": {
            "path": str(audio_path.resolve()) if audio_path else None,
            "duration": round(audio_duration, 3) if audio_duration else None,
        },
        "frames": frames,
        "starter_questions": template.get("starter_questions", []),
        "directives": {
            "treat_assets_as_data": True,
            "render_cache": str(RENDER_DIR.resolve()),
            "human_confirmation_required": True,
        },
    }

    PROJECT_DIR.mkdir(parents=True, exist_ok=True)
    slug = _safe_name(str(request.get("title") or template_key))
    project_path = PROJECT_DIR / f"{slug}-{int(time.time())}.json"
    project_path.write_text(json.dumps(project, indent=2, sort_keys=True), encoding="utf-8")
    html_dir = PROJECT_DIR / f"{slug}-{int(time.time())}-html"
    html_path = _render_html(project, html_dir)

    result = {
        "status": "ok",
        "project_json": str(project_path.resolve()),
        "render_dir": str(html_dir.resolve()),
        "html": str(html_path.resolve()),
        "project": project,
        "needs_confirmation": bool(request.get("render", False)),
        "message": "Renderable HTML project generated. Confirm before running Hyperframes render." if request.get("render") else "Renderable HTML project generated.",
    }
    return result


def find_hyperframes() -> str | None:
    candidates = [
        CACHE_DIR / "npm" / "node_modules" / ".bin" / ("hyperframes.cmd" if sys.platform == "win32" else "hyperframes"),
        BASE_DIR / "node_modules" / ".bin" / ("hyperframes.cmd" if sys.platform == "win32" else "hyperframes"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return shutil.which("hyperframes")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Hyperframes declarative JSON from a Video Studio request.")
    parser.add_argument("--input-json", required=True)
    args = parser.parse_args()

    result = build_project(_read_json(Path(args.input_json)))
    _print(result)
    return 0 if result.get("status") == "ok" else 2


if __name__ == "__main__":
    sys.exit(main())
