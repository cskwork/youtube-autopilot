#!/usr/bin/env python3
"""Generate a Google Flow app commercial with Supertonic Korean narration.

Commercial mode of the youtube-autopilot skill: real product screen captures
+ Google Flow B-roll + independent ducked music + Supertonic Korean TTS into a
vertical 30s app commercial. Shares the vendored google_flow_cli.py with the
main pipeline. The bundled SCENES/flow_prompt are a SpeakCoach-style template;
edit them (or use the generic product-ad mode) for other apps."""

from __future__ import annotations

import argparse
import json
import math
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "speakcoach"
WIDTH = 1080
HEIGHT = 1920
FPS = 30
# Cross-platform Korean-capable font candidates (macOS, Windows, Linux).
# Override with the COMMERCIAL_FONT env var to point at any .ttf/.ttc/.otf.
FONT_CANDIDATES = [
    Path("/System/Library/Fonts/AppleSDGothicNeo.ttc"),
    Path("/System/Library/Fonts/Supplemental/AppleGothic.ttf"),
    Path("C:/Windows/Fonts/malgun.ttf"),
    Path("C:/Windows/Fonts/malgunbd.ttf"),
    Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
]
DEFAULT_FLOW_URL = "https://labs.google/fx/ko/tools/flow/project/YOUR_FLOW_PROJECT_ID"
COMMERCIAL_DURATION = 30.0
FLOW_SEGMENT_DURATION = 10.0
FLOW_MIN_SEGMENT_COUNT = 3
FLOW_MAX_SEGMENT_COUNT = 5
DEFAULT_MUSIC_VOLUME = 0.22


@dataclass(frozen=True)
class Scene:
    key: str
    start: float
    end: float
    eyebrow: str
    title: str
    body: str
    accent: tuple[int, int, int]
    align: str = "top"


