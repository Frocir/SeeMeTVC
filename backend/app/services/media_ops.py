"""Local ffmpeg helpers for trim + concat (beauty canvas tools)."""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import uuid
from pathlib import Path

import httpx

from app.api.uploads import uploads_root
from app.config import get_settings


class MediaOpsError(Exception):
    pass


def _as_ffmpeg_bin(path: Path) -> str | None:
    try:
        if path.is_file():
            return str(path.resolve())
    except OSError:
        return None
    return None


def _ffmpeg_from_env() -> str | None:
    for raw in (
        (get_settings().ffmpeg_path or "").strip().strip('"'),
        (os.environ.get("FFMPEG_PATH") or "").strip().strip('"'),
    ):
        if not raw:
            continue
        found = _as_ffmpeg_bin(Path(raw))
        if found:
            return found
    return None


def _ffmpeg_fallback_candidates() -> list[Path]:
    """User-scoped guesses only (PATH / FFMPEG_PATH preferred). No machine-wide roots."""
    home = Path.home()
    local = home / "AppData" / "Local"
    return [
        home / "scoop" / "apps" / "ffmpeg" / "current" / "bin" / "ffmpeg.exe",
        local / "Microsoft" / "WinGet" / "Links" / "ffmpeg.exe",
        local / "Microsoft" / "WinGet" / "Packages",  # directory → rglob
    ]


def _ffmpeg_bin() -> str:
    """Resolve ffmpeg via env, PATH, then common install layouts under the current user."""
    from_env = _ffmpeg_from_env()
    if from_env:
        return from_env

    which = shutil.which("ffmpeg")
    if which:
        return which

    for c in _ffmpeg_fallback_candidates():
        try:
            found = _as_ffmpeg_bin(c)
            if found:
                return found
            if c.is_dir():
                nested = next(c.rglob("ffmpeg.exe"), None)
                if nested is not None:
                    found = _as_ffmpeg_bin(nested)
                    if found:
                        return found
        except OSError:
            continue

    raise MediaOpsError(
        "未找到 ffmpeg。请安装后重启后端，或在 backend/.env 设置 FFMPEG_PATH=<ffmpeg 可执行文件路径>"
    )


async def run_ffmpeg(cmd: list[str]) -> None:
    """Run ffmpeg. Prefer thread+subprocess so Windows SelectorEventLoop (uvicorn) works.

    ``asyncio.create_subprocess_exec`` raises empty ``NotImplementedError`` on
    Windows when the loop is not ProactorEventLoop — that broke API-path trim/mux.
    """
    import subprocess

    def _sync() -> None:
        proc = subprocess.run(cmd, capture_output=True, check=False)
        if proc.returncode != 0:
            msg = (proc.stderr or b"").decode("utf-8", errors="ignore")[-800:]
            raise MediaOpsError(f"ffmpeg 失败：{msg or proc.returncode}")

    await asyncio.to_thread(_sync)


async def _download(url: str, dest: Path) -> None:
    """Fetch a clip to disk. Prefer local /uploads files; remote uses proxy-aware client."""
    from app.api.uploads import local_upload_path
    from app.services.net import make_async_client

    raw = (url or "").strip()
    if not raw:
        raise MediaOpsError("片段地址为空")

    # Same-origin uploads: read from disk (API serves /uploads, not Vite :5173)
    local = local_upload_path(raw)
    if local is not None and local.is_file():
        dest.write_bytes(local.read_bytes())
        return

    if raw.startswith("/") and not raw.startswith("//"):
        # Relative path → try uploads root, then hit local API
        rel = raw.lstrip("/")
        if rel.startswith("uploads/"):
            candidate = uploads_root() / rel[len("uploads/") :]
            if candidate.is_file():
                dest.write_bytes(candidate.read_bytes())
                return
        base = (get_settings().public_api_base_url or "").strip().rstrip("/")
        if not base:
            raise MediaOpsError(
                "片段不在本机素材目录，且未配置 PUBLIC_API_BASE_URL，无法下载。"
                "请使用项目内上传的视频，或在部署环境设置可访问的 API 根地址。"
            )
        fetch = f"{base}{raw}"
    else:
        fetch = raw

    try:
        async with make_async_client(timeout=120.0) as client:
            resp = await client.get(fetch, follow_redirects=True)
            if resp.status_code >= 400:
                raise MediaOpsError(f"下载片段失败 HTTP {resp.status_code}: {fetch[:120]}")
            if not resp.content:
                raise MediaOpsError(f"下载片段为空: {fetch[:120]}")
            dest.write_bytes(resp.content)
    except MediaOpsError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise MediaOpsError(f"下载片段失败（{fetch[:100]}）：{exc}") from exc


