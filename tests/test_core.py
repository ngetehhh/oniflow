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

    def test_slow_motion_preserves_legacy_final_frame_hold(self):
        pipeline = (ROOT / "anime_vfi.py").read_text(encoding="utf-8")
        engine = (ROOT / "work" / "GMFSS_Fortuna" / "inference_video.py").read_text(encoding="utf-8")
        self.assertNotIn("trim=end_frame", pipeline)
        self.assertNotIn("--no-final-hold", engine)
        self.assertIn("for _ in range(args.multi - 1):", engine)



if __name__ == "__main__":
    unittest.main()