SCENES = [
    Scene("home", 0, 5, "SpeakCoach EDU", "영어 말하기를\n게임처럼 시작", "교과서 문장을 듣고 따라 말하는 초등 영어 코치", (255, 183, 77)),
    Scene("practice", 5, 11, "Read Aloud", "듣고, 말하고,\n바로 고쳐요", "STT 기반 녹음 분석과 단어별 발음 피드백", (0, 188, 212), "bottom"),
    Scene("missions", 11, 17, "Polar Quest", "빙하섬 미션으로\n꾸준한 루틴", "8개 교과 단원과 10가지 발음 학습 원리", (126, 87, 194)),
    Scene("rewards", 17, 23, "Weekly Report", "성장은 숫자로,\n동기는 스티커로", "완료 미션, 평균 점수, XP를 한눈에 확인", (255, 112, 67), "bottom"),
    Scene("settings", 23, 29, "Privacy Ready", "모델은 준비,\n기록은 기기 안에", "STT/TTS 상태와 음성 데이터 정책까지 투명하게", (76, 175, 80)),
    Scene("home", 29, 33, "오늘의 한 문장부터", "SpeakCoach EDU", "자신 있게 말하는 영어 습관", (255, 183, 77), "bottom"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="use bundled SpeakCoach captures and Google Flow hero")
    parser.add_argument("--capture-dir", help="directory containing speakcoach_<screen>.png captures")
    parser.add_argument("--transcript-file", help="Korean narration script text file")
    parser.add_argument("--flow-clip", help="existing Google Flow hero MP4")
    parser.add_argument("--run-flow", action="store_true", help="submit a fresh Google Flow generation")
    parser.add_argument("--flow-project-url", default=DEFAULT_FLOW_URL)
    parser.add_argument("--flow-no-attach", action="store_true", help="reuse an existing Playwright Flow session")
    parser.add_argument("--flow-npm-cache", default="", help="npm cache for Flow CLI; empty uses the default environment")
    parser.add_argument("--out-dir", default=".working_dir/youtube-autopilot/commercial")
    parser.add_argument("--final-name", default="speakcoach_edu_flow_supertonic_demo.mp4")
    parser.add_argument("--voice", default="F1")
    parser.add_argument("--speed", default="0.95")
    parser.add_argument("--music-file", default="", help="optional independent background music file")
    parser.add_argument("--music-volume", type=float, default=DEFAULT_MUSIC_VOLUME)
    parser.add_argument("--steps", default="16")
    parser.add_argument("--supertts-command", default="", help="override, e.g. 'supertts' or 'npx ...'")
    parser.add_argument("--supertts-assets", default="", help="optional Supertonic assets directory")
    parser.add_argument("--supertts-npm-cache", default=str(ROOT / ".working_dir" / "npm-cache"))
    return parser.parse_args()


def resolve_inputs(args: argparse.Namespace) -> dict[str, Path]:
    out_dir = Path(args.out_dir).resolve()
    capture_dir = Path(args.capture_dir).resolve() if args.capture_dir else EXAMPLE / "captures"
    transcript = Path(args.transcript_file).resolve() if args.transcript_file else EXAMPLE / "transcript_ko.txt"
    flow_clip = Path(args.flow_clip).resolve() if args.flow_clip else EXAMPLE / "output" / "speakcoach_edu_flow_hero.mp4"
    if args.demo:
        capture_dir = EXAMPLE / "captures"
        transcript = EXAMPLE / "transcript_ko.txt"
        flow_clip = EXAMPLE / "output" / "speakcoach_edu_flow_hero.mp4"
    return {"out_dir": out_dir, "capture_dir": capture_dir, "transcript": transcript, "flow_clip": flow_clip}


def ensure_inputs(paths: dict[str, Path], run_flow: bool) -> None:
    if run_flow and not paths["capture_dir"].exists():
        raise FileNotFoundError(f"missing capture directory: {paths['capture_dir']}")
    if not paths["transcript"].exists():
        raise FileNotFoundError(f"missing transcript: {paths['transcript']}")
    if not run_flow:
        if not paths["flow_clip"].exists():
            raise FileNotFoundError(f"missing Google Flow clip: {paths['flow_clip']}")
        ensure_flow_clip_duration(paths["flow_clip"])


def ensure_flow_clip_duration(flow_clip: Path) -> None:
    duration = media_duration(flow_clip)
    if duration + 0.05 < COMMERCIAL_DURATION:
        raise ValueError(
            f"Google Flow clip is {duration:.2f}s; expected at least {COMMERCIAL_DURATION:.0f}s. "
            "Run with --run-flow to generate a full-length commercial clip."
        )


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print("+", shlex.join(cmd), file=sys.stderr)
    subprocess.run(cmd, cwd=cwd, check=True)


def run_capture_flow(args: argparse.Namespace, paths: dict[str, Path], out_path: Path) -> Path:
    captures = capture_paths(paths["capture_dir"])
    segments = []
    total_duration = 0.0
    for index in range(FLOW_MAX_SEGMENT_COUNT):
        segment = out_path.with_name(f"{out_path.stem}_segment_{index + 1:02d}{out_path.suffix}")
        if segment.exists():
            segments.append(segment)
            total_duration += media_duration(segment)
            if len(segments) >= FLOW_MIN_SEGMENT_COUNT and total_duration + 0.05 >= COMMERCIAL_DURATION:
                break
            continue
        cmd = [
            sys.executable,
            str(ROOT / "scripts" / "google_flow_cli.py"),
            "--prompt",
            flow_prompt(index),
            "--out",
            str(segment),
            "--app-url",
            args.flow_project_url,
            "--session",
            "flow",
            "--npm-cache",
            args.flow_npm_cache,
            "--timeout",
            "900",
            "--poll-interval",
            "15",
            "--duration",
            str(int(FLOW_SEGMENT_DURATION)),
            "--fresh",
        ]
        if args.flow_no_attach:
            cmd.append("--no-attach")
        else:
            cmd.extend(["--attach", "cdp"])
        for capture in captures:
            cmd.extend(["--image", str(capture)])
        run(cmd)
        segments.append(segment)
        total_duration += media_duration(segment)
        if len(segments) >= FLOW_MIN_SEGMENT_COUNT and total_duration + 0.05 >= COMMERCIAL_DURATION:
            break
    if total_duration + 0.05 < COMMERCIAL_DURATION:
        raise ValueError(f"Flow segments total {total_duration:.2f}s; expected at least {COMMERCIAL_DURATION:.0f}s")
    return concat_flow_segments(segments, out_path)


def flow_prompt(segment_index: int = 0) -> str:
    beats = [
        "open on the SpeakCoach EDU home dashboard, app brand, icy learning world, and a confident product-demo intro",
        "move through Read Aloud practice, live recording, pronunciation feedback, and mission map progress",
        "finish with weekly report rewards, privacy/on-device STT/TTS readiness, and a clear SpeakCoach EDU brand end frame",
    ]
    beat = beats[min(segment_index, len(beats) - 1)]
    return (
        "Google Flow product-demo marketing video for SpeakCoach EDU. Generate ONLY from the uploaded mobile app screenshots. "
        "Show a modern smartphone mockup with the exact SpeakCoach EDU / Polar Quest app interface visible and readable. "
        "Premium edtech motion graphics, icy blue learning world, warm confident accent lighting, smooth camera moves, "
        f"commercial segment {segment_index + 1}: {beat}. "
        "No live-action people, no historical scene, no costumes, no beverage cans, no boats, no harbors, no fake logos. "
        "Keep this as a polished app commercial with crisp UI close-ups."
    )


def capture_paths(capture_dir: Path) -> list[Path]:
    keys = ["home", "practice", "missions", "rewards", "settings"]
    paths = [capture_dir / f"speakcoach_{key}.png" for key in keys]
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise FileNotFoundError("missing captures: " + ", ".join(missing))
    return paths


def synthesize_voice(args: argparse.Namespace, transcript: Path, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = supertts_command(args)
    cmd.extend([
        "-f",
        str(transcript),
        "--lang",
        "ko",
        "--voice",
        args.voice,
        "--speed",
        args.speed,
        "--steps",
        args.steps,
        "--no-play",
        "--quiet",
        "-o",
        str(out_path),
    ])
    if args.supertts_assets:
        cmd.extend(["--assets", str(Path(args.supertts_assets).resolve())])
    run(cmd)
    return out_path


def supertts_command(args: argparse.Namespace) -> list[str]:
    if args.supertts_command:
        return shlex.split(args.supertts_command)
    if shutil.which("supertts"):
        return ["supertts"]
    return [
        "npm",
        "exec",
        "--cache",
        args.supertts_npm_cache,
        "--yes",
        "--package",
        "github:cskwork/supertonic-tts",
        "--",
        "supertts",
    ]


def load_captures(capture_dir: Path) -> dict[str, Image.Image]:
    return {scene.key: Image.open(capture_dir / f"speakcoach_{scene.key}.png").convert("RGB") for scene in SCENES}


@lru_cache(maxsize=1)
def _resolve_font() -> Path | None:
    env = os.environ.get("COMMERCIAL_FONT")
    if env and Path(env).exists():
        return Path(env)
    for cand in FONT_CANDIDATES:
        if cand.exists():
            return cand
    return None


@lru_cache(maxsize=16)
def font(size: int) -> ImageFont.ImageFont:
    path = _resolve_font()
    if path is None:
        # No Korean-capable TrueType font found; degrade rather than crash.
        return ImageFont.load_default()
    return ImageFont.truetype(str(path), size=size)


@lru_cache(maxsize=1)
def gradient() -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), "#061834")
    pix = img.load()
    for y in range(HEIGHT):
        t = y / HEIGHT
        for x in range(WIDTH):
            u = x / WIDTH
            pix[x, y] = (int(5 + 17 * t + 8 * u), int(24 + 42 * t + 18 * u), int(52 + 72 * t))
    return img.convert("RGBA")


