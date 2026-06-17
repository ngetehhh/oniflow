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

    def test_render_template(self):
        result = MODULE.render_template(
            ["engine", "--input", "{input}", "--multi", "{multiplier}"],
            {"input": "a b.mkv", "multiplier": "2"},
        )
        self.assertEqual(result, ["engine", "--input", "a b.mkv", "--multi", "2"])

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
                "--slow-motion-factor",
                "8",
                "--uhd-mode",
                "memory",
                "--throttle-ms",
                "15",
            ]
        )
        self.assertEqual(args.multiplier, 10)
        self.assertIsNone(args.fps)
        self.assertEqual(args.mode, "live-action")
        self.assertEqual(args.scale, 1.0)
        self.assertEqual(args.slow_motion_factor, 8)
        self.assertEqual(args.uhd_mode, "memory")
        self.assertEqual(args.throttle_ms, 15)

    def test_pipeline_forwards_throttle_to_gmfss(self):
        source = (ROOT / "anime_vfi.py").read_text(encoding="utf-8")
        self.assertGreaterEqual(source.count('command.extend(["--throttle-ms", str(throttle_ms)])'), 2)

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