def _public_upload_url(user_id: int, filename: str) -> str:
    return f"/uploads/{user_id}/{filename}"


async def ensure_mock_demo_clip(duration_seconds: int = 5) -> str:
    """Create (or reuse) a local demo mp4 for the mock provider.

    Stored under uploads/_mock/ so trim/mux can read from disk without hitting
    remote sample URLs (which often return 403).
    """
    duration_seconds = max(1, min(int(duration_seconds or 5), 15))
    mock_dir = uploads_root() / "_mock"
    mock_dir.mkdir(parents=True, exist_ok=True)
    # v2 LocalSimulate: SMPTE bars (old clips were near-black / labeled MOCK)
    name = f"demo_localsim_v2_{duration_seconds}s.mp4"
    path = mock_dir / name
    public = f"/uploads/_mock/{name}"
    if path.is_file() and path.stat().st_size > 1000:
        return public

    ffmpeg = _ffmpeg_bin()
    tmp_out = mock_dir / f"{name}.partial.mp4"

    async def _encode(with_drawtext: bool) -> None:
        cmd = [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"smptebars=s=640x360:d={duration_seconds}",
            "-f",
            "lavfi",
            "-i",
            f"sine=f=440:d={duration_seconds}",
        ]
        if with_drawtext:
            cmd += [
                "-vf",
                (
                    f"drawtext=text='LocalSimulate {duration_seconds}s':"
                    "fontsize=36:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2:"
                    "box=1:boxcolor=black@0.45:boxborderw=12"
                ),
            ]
        cmd += [
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "veryfast",
            "-crf",
            "28",
            "-c:a",
            "aac",
            "-shortest",
            "-movflags",
            "+faststart",
            str(tmp_out),
        ]
        await run_ffmpeg(cmd)

    try:
        try:
            await _encode(True)
        except MediaOpsError:
            await _encode(False)
        if path.exists():
            path.unlink()
        tmp_out.replace(path)
    except Exception:
        if tmp_out.exists():
            try:
                tmp_out.unlink()
            except OSError:
                pass
        raise
    if not path.is_file() or path.stat().st_size < 1000:
        raise MediaOpsError("mock 样片生成失败")
    return public


async def concat_videos(user_id: int, urls: list[str]) -> str:
    if not urls:
        raise MediaOpsError("没有可拼接的视频")
    # Dedupe while preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for u in urls:
        if u and u not in seen:
            seen.add(u)
            uniq.append(u)
    urls = uniq
    if len(urls) == 1:
        return urls[0]

    ffmpeg = _ffmpeg_bin()
    user_dir = uploads_root() / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    out_name = f"{uuid.uuid4().hex}_mux.mp4"
    out_path = user_dir / out_name

    with tempfile.TemporaryDirectory(prefix="seemetvc_mux_") as tmp:
        tmp_path = Path(tmp)
        parts: list[Path] = []
        for i, url in enumerate(urls):
            part = tmp_path / f"p{i}.mp4"
            await _download(url, part)
            # Re-encode to aligned mp4 for concat demuxer reliability
            aligned = tmp_path / f"a{i}.mp4"
            await run_ffmpeg(
                [
                    ffmpeg,
                    "-y",
                    "-i",
                    str(part),
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "23",
                    "-c:a",
                    "aac",
                    "-movflags",
                    "+faststart",
                    str(aligned),
                ]
            )
            parts.append(aligned)

        list_file = tmp_path / "list.txt"
        # ffmpeg concat demuxer on Windows needs escaped paths
        list_file.write_text(
            "\n".join(f"file '{p.resolve().as_posix()}'" for p in parts),
            encoding="utf-8",
        )
        await run_ffmpeg(
            [
                ffmpeg,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_file),
                "-c",
                "copy",
                str(out_path),
            ]
        )

    return _public_upload_url(user_id, out_name)


async def trim_video(user_id: int, url: str, start: float, end: float) -> str:
    if end <= start:
        raise MediaOpsError("裁剪结束时间必须大于起始时间")
    ffmpeg = _ffmpeg_bin()
    user_dir = uploads_root() / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    out_name = f"{uuid.uuid4().hex}_trim.mp4"
    out_path = user_dir / out_name
    duration = max(0.1, end - start)

    with tempfile.TemporaryDirectory(prefix="seemetvc_trim_") as tmp:
        src = Path(tmp) / "in.mp4"
        await _download(url, src)
        await run_ffmpeg(
            [
                ffmpeg,
                "-y",
                "-ss",
                str(start),
                "-i",
                str(src),
                "-t",
                str(duration),
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(out_path),
            ]
        )

    return _public_upload_url(user_id, out_name)