def wrap_text(draw: ImageDraw.ImageDraw, text: str, face: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines: list[str] = []
    for raw in text.split("\n"):
        line = ""
        for word in raw.split(" "):
            candidate = word if not line else f"{line} {word}"
            if draw.textbbox((0, 0), candidate, font=face)[2] <= max_width:
                line = candidate
            else:
                if line:
                    lines.append(line)
                line = word
        if line:
            lines.append(line)
    return lines


def draw_multiline(draw: ImageDraw.ImageDraw, xy: tuple[int, int], lines: list[str], face: ImageFont.FreeTypeFont, fill: tuple[int, ...], gap: int) -> int:
    x, y = xy
    for line in lines:
        draw.text((x, y), line, font=face, fill=fill)
        y += draw.textbbox((0, 0), line, font=face)[3] + gap
    return y


def ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def fit_phone(img: Image.Image, scene_t: float) -> Image.Image:
    height = int(1120 * (1.14 + 0.05 * ease(scene_t)))
    width = int(height * img.width / img.height)
    phone = img.resize((width, height), Image.Resampling.LANCZOS)
    return frame_phone(phone, width, height)


def frame_phone(phone: Image.Image, width: int, height: int) -> Image.Image:
    mask = Image.new("L", phone.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, width, height), radius=52, fill=255)
    framed = Image.new("RGBA", (width + 42, height + 42), (0, 0, 0, 0))
    shadow = Image.new("RGBA", framed.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((21, 21, width + 21, height + 21), radius=64, fill=(0, 0, 0, 120))
    framed.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(22)))
    framed.alpha_composite(Image.composite(phone.convert("RGBA"), Image.new("RGBA", phone.size), mask), (21, 21))
    ImageDraw.Draw(framed).rounded_rectangle((21, 21, width + 21, height + 21), radius=54, outline=(255, 255, 255, 235), width=8)
    return framed


