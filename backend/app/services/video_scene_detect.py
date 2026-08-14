"""Scene-boundary keyframe extraction for reference-video reverse prompting."""

from __future__ import annotations

import asyncio
import re
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.api.uploads import uploads_root
from app.services import media_ops


@dataclass(slots=True)
class DetectedScene:
    index: int
    start_time: float
    end_time: float
    frame_url: str
    score: float

    def as_dict(self) -> dict[str, float | int | str]:
        return {
            "index": self.index,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "frame_url": self.frame_url,
            "score": self.score,
        }


_SCENE_RE = re.compile(r"pts_time:(?P<time>\d+(?:\.\d+)?)")
_SCORE_RE = re.compile(r"lavfi\.scene_score=(?P<score>\d+(?:\.\d+)?)")


def _public_upload_url(user_id: int, relative_name: str) -> str:
    return f"/uploads/{user_id}/{relative_name}"


def _dedupe_times(times: list[tuple[float, float]], *, min_gap: float) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for ts, score in sorted(times, key=lambda x: x[0]):
        if ts <= 0.05:
            continue
        if out and ts - out[-1][0] < min_gap:
            if score > out[-1][1]:
                out[-1] = (ts, score)
            continue
        out.append((ts, score))
    return out


def _scene_spans(
    cuts: list[tuple[float, float]],
    *,
    duration: float,
    max_scenes: int,
    min_scene_duration: float,
) -> list[tuple[float, float, float]]:
    boundaries = [0.0, *[t for t, _ in cuts if 0 < t < duration], duration]
    spans: list[tuple[float, float, float]] = []
    for idx in range(len(boundaries) - 1):
        start = boundaries[idx]
        end = boundaries[idx + 1]
        if end - start < min_scene_duration and spans:
            prev_start, _, prev_score = spans[-1]
            cut_score = cuts[idx - 1][1] if 0 <= idx - 1 < len(cuts) else 0.0
            spans[-1] = (prev_start, end, max(prev_score, cut_score))
            continue
        score = cuts[idx - 1][1] if 0 <= idx - 1 < len(cuts) else 0.0
        spans.append((start, end, score))

    if len(spans) <= max_scenes:
        return spans

    ranked = sorted(enumerate(spans), key=lambda item: item[1][2], reverse=True)[:max_scenes]
    return [spans[i] for i, _ in sorted(ranked, key=lambda item: item[0])]


def _even_spans(duration: float, max_scenes: int) -> list[tuple[float, float, float]]:
    count = max(1, min(max_scenes, 6))
    if duration <= 0:
        return [(0.0, 2.0, 0.0)]
    step = duration / count
    return [(i * step, min(duration, (i + 1) * step), 0.0) for i in range(count)]


async def _detect_scene_cuts(src: Path, *, threshold: float) -> list[tuple[float, float]]:
    ffmpeg = media_ops.ffmpeg_bin()
    threshold = max(0.05, min(float(threshold or 0.28), 0.95))
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-i",
        str(src),
        "-vf",
        f"select='gt(scene,{threshold:.3f})',showinfo",
        "-vsync",
        "vfr",
        "-f",
        "null",
        "-",
    ]

    def _sync() -> str:
        import subprocess

        proc = subprocess.run(cmd, capture_output=True, check=False)
        text = (proc.stderr or b"").decode("utf-8", errors="ignore")
        if proc.returncode != 0 and not text:
            raise media_ops.MediaOpsError(f"场景检测失败：{proc.returncode}")
        return text

    text = await asyncio.to_thread(_sync)
    cuts: list[tuple[float, float]] = []
    current_score = 0.0
    for line in text.splitlines():
        score_match = _SCORE_RE.search(line)
        if score_match:
            current_score = float(score_match.group("score"))
        time_match = _SCENE_RE.search(line)
        if time_match:
            cuts.append((float(time_match.group("time")), current_score))
            current_score = 0.0
    return _dedupe_times(cuts, min_gap=0.6)


async def detect_scenes(
    user_id: int,
    video_url: str,
    *,
    max_scenes: int = 6,
    threshold: float = 0.28,
    sample_fps: float = 2.0,
    min_scene_duration: float = 0.8,
) -> list[DetectedScene]:
    if not video_url:
        raise media_ops.MediaOpsError("场景检测缺少输入视频")
    max_scenes = max(1, min(int(max_scenes or 6), 8))
    min_scene_duration = max(0.2, float(min_scene_duration or 0.8))
    _ = sample_fps

    user_dir = uploads_root() / str(user_id)
    run_dir_name = f"video_reverse/{uuid.uuid4().hex}"
    out_dir = user_dir / run_dir_name
    out_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="seemetvc_scene_") as tmp:
        tmp_path = Path(tmp)
        src = tmp_path / "input_video"
        await media_ops.download_media(video_url, src)
        duration = await media_ops.probe_duration(src)
        cuts = await _detect_scene_cuts(src, threshold=threshold)
        spans = _scene_spans(
            cuts,
            duration=duration,
            max_scenes=max_scenes,
            min_scene_duration=min_scene_duration,
        )
        if len(spans) < 2:
            spans = _even_spans(duration, max_scenes)

        scenes: list[DetectedScene] = []
        for idx, (start, end, score) in enumerate(spans[:max_scenes], start=1):
            midpoint = start + max(0.05, (end - start) / 2)
            frame_name = f"scene_{idx:03d}.jpg"
            frame_path = out_dir / frame_name
            await media_ops.extract_frame_at(src, frame_path, at_seconds=midpoint)
            if not frame_path.is_file() or frame_path.stat().st_size < 200:
                continue
            scenes.append(
                DetectedScene(
                    index=idx,
                    start_time=round(start, 3),
                    end_time=round(end, 3),
                    frame_url=_public_upload_url(user_id, f"{run_dir_name}/{frame_name}"),
                    score=round(float(score or 0.0), 4),
                )
            )

    if not scenes:
        raise media_ops.MediaOpsError("未能从视频中检测或抽取关键帧")
    return scenes
