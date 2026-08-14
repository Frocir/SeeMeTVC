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


DEMO_BGM_NAME = "demo_bgm_v1.wav"
DEMO_BGM_URL = f"/uploads/_mock/{DEMO_BGM_NAME}"
DEMO_T2I_NAME = "demo_t2i_v1.png"
DEMO_T2I_URL = f"/uploads/_mock/{DEMO_T2I_NAME}"


async def ensure_demo_bgm(duration_seconds: int = 12) -> str:
    """Quiet sine bed for official templates (replaceable, not a commercial track)."""
    duration_seconds = max(4, min(int(duration_seconds or 12), 30))
    mock_dir = uploads_root() / "_mock"
    mock_dir.mkdir(parents=True, exist_ok=True)
    path = mock_dir / DEMO_BGM_NAME
    if path.is_file() and path.stat().st_size > 400:
        return DEMO_BGM_URL
    ffmpeg = _ffmpeg_bin()
    tmp_out = mock_dir / f"{DEMO_BGM_NAME}.partial.wav"
    await run_ffmpeg(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=f=196:d={duration_seconds}",
            "-af",
            "volume=0.08",
            str(tmp_out),
        ]
    )
    if path.exists():
        path.unlink()
    tmp_out.replace(path)
    if not path.is_file() or path.stat().st_size < 400:
        raise MediaOpsError("演示床垫音频生成失败")
    return DEMO_BGM_URL


async def ensure_demo_t2i() -> str:
    """Placeholder still for local text-to-image simulate."""
    mock_dir = uploads_root() / "_mock"
    mock_dir.mkdir(parents=True, exist_ok=True)
    path = mock_dir / DEMO_T2I_NAME
    if path.is_file() and path.stat().st_size > 400:
        return DEMO_T2I_URL
    ffmpeg = _ffmpeg_bin()
    tmp_out = mock_dir / f"{DEMO_T2I_NAME}.partial.png"
    await run_ffmpeg(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x2a1a22:s=720x1280:d=1",
            "-frames:v",
            "1",
            str(tmp_out),
        ]
    )
    if path.exists():
        path.unlink()
    tmp_out.replace(path)
    if not path.is_file() or path.stat().st_size < 400:
        raise MediaOpsError("文生图占位图生成失败")
    return DEMO_T2I_URL


async def mix_audio(
    user_id: int,
    video_url: str,
    bgm_url: str,
    vo_url: str,
    *,
    bgm_volume: float = 0.22,
    vo_volume: float = 1.0,
    duck: float = 0.55,
) -> str:
    """Overlay looping BGM + VO onto a video. All three inputs required."""
    if not video_url or not bgm_url or not vo_url:
        raise MediaOpsError("混音需要视频、BGM 和口播三条输入")
    ffmpeg = _ffmpeg_bin()
    user_dir = uploads_root() / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    out_name = f"{uuid.uuid4().hex}_mix.mp4"
    out_path = user_dir / out_name
    bgm_vol = max(0.01, min(float(bgm_volume), 2.0))
    vo_vol = max(0.01, min(float(vo_volume), 2.0))
    duck_mul = max(0.05, min(float(duck), 1.0))

    with tempfile.TemporaryDirectory(prefix="seemetvc_mix_") as tmp:
        tmp_path = Path(tmp)
        video = tmp_path / "v.mp4"
        bgm = tmp_path / "bgm.mp3"
        vo = tmp_path / "vo.mp3"
        await _download(video_url, video)
        await _download(bgm_url, bgm)
        await _download(vo_url, vo)
        filt = (
            f"[1:a]aloop=loop=-1:size=2e+09,volume={bgm_vol},aformat=sample_fmts=fltp:channel_layouts=stereo[bg];"
            f"[2:a]volume={vo_vol},aformat=sample_fmts=fltp:channel_layouts=stereo[vo];"
            f"[bg]volume={duck_mul}[bgd];"
            f"[bgd][vo]amix=inputs=2:duration=first:dropout_transition=0[a]"
        )
        await run_ffmpeg(
            [
                ffmpeg,
                "-y",
                "-i",
                str(video),
                "-i",
                str(bgm),
                "-i",
                str(vo),
                "-filter_complex",
                filt,
                "-map",
                "0:v:0",
                "-map",
                "[a]",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-shortest",
                "-movflags",
                "+faststart",
                str(out_path),
            ]
        )
    if not out_path.is_file() or out_path.stat().st_size < 1000:
        raise MediaOpsError("混音输出为空")
    return _public_upload_url(user_id, out_name)


