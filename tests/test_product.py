import sys
import tempfile
import unittest
import os
import json
import hashlib
import inspect
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import anime_vfi
import anime_vfi_gui
import activation_server
import release_audit
import offline_license
import runtime_security


class ProductTests(unittest.TestCase):
    def test_product_documents_exist(self):
        for name in (
            "VERSION",
            "HELP.md",
            "EULA.md",
            "PRIVACY.md",
            "THIRD_PARTY_NOTICES.md",
            "UPDATE_POLICY.md",
            "DISTRIBUTION_SECURITY.md",
            "RELEASE_CHECKLIST.md",
        ):
            self.assertTrue((ROOT / name).is_file(), name)

    def test_release_build_copies_runtime_documents_to_distribution_root(self):
        script = (ROOT / "build_release.ps1").read_text(encoding="utf-8")
        for name in (
            "HELP.md",
            "EULA.md",
            "PRIVACY.md",
            "THIRD_PARTY_NOTICES.md",
            "UPDATE_POLICY.md",
            "DISTRIBUTION_SECURITY.md",
            "RELEASE_CHECKLIST.md",
        ):
            self.assertIn(f'"{name}"', script)
        self.assertIn('"activation_config.json"', script)
        self.assertIn('"update_config.json"', script)

    def test_default_product_safety_settings(self):
        settings = anime_vfi_gui.DEFAULT_SETTINGS
        self.assertTrue(settings["mixed_precision"])
        self.assertEqual(settings["uhd_mode"], "Auto (Recommended)")
        self.assertEqual(settings["gpu_usage_limit"], "100%")
        self.assertEqual(settings["default_profile"], "Anime")
        self.assertEqual(settings["default_backend"], "GMFSS")
        self.assertEqual(settings["default_multiplier"], "2x")
        self.assertEqual(settings["default_interpolation_quality"], "Normal")
        self.assertEqual(settings["default_output_format"], "MP4")
        self.assertEqual(settings["default_slow_motion"], "Off")
        self.assertTrue(settings["auto_check_updates"])
        self.assertEqual(settings["update_check_interval_hours"], 24)

    def test_mov_with_alpha_output_is_available(self):
        gui = (ROOT / "anime_vfi_gui.py").read_text(encoding="utf-8")
        self.assertIn('"MOV"', gui)
        self.assertIn('"MOV with Alpha"', gui)
        self.assertEqual(anime_vfi_gui.output_extension("MOV"), "mov")
        self.assertEqual(anime_vfi_gui.output_extension("MOV with Alpha"), "mov")
        self.assertIn('"codec": "prores_ks"', gui)
        self.assertIn('"profile": "3"', gui)
        self.assertIn('"pixel_format": "yuv422p10le"', gui)
        self.assertIn('"profile": "4444"', gui)
        self.assertIn('"pixel_format": "yuva444p10le"', gui)

    def test_update_manifest_helpers(self):
        self.assertTrue(anime_vfi_gui.update_is_newer("0.9.3-beta", "0.9.2-beta"))
        self.assertFalse(anime_vfi_gui.update_is_newer("0.9.2-beta", "0.9.2-beta"))
        self.assertEqual(anime_vfi_gui.version_key("v1.2.3-beta"), (1, 2, 3))
        source = inspect.getsource(anime_vfi_gui.AnimeVfiPro.check_for_updates)
        self.assertIn("_check_for_updates_worker", source)
        gui = (ROOT / "anime_vfi_gui.py").read_text(encoding="utf-8")
        self.assertIn("_maybe_auto_check_for_updates", gui)
        self.assertIn('"Check for updates automatically"', gui)
        self.assertIn("automatic: bool = False", gui)
        self.assertIn("UPDATE_REQUEST_HEADERS", gui)
        self.assertIn("friendly_update_error", gui)
        self.assertIn("progress_callback", gui)
        self.assertIn('"update_progress"', gui)

    def test_job_defaults_are_available_and_applied(self):
        source = (ROOT / "anime_vfi_gui.py").read_text(encoding="utf-8")
        self.assertIn('"Job Defaults"', source)
        self.assertIn('self._apply_job_defaults()', source)
        self.assertIn('self.mode = ctk.StringVar(value=str(self.settings["default_profile"]))', source)
        self.assertIn('self.model_name = ctk.StringVar(value=default_backend_label)', source)
        self.assertIn('"default_backend"', source)

    def test_resolution_policy_preserves_output_size(self):
        self.assertEqual(anime_vfi.resolve_motion_scale(3840, 2160, 1.0, "auto"), 0.5)

    def test_friendly_error_mapping(self):
        message = anime_vfi_gui.AnimeVfiPro._friendly_error("CUDA out of memory")
        self.assertIn("VRAM", message)

    def test_engine_command_rejects_arbitrary_executable(self):
        with self.assertRaises(anime_vfi.PipelineError):
            anime_vfi.validate_engine_command(["powershell.exe", "malware.ps1"], ROOT)

    def test_release_audit_rejects_private_paths_and_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            username = os.environ.get("USERNAME", "user")
            (root / "settings.cfg").write_text(f"home=C:\\Users\\{username}\\Videos", encoding="utf-8")
            (root / "session.log").write_text("private log", encoding="utf-8")
            findings = release_audit.audit(root)
        self.assertTrue(any("private Windows user path" in finding for finding in findings))
        self.assertTrue(any("forbidden release file" in finding for finding in findings))

    def test_inference_backend_uses_safe_model_loading_and_no_shell_commands(self):
        backend = (ROOT / "work" / "GMFSS_Fortuna")
        inference = (backend / "inference_video.py").read_text(encoding="utf-8")
        override = (ROOT / "patches" / "GMFSS_Fortuna" / "inference_video.py").read_text(encoding="utf-8")
        setup = (ROOT / "setup_gmfss.ps1").read_text(encoding="utf-8")
        union = (backend / "model" / "GMFSS_infer_u.py").read_text(encoding="utf-8")
        base = (backend / "model" / "GMFSS_infer_b.py").read_text(encoding="utf-8")
        self.assertNotIn("os.system(", inference)
        self.assertIn("skvideo.setFFmpegPath(str(TOOLS_DIR))", inference)
        self.assertIn('os.environ["PATH"] = str(TOOLS_DIR)', inference)
        self.assertIn('FFMPEG_EXE if FFMPEG_EXE.is_file() else "ffmpeg"', inference)
        self.assertIn("skvideo.setFFmpegPath(str(TOOLS_DIR))", override)
        self.assertIn("--object-protection", inference)
        self.assertIn("--object-protection", override)
        self.assertIn("default=False, help='experimental: preserve fast moving objects", inference)
        self.assertIn("default=False, help='experimental: preserve fast moving objects", override)
        self.assertIn("build_object_protection_mask", inference)
        self.assertIn("build_object_protection_mask", override)
        self.assertIn("protect_interpolated_object", inference)
        self.assertIn("protect_interpolated_object", override)
        self.assertIn("patches\\GMFSS_Fortuna\\inference_video.py", setup)
        self.assertIn("weights_only=True", union)
        self.assertIn("weights_only=True", base)

    def test_release_build_excludes_git_metadata(self):
        script = (ROOT / "build_release.ps1").read_text(encoding="utf-8")
        self.assertIn("/XD .git __pycache__", script)
        self.assertIn("work\\python-runtime", script)
        self.assertIn("oniflow_launcher.py", script)
        self.assertIn('release\\Oniflow', script)

    def test_launcher_uses_portable_pythonw(self):
        launcher = (ROOT / "oniflow_launcher.py").read_text(encoding="utf-8")
        self.assertIn('"pythonw.exe"', launcher)
        self.assertIn('"anime_vfi_gui.pyc"', launcher)

    def test_brand_assets_and_release_icon_exist(self):
        self.assertTrue((ROOT / "assets" / "oniflow-logo.png").is_file())
        self.assertTrue((ROOT / "assets" / "oniflow.ico").is_file())
        build_script = (ROOT / "build_release.ps1").read_text(encoding="utf-8")
        self.assertIn("--icon $IconPath $LauncherSource", build_script)

    def test_settings_are_saved_to_user_data_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            app_data = Path(directory) / "Oniflow"
            settings_path = app_data / "user_settings.json"
            with patch.object(anime_vfi_gui, "APP_DATA_ROOT", app_data), patch.object(
                anime_vfi_gui, "SETTINGS_PATH", settings_path
            ):
                anime_vfi_gui.AnimeVfiPro._save_settings_file({"mixed_precision": False})
                saved = json.loads(settings_path.read_text(encoding="utf-8"))
        self.assertFalse(saved["mixed_precision"])

    def test_runtime_config_is_written_to_user_data(self):
        with tempfile.TemporaryDirectory() as directory:
            app_data = Path(directory) / "Oniflow"
            app = object.__new__(anime_vfi_gui.AnimeVfiPro)
            app.settings = dict(anime_vfi_gui.DEFAULT_SETTINGS)
            app.device_caps = {"encoders": ["AV1", "HEVC", "H.264"]}
            with patch.object(anime_vfi_gui, "APP_DATA_ROOT", app_data):
                runtime_config = app._write_runtime_config()
        self.assertEqual(runtime_config, app_data / "runtime-config.json")
        self.assertNotEqual(runtime_config.parent, ROOT / "work")

    def test_start_reports_job_preparation_errors(self):
        source = inspect.getsource(anime_vfi_gui.AnimeVfiPro.start)
        self.assertIn("Job preparation failed", source)
        self.assertIn('"Cannot Start Processing"', source)

    def test_all_windows_use_brand_icon_and_main_window_accepts_global_drop(self):
        source = (ROOT / "anime_vfi_gui.py").read_text(encoding="utf-8")
        self.assertGreaterEqual(source.count("self._apply_window_icon(window)"), 3)
        self.assertIn("def _register_main_drop_targets", source)
        self.assertIn('widget.dnd_bind("<<Drop>>", self.handle_drop)', source)

    def test_device_check_runs_outside_ui_thread(self):
        source = (ROOT / "anime_vfi_gui.py").read_text(encoding="utf-8")
        self.assertIn("threading.Thread(target=self._startup_device_check, daemon=True).start()", source)
        self.assertIn("threading.Thread(target=self._update_gpu, daemon=True).start()", source)
        self.assertIn('self.events.put(("device"', source)
        self.assertIn('self.events.put(("gpu"', source)

    def test_access_codes_and_daily_quota_are_disabled_but_retained(self):
        source = (ROOT / "anime_vfi_gui.py").read_text(encoding="utf-8")
        self.assertFalse(anime_vfi_gui.ACCESS_FEATURE_ENABLED)
        self.assertEqual(anime_vfi_gui.FREE_DAILY_CLIP_LIMIT, 15)
        self.assertIn("Subscribe (Coming Soon)", source)
        self.assertIn("Redeem Code", source)
        self.assertIn("if ACCESS_FEATURE_ENABLED:", source)
        self.assertIn("if not ACCESS_FEATURE_ENABLED:", source)

    def test_offline_license_is_required_and_private_key_is_not_released(self):
        source = (ROOT / "anime_vfi_gui.py").read_text(encoding="utf-8")
        build_script = (ROOT / "build_release.ps1").read_text(encoding="utf-8")
        self.assertTrue(anime_vfi_gui.OFFLINE_LICENSE_REQUIRED)
        self.assertIn("offline_license.py", build_script)
        self.assertIn("offline-license-public.json", build_script)
        self.assertNotIn("offline-license-private.json", build_script)
        self.assertNotIn("offline_license_admin.py", build_script)

    def test_offline_license_device_id_is_stable(self):
        self.assertEqual(offline_license.device_id(), offline_license.device_id())
        self.assertRegex(offline_license.device_id(), r"^[0-9A-F]{8}(?:-[0-9A-F]{8}){3}$")

    def test_owner_license_tools_stay_private(self):
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for name in (
            "Buat Lisensi Oniflow.vbs",
            "buat_kunci_offline_license.ps1",
            "buat_offline_license.ps1",
            "integrity_admin.py",
            "offline_license_admin.py",
            "offline_license_gui.py",
        ):
            self.assertIn(name, gitignore)
        build_script = (ROOT / "build_release.ps1").read_text(encoding="utf-8")
        self.assertNotIn("offline_license_admin.py", build_script)
        self.assertNotIn("offline_license_gui.py", build_script)
        self.assertNotIn("Buat Lisensi Oniflow.vbs", build_script)

    def test_offline_license_verification_and_device_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            public_key = root / "public.json"
            license_path = root / "license.json"
            public_key.write_text("{}", encoding="utf-8")
            license_path.write_text(
                json.dumps(
                    {
                        "payload": {
                            "product": "Oniflow",
                            "license_id": "TEST",
                            "licensed_to": "Test User",
                            "device_id": "AAAAAAAA-BBBBBBBB-CCCCCCCC-DDDDDDDD",
                            "issued_at": "2026-01-01T00:00:00+00:00",
                            "expires_at": "",
                        },
                        "signature": "AA==",
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(offline_license, "public_key_is_trusted", return_value=True), patch.object(
                offline_license, "_rsa_verify", return_value=True
            ):
                valid, _, payload = offline_license.verify_license(
                    license_path,
                    public_key,
                    "AAAAAAAA-BBBBBBBB-CCCCCCCC-DDDDDDDD",
                )
                wrong_device, _, _ = offline_license.verify_license(
                    license_path,
                    public_key,
                    "11111111-22222222-33333333-44444444",
                )
        self.assertTrue(valid)
        self.assertEqual(payload["licensed_to"], "Test User")
        self.assertFalse(wrong_device)

    def test_offline_public_key_is_pinned(self):
        self.assertTrue(offline_license.public_key_is_trusted(ROOT / "assets" / "offline-license-public.json"))
        with tempfile.TemporaryDirectory() as directory:
            modified = Path(directory) / "public.json"
            modified.write_text("{}", encoding="utf-8")
            self.assertFalse(offline_license.public_key_is_trusted(modified))

    def test_signed_integrity_manifest_detects_modified_files(self):
        with tempfile.TemporaryDirectory() as directory:
            release = Path(directory)
            protected_files = (
                "Oniflow.exe",
                "anime_vfi.pyc",
                "assets/offline-license-public.json",
            )
            file_hashes = {}
            for relative in protected_files:
                path = release / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                if relative == "assets/offline-license-public.json":
                    path.write_bytes((ROOT / "assets" / "offline-license-public.json").read_bytes())
                else:
                    path.write_text(f"protected:{relative}", encoding="utf-8")
                file_hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest().upper()
            manifest = {
                "payload": {
                    "product": "Oniflow",
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "files": file_hashes,
                },
                "signature": "AA==",
            }
            (release / "integrity-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with patch.object(runtime_security, "public_key_is_trusted", return_value=True), patch.object(
                runtime_security, "_rsa_verify", return_value=True
            ):
                valid, _ = runtime_security.verify_integrity(release, require_manifest=True)
                (release / "anime_vfi.pyc").write_text("modified", encoding="utf-8")
                modified_valid, modified_message = runtime_security.verify_integrity(release, require_manifest=True)
        self.assertTrue(valid)
        self.assertFalse(modified_valid)
        self.assertIn("modified", modified_message)

    def test_launcher_and_pipeline_enforce_runtime_security(self):
        launcher = (ROOT / "oniflow_launcher.py").read_text(encoding="utf-8")
        pipeline = (ROOT / "anime_vfi.py").read_text(encoding="utf-8")
        gui = (ROOT / "anime_vfi_gui.py").read_text(encoding="utf-8")
        self.assertIn("verify_integrity", launcher)
        self.assertNotIn("require_runtime_access", launcher)
        self.assertIn("verify_runtime_access", pipeline)
        self.assertIn("verify_runtime_access", gui)
        self.assertIn("integrity_admin.py", (ROOT / "build_release.ps1").read_text(encoding="utf-8"))
        self.assertIn("Owner-only integrity_admin.py is missing", (ROOT / "build_release.ps1").read_text(encoding="utf-8"))
        self.assertIn("py_compile.compile", (ROOT / "build_release.ps1").read_text(encoding="utf-8"))

    def test_launcher_allows_offline_license_import_screen(self):
        launcher = (ROOT / "oniflow_launcher.py").read_text(encoding="utf-8")
        gui = (ROOT / "anime_vfi_gui.py").read_text(encoding="utf-8")
        self.assertNotIn("verify_runtime_access", launcher)
        self.assertIn('"__compiled__" in globals()', launcher)
        self.assertIn("Path(sys.argv[0]).resolve().parent", launcher)
        self.assertIn("MessageBoxW", launcher)
        self.assertIn("self.root.after(300, self._ensure_offline_license)", gui)
        self.assertIn("self._open_offline_license_window(message)", gui)

    def test_redeem_code_activates_pro_and_cannot_be_reused(self):
        state = anime_vfi_gui.normalize_access_state()
        updated, expiry = anime_vfi_gui.redeem_access_code(state, "oniflow-beta-30d")
        self.assertTrue(anime_vfi_gui.is_pro_access(updated))
        self.assertTrue(expiry)
        with self.assertRaisesRegex(ValueError, "already been redeemed"):
            anime_vfi_gui.redeem_access_code(updated, "ONIFLOW-BETA-30D")
        with self.assertRaisesRegex(ValueError, "invalid"):
            anime_vfi_gui.redeem_access_code(state, "NOT-A-REAL-CODE")

    def test_daily_access_state_resets_for_a_new_day(self):
        state = anime_vfi_gui.normalize_access_state({"usage_date": "2000-01-01", "clips_used": 15})
        self.assertEqual(state["clips_used"], 0)

    def test_activation_server_schema_supports_codes_devices_and_activations(self):
        source = (ROOT / "activation_server.py").read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS codes", source)
        self.assertIn("CREATE TABLE IF NOT EXISTS devices", source)
        self.assertIn("CREATE TABLE IF NOT EXISTS activations", source)
        self.assertEqual(activation_server.FREE_DAILY_CLIP_LIMIT, 15)

    def test_release_does_not_copy_private_activation_server_database(self):
        script = (ROOT / "build_release.ps1").read_text(encoding="utf-8")
        self.assertNotIn('Copy-Item -Force (Join-Path $Root "activation.db")', script)
        self.assertNotIn('Copy-Item -Force (Join-Path $Root "activation_server.py")', script)

    def test_queue_scrollbar_and_progress_use_oniflow_colors(self):
        source = (ROOT / "anime_vfi_gui.py").read_text(encoding="utf-8")
        self.assertIn('scrollbar_button_color="#1d5f8c"', source)
        self.assertIn('scrollbar_button_hover_color="#38bdf8"', source)
        self.assertIn('progress_color="#38bdf8"', source)
        self.assertIn("self.compact_layout = window_height < 760", source)
        self.assertIn("minsize=220 if self.compact_layout else 270", source)
        self.assertIn("minsize=95 if self.compact_layout else 105", source)

    def test_device_check_uses_bundled_ffmpeg(self):
        source = inspect.getsource(anime_vfi_gui.AnimeVfiPro._startup_device_check)
        self.assertIn('ROOT / "tools" / "ffmpeg.exe"', source)
        self.assertIn("[ffmpeg, \"-hide_banner\", \"-encoders\"]", source)

    def test_output_filename_contains_brand_multiplier_and_result_fps(self):
        self.assertEqual(
            anime_vfi_gui.build_output_filename("1", "mp4", 60.0, 8),
            "1_oniflow_8x-480fps.mp4",
        )
        self.assertEqual(
            anime_vfi_gui.build_output_filename("1", "mp4", 60.0, 10, 10),
            "1_oniflow_10x-60fps(slowmo).mp4",
        )
        self.assertEqual(
            anime_vfi_gui.build_output_filename("clip", "mkv", 23.976, 5, 2),
            "clip_oniflow_5x-59.94fps(slowmo).mkv",
        )

    def test_queue_worker_does_not_read_tkinter_job_controls(self):
        source = inspect.getsource(anime_vfi_gui.AnimeVfiPro._run_queue)
        for control in ("self.mode.get()", "self.output_format.get()", "self.multiplier.get()", "self.slow_motion.get()"):
            self.assertNotIn(control, source)
        self.assertIn("Queue worker stopped unexpectedly", source)
        self.assertIn('self.events.put(("done", failures))', source)

    def test_installer_has_normal_windows_install_features(self):
        installer = (ROOT / "installer.iss").read_text(encoding="utf-8")
        self.assertIn("OutputDir=installer-output", installer)
        self.assertIn('Source: "release\\Oniflow\\*"', installer)
        self.assertIn("UninstallDisplayIcon=", installer)
        self.assertIn("Uninstallable=yes", installer)
        self.assertIn("CreateUninstallRegKey=yes", installer)
        self.assertIn("UninstallDisplayName={#MyAppName}", installer)
        self.assertIn("PrivilegesRequired=admin", installer)
        self.assertIn("ArchitecturesInstallIn64BitMode=x64compatible", installer)
        self.assertIn("DefaultDirName={autopf64}\\Oniflow", installer)
        self.assertIn("WizardStyle=modern", installer)
        self.assertIn("Name: \"{autodesktop}\\Oniflow\"", installer)
        self.assertTrue((ROOT / "build_installer.ps1").is_file())
        build_installer = (ROOT / "build_installer.ps1").read_text(encoding="utf-8")
        self.assertIn("Get-FileHash $Installer.FullName -Algorithm SHA256", build_installer)
        self.assertIn('installer-output\\SHA256SUMS.txt', build_installer)
        self.assertLess(build_installer.index("sign_oniflow.ps1"), build_installer.index("Get-FileHash"))

    def test_free_native_build_and_test_signing_workflows_exist(self):
        native = (ROOT / "build_native_release.ps1").read_text(encoding="utf-8")
        release = (ROOT / "build_release.ps1").read_text(encoding="utf-8")
        setup = (ROOT / "setup_native_build.ps1").read_text(encoding="utf-8")
        signing = (ROOT / "sign_oniflow.ps1").read_text(encoding="utf-8")
        certificate = (ROOT / "create_test_signing_certificate.ps1").read_text(encoding="utf-8")
        self.assertIn("-NativeLauncher", native)
        self.assertIn("-m nuitka", release)
        self.assertLess(release.index("sign_oniflow.ps1"), release.index("& $Python $IntegrityAdmin"))
        self.assertIn("nuitka ordered-set zstandard", setup)
        self.assertIn("Set-AuthenticodeSignature", signing)
        self.assertIn("New-SelfSignedCertificate", certificate)
        self.assertIn("$IconPath = Join-Path $Root", release)
        self.assertIn("$LauncherSource = Join-Path $Root", release)
        self.assertIn('-Filter "__pycache__"', release)
        self.assertIn("$PrunedRuntimePackages", release)
        self.assertIn("$PrunedRuntimePaths", release)
        self.assertIn('"imageio_ffmpeg"', release)
        self.assertIn('"rawpy"', release)
        self.assertIn('"grpc"', release)
        self.assertIn('"tensorboard"', release)
        self.assertIn('"Lib\\site-packages\\torch\\include"', release)
        self.assertIn('".whl"', release)
        self.assertIn('".lib"', release)
        self.assertIn('-Filter "tests"', release)


if __name__ == "__main__":
    unittest.main()