def draw_copy(base: Image.Image, scene: Scene, scene_t: float) -> None:
    alpha = int(255 * ease(min(scene_t * 1.8, 1)))
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    y = 104 if scene.align == "top" else 1270
    draw.rounded_rectangle((70, y, 1010, y + 420), radius=34, fill=(2, 15, 34, int(186 * alpha / 255)))
    draw.rounded_rectangle((70, y, 1010, y + 420), radius=34, outline=(*scene.accent, alpha), width=3)
    draw.text((106, y + 44), scene.eyebrow, font=font(42), fill=(*scene.accent, alpha))
    title_y = draw_multiline(draw, (106, y + 102), wrap_text(draw, scene.title, font(86), 820), font(86), (255, 255, 255, alpha), 8)
    draw_multiline(draw, (106, title_y + 22), wrap_text(draw, scene.body, font(40), 820), font(40), (218, 235, 248, alpha), 8)
    base.alpha_composite(overlay)


def draw_frame(captures: dict[str, Image.Image], frame: int) -> Image.Image:
    time = frame / FPS
    scene = next(scene for scene in SCENES if scene.start <= time < scene.end)
    scene_t = (time - scene.start) / (scene.end - scene.start)
    base = gradient().copy()
    phone = fit_phone(captures[scene.key], scene_t)
    base.alpha_composite(phone, ((WIDTH - phone.width) // 2 + int(math.sin(time * 1.1) * 20), 592 if scene.align == "top" else 112))
    draw_copy(base, scene, scene_t)
    ImageDraw.Draw(base).text((70, HEIGHT - 96), "eng-stt-module.vercel.app/mobile-app", font=font(30), fill=(160, 198, 220, 220))
    return base.convert("RGB")


def render_product_visual(capture_dir: Path, out: Path) -> Path:
    captures = load_captures(capture_dir)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{WIDTH}x{HEIGHT}", "-r", str(FPS), "-i", "-", "-t", "33", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    assert proc.stdin is not None
    for frame in range(int(33 * FPS)):
        proc.stdin.write(draw_frame(captures, frame).tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("product visual render failed")
    return out


def concat_flow_segments(segments: list[Path], out: Path) -> Path:
    if len(segments) < FLOW_MIN_SEGMENT_COUNT:
        raise ValueError(f"expected at least {FLOW_MIN_SEGMENT_COUNT} Flow segments, got {len(segments)}")
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-v", "error", "-y"]
    graph_parts = []
    concat_inputs = []
    for index, segment in enumerate(segments):
        cmd.extend(["-i", str(segment)])
        graph_parts.append(
            f"[{index}:v]scale=1280:720:force_original_aspect_ratio=decrease,"
            f"pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,format=yuv420p,"
            f"trim=duration={FLOW_SEGMENT_DURATION:.3f},setpts=PTS-STARTPTS[v{index}];"
            f"[{index}:a]aformat=sample_rates=48000:sample_fmts=fltp:channel_layouts=stereo,"
            f"atrim=duration={FLOW_SEGMENT_DURATION:.3f},asetpts=PTS-STARTPTS[a{index}]"
        )
        concat_inputs.append(f"[v{index}][a{index}]")
    graph = ";".join(graph_parts) + ";" + "".join(concat_inputs) + f"concat=n={len(segments)}:v=1:a=1[v][a]"
    cmd.extend([
        "-filter_complex",
        graph,
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-t",
        f"{COMMERCIAL_DURATION:.3f}",
        "-c:v",
        "libx264",
        "-crf",
        "18",
        "-preset",
        "medium",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(out),
    ])
    run(cmd)
    return out


def media_duration(path: Path) -> float:
    proc = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True, check=True)
    return float(proc.stdout.strip())


def generate_background_music(out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    source = (
        "aevalsrc="
        "0.10*sin(2*PI*220*t)+"
        "0.06*sin(2*PI*277.18*t)+"
        "0.05*sin(2*PI*329.63*t)+"
        "0.035*sin(2*PI*440*t)"
        f":s=48000:d={COMMERCIAL_DURATION:.3f}"
    )
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        source,
        "-af",
        "aformat=sample_rates=48000:sample_fmts=s16:channel_layouts=stereo,"
        "afade=t=in:st=0:d=1.2,afade=t=out:st=28.5:d=1.5",
        "-c:a",
        "pcm_s16le",
        str(out),
    ]
    run(cmd)
    return out


def prepare_music(args: argparse.Namespace, out_dir: Path) -> Path:
    if args.music_file:
        music = Path(args.music_file).resolve()
        if not music.exists():
            raise FileNotFoundError(f"missing music file: {music}")
        return music
    return generate_background_music(out_dir / "background_music.wav")


def compose_final(flow_clip: Path, voice: Path, music: Path, out: Path, music_volume: float = DEFAULT_MUSIC_VOLUME) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    graph = (
        f"[0:v]scale=1280:720:force_original_aspect_ratio=decrease,"
        f"pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p,"
        f"tpad=stop_mode=clone:stop_duration={COMMERCIAL_DURATION:.3f},"
        f"trim=duration={COMMERCIAL_DURATION:.3f},setpts=PTS-STARTPTS[v];"
        f"[2:a]volume={music_volume:.3f},aformat=sample_rates=48000:sample_fmts=fltp:channel_layouts=stereo,"
        f"apad=pad_dur={COMMERCIAL_DURATION:.3f},"
        f"atrim=duration={COMMERCIAL_DURATION:.3f},asetpts=PTS-STARTPTS[music];"
        f"[1:a]aformat=sample_rates=48000:sample_fmts=fltp:channel_layouts=stereo,"
        f"apad=pad_dur={COMMERCIAL_DURATION:.3f},"
        f"atrim=duration={COMMERCIAL_DURATION:.3f},asetpts=PTS-STARTPTS[narration];"
        "[narration]asplit=2[narration_sidechain][narration_mix];"
        "[music][narration_sidechain]sidechaincompress=threshold=0.025:ratio=18:attack=20:release=700[ducked];"
        f"[ducked][narration_mix]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
        f"atrim=duration={COMMERCIAL_DURATION:.3f},asetpts=PTS-STARTPTS[a]"
    )
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-i",
        str(flow_clip),
        "-i",
        str(voice),
        "-stream_loop",
        "-1",
        "-i",
        str(music),
        "-filter_complex",
        graph,
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-t",
        f"{COMMERCIAL_DURATION:.3f}",
        "-c:v",
        "libx264",
        "-crf",
        "18",
        "-preset",
        "medium",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(out),
    ]
    run(cmd)
    return out


def write_manifest(out_dir: Path, final: Path, flow_clip: Path, voice: Path, music: Path, voice_id: str) -> None:
    voice_names = {"F1": "Mina", "F2": "Sora", "F3": "Yuna", "M1": "Aiden", "M2": "Hiro", "M3": "Leo"}
    manifest = {
        "pipeline": "Google Flow visuals + independent music + Supertonic Korean TTS",
        "final": os.path.relpath(final, out_dir),
        "flow_clip": os.path.relpath(flow_clip, out_dir),
        "voice": os.path.relpath(voice, out_dir),
        "music": os.path.relpath(music, out_dir),
        "flow_source_audio": "discarded",
        "tts": {"engine": "supertonic-tts", "voice": voice_id, "voice_name": voice_names.get(voice_id, voice_id), "lang": "ko"},
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    args = parse_args()
    paths = resolve_inputs(args)
    ensure_inputs(paths, args.run_flow)
    out_dir = paths["out_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    flow_clip = paths["flow_clip"]
    if args.run_flow:
        flow_clip = run_capture_flow(args, paths, out_dir / "flow_hero.mp4")
        ensure_flow_clip_duration(flow_clip)
    voice = synthesize_voice(args, paths["transcript"], out_dir / "supertonic_ko_voice.wav")
    music = prepare_music(args, out_dir)
    final = compose_final(flow_clip, voice, music, out_dir / args.final_name, args.music_volume)
    write_manifest(out_dir, final, flow_clip, voice, music, args.voice)
    print(json.dumps({"ok": True, "final": str(final), "flow_clip": str(flow_clip), "voice": str(voice), "music": str(music)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