async def demux_av(user_id: int, video_url: str) -> tuple[str, str]:
    """Split a clip into silent video + audio. Fails if there is no audio stream."""
    if not video_url:
        raise MediaOpsError("拆轨缺少输入视频")
    ffmpeg = _ffmpeg_bin()
    user_dir = uploads_root() / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    silent_name = f"{uuid.uuid4().hex}_demux.mp4"
    audio_name = f"{uuid.uuid4().hex}_demux.m4a"
    silent_path = user_dir / silent_name
    audio_path = user_dir / audio_name

    with tempfile.TemporaryDirectory(prefix="seemetvc_demux_") as tmp:
        src = Path(tmp) / "in.mp4"
        await _download(video_url, src)
        try:
            await run_ffmpeg(
                [
                    ffmpeg,
                    "-y",
                    "-i",
                    str(src),
                    "-vn",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    str(audio_path),
                ]
            )
        except MediaOpsError as exc:
            raise MediaOpsError("视频没有音轨，无法拆分") from exc
        await run_ffmpeg(
            [
                ffmpeg,
                "-y",
                "-i",
                str(src),
                "-an",
                "-c:v",
                "copy",
                "-movflags",
                "+faststart",
                str(silent_path),
            ]
        )
    if not audio_path.is_file() or audio_path.stat().st_size < 64:
        raise MediaOpsError("视频没有音轨，无法拆分")
    if not silent_path.is_file() or silent_path.stat().st_size < 1000:
        raise MediaOpsError("拆出的静音视频为空")
    return _public_upload_url(user_id, silent_name), _public_upload_url(user_id, audio_name)


async def trim_audio(user_id: int, audio_url: str, start: float, end: float) -> str:
    """Cut an audio file. If end <= start, return the original URL unchanged."""
    if not audio_url:
        raise MediaOpsError("音频裁切缺少输入")
    start = max(0.0, float(start or 0))
    end = float(end or 0)
    if end <= start:
        return audio_url
    ffmpeg = _ffmpeg_bin()
    user_dir = uploads_root() / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    out_name = f"{uuid.uuid4().hex}_atrim.m4a"
    out_path = user_dir / out_name
    with tempfile.TemporaryDirectory(prefix="seemetvc_atrim_") as tmp:
        src = Path(tmp) / "in.audio"
        await _download(audio_url, src)
        await run_ffmpeg(
            [
                ffmpeg,
                "-y",
                "-i",
                str(src),
                "-ss",
                f"{start:.3f}",
                "-to",
                f"{end:.3f}",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                str(out_path),
            ]
        )
    if not out_path.is_file() or out_path.stat().st_size < 64:
        raise MediaOpsError("音频裁切输出为空")
    return _public_upload_url(user_id, out_name)


def _subtitle_fontfile_prefix() -> str:
    """ffmpeg drawtext fontfile=... or empty to use the encoder default.

    Prefer SUBTITLE_FONT / settings.subtitle_font. Windows fonts come from %WINDIR%
    when set; never assume C:\\Windows. Linux uses common distro packages.
    """
    candidates: list[Path] = []
    explicit = (
        (get_settings().subtitle_font or "").strip().strip('"')
        or (os.environ.get("SUBTITLE_FONT") or "").strip().strip('"')
    )
    if explicit:
        candidates.append(Path(explicit))
    windir = (os.environ.get("WINDIR") or "").strip()
    if windir:
        fonts = Path(windir) / "Fonts"
        candidates.extend(
            (
                fonts / "msyh.ttc",
                fonts / "msyh.ttf",
                fonts / "arial.ttf",
            )
        )
    candidates.extend(
        (
            Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
            Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
        )
    )
    for cand in candidates:
        try:
            if cand.is_file():
                ff = str(cand.resolve()).replace("\\", "/").replace(":", "\\:")
                return f"fontfile={ff}:"
        except OSError:
            continue
    return ""


async def burn_subtitle(user_id: int, video_url: str, text: str) -> str:
    """Burn a single slogan line onto the lower third. Empty text returns the source URL."""
    if not video_url:
        raise MediaOpsError("字幕缺少输入视频")
    slogan = (text or "").strip()
    if not slogan:
        return video_url
    safe = (
        slogan.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace(":", "\\:")
        .replace("%", "\\%")
    )
    font_prefix = _subtitle_fontfile_prefix()
    ffmpeg = _ffmpeg_bin()
    user_dir = uploads_root() / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    out_name = f"{uuid.uuid4().hex}_sub.mp4"
    out_path = user_dir / out_name
    with tempfile.TemporaryDirectory(prefix="seemetvc_sub_") as tmp:
        src = Path(tmp) / "in.mp4"
        await _download(video_url, src)
        draw = (
            f"drawtext={font_prefix}text='{safe}':fontsize=36:fontcolor=white:"
            "x=(w-text_w)/2:y=h-80:box=1:boxcolor=black@0.45:boxborderw=12"
        )
        await run_ffmpeg(
            [
                ffmpeg,
                "-y",
                "-i",
                str(src),
                "-vf",
                draw,
                "-c:a",
                "copy",
                "-movflags",
                "+faststart",
                str(out_path),
            ]
        )
    if not out_path.is_file() or out_path.stat().st_size < 1000:
        raise MediaOpsError("字幕烧录输出为空")
    return _public_upload_url(user_id, out_name)
