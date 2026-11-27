import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import anime_vfi as MODULE


class CoreTests(unittest.TestCase):
    def test_parse_rate(self):
        self.assertAlmostEqual(MODULE.parse_rate("24000/1001"), 23.976023976, places=6)

    def test_auto_4k_uses_protected_motion_scale(self):
        self.assertEqual(MODULE.resolve_motion_scale(3840, 2160, 1.0, "auto"), 0.5)
        self.assertEqual(MODULE.resolve_motion_scale(1920, 1080, 1.0, "auto"), 1.0)
        self.assertEqual(MODULE.resolve_motion_scale(3840, 2160, 1.0, "full"), 1.0)
        self.assertEqual(MODULE.resolve_motion_scale(1920, 1080, 1.0, "auto", 10), 1.0)
        self.assertEqual(MODULE.resolve_motion_scale(1920, 1080, 0.75, "auto", 10), 0.75)
        self.assertEqual(MODULE.resolve_motion_scale(1920, 1080, 1.0, "auto", 8), 1.0)
        self.assertEqual(MODULE.resolve_motion_scale(1920, 1080, 1.0, "auto", 6), 1.0)
        self.assertEqual(MODULE.resolve_motion_scale(1920, 1080, 0.5, "auto", 6), 0.5)
        self.assertEqual(MODULE.resolve_motion_scale(1920, 1080, 1.0, "auto", 10, "extreme"), 0.25)
        self.assertEqual(MODULE.resolve_motion_scale(1920, 1080, 1.0, "auto", 8, "extreme"), 0.5)
        self.assertEqual(MODULE.resolve_motion_scale(1920, 1080, 1.0, "auto", 6, "extreme"), 0.5)
        self.assertEqual(MODULE.resolve_motion_scale(1920, 1080, 1.0, "auto", 4, "extreme"), 0.75)

    def test_render_template(self):
        result = MODULE.render_template(
            ["engine", "--input", "{input}", "--multi", "{multiplier}"],
            {"input": "a b.mkv", "multiplier": "2"},
        )
        self.assertEqual(result, ["engine", "--input", "a b.mkv", "--multi", "2"])

    def test_available_backends_detects_configured_pairs(self):
        config = {
            "gmfss_anime": {"command": ["python", "a.py"]},
            "gmfss_live_action": {"command": ["python", "b.py"]},
            "rife_anime": {"command": ["python", "c.py"]},
            "rife_live_action": {"command": ["python", "d.py"]},
        }
        self.assertEqual(MODULE.available_backends(config), ["gmfss", "rife"])
        self.assertEqual(MODULE.backend_label("gmfss"), "GMFSS")
        self.assertEqual(MODULE.backend_label("rife"), "RIFE")

    def test_render_template_rejects_unknown_placeholder(self):
        with self.assertRaises(MODULE.PipelineError):
            MODULE.render_template(["{unknown}"], {})

    def test_missing_bundled_python_falls_back_to_current_python(self):
        command = MODULE.resolve_engine_python(
            [str(ROOT / "work" / "missing-runtime" / "python.exe"), "inference_video.py"]
        )
        self.assertEqual(Path(command[0]).resolve(), Path(sys.executable).resolve())

    def test_parser_accepts_multiplier_ten(self):
        parser = MODULE.build_parser()
        args = parser.parse_args(
            [
                "run",
                str(ROOT / "anime_vfi.py"),
                "out.mkv",
                "--multiplier",
                "10",
                "--mode",
                "live-action",
                "--backend",
                "gmfss",
                "--slow-motion-factor",
                "8",
                "--uhd-mode",
                "memory",
                "--motion-profile",
                "extreme",
                "--throttle-ms",
                "15",
            ]
        )
        self.assertEqual(args.multiplier, 10)
        self.assertIsNone(args.fps)
        self.assertEqual(args.mode, "live-action")
        self.assertEqual(args.backend, "gmfss")
        self.assertEqual(args.scale, 1.0)
        self.assertEqual(args.slow_motion_factor, 8)
        self.assertEqual(args.uhd_mode, "memory")
        self.assertEqual(args.motion_profile, "extreme")
        self.assertEqual(args.throttle_ms, 15)

    def test_parser_accepts_batch_mode(self):
        parser = MODULE.build_parser()
        args = parser.parse_args(
            [
                "batch",
                str(ROOT / "config.json"),
                "--multiplier",
                "8",
                "--backend",
                "GMFSS",
                "--slow-motion-factor",
                "8",
                "--scale",
                "0.75",
            ]
        )
        self.assertEqual(args.command, "batch")
        self.assertEqual(args.multiplier, 8)
        self.assertEqual(args.backend, "GMFSS")
        self.assertEqual(args.slow_motion_factor, 8)
        self.assertEqual(args.scale, 0.75)

    def test_pipeline_forwards_throttle_to_gmfss(self):
        source = (ROOT / "anime_vfi.py").read_text(encoding="utf-8")
        self.assertGreaterEqual(source.count('command.extend(["--throttle-ms", str(throttle_ms)])'), 2)

    def test_batch_mode_uses_one_engine_process(self):
        source = (ROOT / "anime_vfi.py").read_text(encoding="utf-8")
        engine = (ROOT / "work" / "GMFSS_Fortuna" / "inference_video.py").read_text(encoding="utf-8")
        gui = (ROOT / "anime_vfi_gui.py").read_text(encoding="utf-8")
        self.assertIn("def interpolate_gmfss_batch", source)
        self.assertIn("--batch-manifest", source)
        self.assertIn("VFI_BATCH_ITEM", engine)
        self.assertIn('"batch", str(manifest)', gui)

    def test_atempo_filter_supports_ten_times_slow_motion(self):
        self.assertEqual(MODULE.atempo_filter(0.1), "atempo=0.5,atempo=0.5,atempo=0.5,atempo=0.8")

    def test_clip_ends_on_last_real_frame(self):
        engine = (ROOT / "work" / "GMFSS_Fortuna" / "inference_video.py").read_text(encoding="utf-8")
        override = (ROOT / "patches" / "GMFSS_Fortuna" / "inference_video.py").read_text(encoding="utf-8")
        for source in (engine, override):
            self.assertNotIn("for _ in range(args.multi - 1):", source)

    def test_mux_keeps_video_length_when_audio_is_shorter(self):
        pipeline = (ROOT / "anime_vfi.py").read_text(encoding="utf-8")
        self.assertNotIn('"-shortest"', pipeline)
        self.assertIn('"-t", f"{video_duration:.6f}"', pipeline)

    def test_ntsc_rates_are_written_as_exact_fractions(self):
        self.assertEqual(MODULE.exact_rate(24000 / 1001 * 8), "192000/1001")
        self.assertEqual(MODULE.exact_rate(191.808192), "192000/1001")
        self.assertEqual(MODULE.exact_rate(59.94005994), "60000/1001")
        self.assertEqual(MODULE.exact_rate(60.0), "60/1")
        self.assertEqual(MODULE.exact_rate(12.5), "25/2")
        engine = (ROOT / "work" / "GMFSS_Fortuna" / "inference_video.py").read_text(encoding="utf-8")
        self.assertIn('"-r", exact_rate(fps)', engine)

    def test_any_target_fps_is_accepted(self):
        self.assertEqual(MODULE.engine_multiplier(24000 / 1001, 48000 / 1001), 2)
        self.assertEqual(MODULE.engine_multiplier(23.976, 191.808), 8)
        self.assertEqual(MODULE.engine_multiplier(24000 / 1001, 60.0), 3)
        self.assertEqual(MODULE.engine_multiplier(24.0, 30.0), 2)
        self.assertEqual(MODULE.engine_multiplier(30.0, 144.0), 5)

    def test_scene_cut_rule_separates_cuts_from_fast_motion(self):
        import ast
        engine = (ROOT / "work" / "GMFSS_Fortuna" / "inference_video.py").read_text(encoding="utf-8")
        tree = ast.parse(engine)
        wanted = [node for node in tree.body
                  if isinstance(node, ast.FunctionDef) and node.name == "is_scene_cut"
                  or isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "SCENE_COLOR_CHANGE"]
        namespace = {}
        exec(compile(ast.Module(body=wanted, type_ignores=[]), "engine", "exec"), namespace)
        is_scene_cut = namespace["is_scene_cut"]
        # (motion-compensated difference, colour change) measured on an anime episode
        cuts = [(0.149, 0.312), (0.1, 0.444), (0.21, 0.398), (0.167, 0.174), (0.122, 0.481)]
        fast_motion = [(0.106, 0.308), (0.1, 0.167), (0.084, 0.177), (0.079, 0.095), (0.076, 0.348)]
        for motion, colour in cuts:
            self.assertTrue(is_scene_cut(motion, colour, 0.12), (motion, colour))
        for motion, colour in fast_motion:
            self.assertFalse(is_scene_cut(motion, colour, 0.12), (motion, colour))

    def test_odd_resolution_rounds_down_to_even(self):
        def info(width, height):
            return MODULE.VideoInfo(width, height, 30.0, 1.0, 30, "h264", "yuv444p", False, False)

        self.assertEqual(MODULE.video_size(info(853, 481)), (852, 480))
        self.assertEqual(MODULE.video_size(info(1920, 1080)), (1920, 1080))
        MODULE.check_engine_resolution(info(852, 480), info(853, 481))
        with self.assertRaises(MODULE.PipelineError):
            MODULE.check_engine_resolution(info(853, 481), info(853, 481))



if __name__ == "__main__":
    unittest.main()
