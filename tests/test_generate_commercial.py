from __future__ import annotations

import argparse
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import generate_commercial as gen  # noqa: E402


class GenerateCommercialTests(unittest.TestCase):
    def test_run_capture_flow_generates_until_duration_is_covered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            capture_dir = Path(tmp) / "captures"
            capture_dir.mkdir()
            for key in ["home", "practice", "missions", "rewards", "settings"]:
                (capture_dir / f"speakcoach_{key}.png").write_bytes(b"png")

            commands: list[list[str]] = []
            args = argparse.Namespace(flow_project_url="https://flow.example/project", flow_no_attach=False, flow_npm_cache="")
            out = Path(tmp) / "flow.mp4"

            with (
                patch.object(gen, "run", side_effect=commands.append),
                patch.object(gen, "media_duration", side_effect=[8.0, 8.0, 10.0, 10.0]),
            ):
                self.assertEqual(gen.run_capture_flow(args, {"capture_dir": capture_dir}, out), out)

            self.assertEqual(len(commands), 5)
            for index, cmd in enumerate(commands[:4], start=1):
                self.assertEqual(cmd[cmd.index("--duration") + 1], "10")
                self.assertEqual(cmd[cmd.index("--npm-cache") + 1], "")
                self.assertEqual(cmd[cmd.index("--app-url") + 1], args.flow_project_url)
                self.assertIn(f"segment {index}", cmd[cmd.index("--prompt") + 1])
                self.assertIn(f"flow_segment_{index:02d}.mp4", cmd[cmd.index("--out") + 1])
                self.assertEqual(cmd.count("--image"), 5)

            concat_cmd = commands[-1]
            graph = concat_cmd[concat_cmd.index("-filter_complex") + 1]
            self.assertEqual(concat_cmd.count("-i"), 4)
            self.assertIn("concat=n=4:v=1:a=1", graph)
            self.assertEqual(concat_cmd[concat_cmd.index("-t") + 1], "30.000")

    def test_compose_final_uses_flow_visual_and_independent_ducked_music(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            flow = Path(tmp) / "flow.mp4"
            voice = Path(tmp) / "voice.wav"
            music = Path(tmp) / "music.wav"
            out = Path(tmp) / "final.mp4"
            commands: list[list[str]] = []

            with patch.object(gen, "run", side_effect=commands.append):
                self.assertEqual(gen.compose_final(flow, voice, music, out), out)

            self.assertEqual(len(commands), 1)
            cmd = commands[0]
            graph = cmd[cmd.index("-filter_complex") + 1]

            self.assertEqual(cmd.count("-i"), 3)
            self.assertIn(str(flow), cmd)
            self.assertIn(str(voice), cmd)
            self.assertIn(str(music), cmd)
            self.assertIn("-stream_loop", cmd)
            self.assertNotIn("product_visual", " ".join(cmd))
            self.assertNotIn("concat=", graph)
            self.assertNotIn("[1:v]", graph)
            self.assertNotIn("[0:a]", graph)
            self.assertIn("[0:v]scale=1280:720", graph)
            self.assertIn("tpad=stop_mode=clone:stop_duration=30.000", graph)
            self.assertIn("trim=duration=30.000", graph)
            self.assertIn("[2:a]volume=0.220,aformat", graph)
            self.assertIn("[1:a]aformat", graph)
            self.assertIn("[narration]asplit=2[narration_sidechain][narration_mix]", graph)
            self.assertIn("sidechaincompress=threshold=0.025:ratio=18", graph)
            self.assertIn("[ducked][narration_mix]amix", graph)
            self.assertNotIn("[ducked][voice]amix", graph)
            self.assertIn("amix=inputs=2:duration=first:dropout_transition=0:normalize=0", graph)
            self.assertEqual(cmd[cmd.index("-t") + 1], "30.000")

    def test_prepare_music_uses_external_music_file_when_provided(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            music = Path(tmp) / "music.wav"
            music.write_bytes(b"music")
            args = argparse.Namespace(music_file=str(music))

            with patch.object(gen, "generate_background_music") as generate:
                self.assertEqual(gen.prepare_music(args, Path(tmp)), music.resolve())

            generate.assert_not_called()

    def test_prepare_music_generates_background_music_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            expected = out_dir / "background_music.wav"
            args = argparse.Namespace(music_file="")

            with patch.object(gen, "generate_background_music", return_value=expected) as generate:
                self.assertEqual(gen.prepare_music(args, out_dir), expected)

            generate.assert_called_once_with(expected)

    def test_ensure_inputs_does_not_require_captures_without_run_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            transcript = root / "transcript.txt"
            flow = root / "flow.mp4"
            transcript.write_text("narration", encoding="utf-8")
            flow.write_bytes(b"mp4")
            paths = {
                "capture_dir": root / "missing-captures",
                "transcript": transcript,
                "flow_clip": flow,
            }

            with patch.object(gen, "media_duration", return_value=gen.COMMERCIAL_DURATION):
                gen.ensure_inputs(paths, run_flow=False)

            with self.assertRaises(FileNotFoundError):
                gen.ensure_inputs(paths, run_flow=True)

    def test_existing_flow_clip_must_cover_full_commercial_duration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            transcript = root / "transcript.txt"
            flow = root / "flow.mp4"
            transcript.write_text("narration", encoding="utf-8")
            flow.write_bytes(b"mp4")
            paths = {
                "capture_dir": root / "missing-captures",
                "transcript": transcript,
                "flow_clip": flow,
            }

            with patch.object(gen, "media_duration", return_value=8.0):
                with self.assertRaisesRegex(ValueError, "expected at least 30s"):
                    gen.ensure_inputs(paths, run_flow=False)

    def test_main_skips_product_visual_render_for_final_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            flow = out_dir / "flow.mp4"
            voice = out_dir / "voice.wav"
            music = out_dir / "music.wav"
            final = out_dir / "final.mp4"
            args = argparse.Namespace(run_flow=False, final_name="final.mp4", voice="F1", music_file="", music_volume=0.22)
            paths = {
                "out_dir": out_dir,
                "capture_dir": out_dir / "captures",
                "transcript": out_dir / "transcript.txt",
                "flow_clip": flow,
            }

            with (
                patch.object(gen, "parse_args", return_value=args),
                patch.object(gen, "resolve_inputs", return_value=paths),
                patch.object(gen, "ensure_inputs"),
                patch.object(gen, "ensure_flow_clip_duration"),
                patch.object(gen, "synthesize_voice", return_value=voice),
                patch.object(gen, "prepare_music", return_value=music),
                patch.object(gen, "compose_final", return_value=final) as compose,
                patch.object(gen, "render_product_visual") as render_product_visual,
                patch.object(gen, "write_manifest"),
            ):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(gen.main(), 0)

            render_product_visual.assert_not_called()
            compose.assert_called_once_with(flow, voice, music, final, 0.22)

    def test_main_validates_fresh_flow_clip_duration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            flow = out_dir / "flow_hero.mp4"
            voice = out_dir / "voice.wav"
            music = out_dir / "music.wav"
            final = out_dir / "final.mp4"
            args = argparse.Namespace(run_flow=True, final_name="final.mp4", voice="F1", music_file="", music_volume=0.22)
            paths = {
                "out_dir": out_dir,
                "capture_dir": out_dir / "captures",
                "transcript": out_dir / "transcript.txt",
                "flow_clip": out_dir / "stale-flow.mp4",
            }

            with (
                patch.object(gen, "parse_args", return_value=args),
                patch.object(gen, "resolve_inputs", return_value=paths),
                patch.object(gen, "ensure_inputs"),
                patch.object(gen, "run_capture_flow", return_value=flow),
                patch.object(gen, "ensure_flow_clip_duration") as ensure_duration,
                patch.object(gen, "synthesize_voice", return_value=voice),
                patch.object(gen, "prepare_music", return_value=music),
                patch.object(gen, "compose_final", return_value=final),
                patch.object(gen, "write_manifest"),
            ):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(gen.main(), 0)

            ensure_duration.assert_called_once_with(flow)


if __name__ == "__main__":
    unittest.main()
