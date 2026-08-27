import importlib.util
import json
import os
import plistlib
import shutil
import sys
import tempfile
import types
import zipfile
import tarfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = REPO_ROOT / "progressor.py"


def load_progressor():
    spec = importlib.util.spec_from_file_location("progressor_macos_smoke", SOURCE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_mod(mod_dir: Path, package_id: str, name: str) -> None:
    about = mod_dir / "About"
    about.mkdir(parents=True)
    (about / "About.xml").write_text(
        f"""<?xml version="1.0" encoding="utf-8"?>
<ModMetaData>
  <name>{name}</name>
  <packageId>{package_id}</packageId>
</ModMetaData>
""",
        encoding="utf-8",
    )
    (mod_dir / "data.txt").write_text(f"{name} content\n", encoding="utf-8")


def make_fake_steamcmd_tar(path: Path) -> None:
    script = b"#!/bin/sh\nexit 0\n"
    with tarfile.open(path, "w:gz") as archive:
        info = tarfile.TarInfo("steamcmd.sh")
        info.mode = 0o755
        info.size = len(script)
        archive.addfile(info, fileobj=types.SimpleNamespace(read=lambda _n=-1: script))


class FakeUrlOpen:
    def __init__(self, payload_path: Path):
        self.payload_path = payload_path

    def __call__(self, _request, timeout=60):
        return self.payload_path.open("rb")


def assert_true(condition, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    progressor = load_progressor()
    original_platform = progressor.sys.platform
    original_app_data_dir = progressor.app_data_dir
    original_urlopen = progressor.urllib.request.urlopen
    original_run = progressor.subprocess.run
    original_popen = progressor.subprocess.Popen
    original_env = dict(os.environ)
    root = Path(tempfile.mkdtemp(prefix="progression_launcher_macos_"))
    launched_commands: list[list[str]] = []

    try:
        progressor.sys.platform = "darwin"
        os.environ.pop("STEAMCMD", None)
        app_data = root / "Library" / "Application Support" / "ProgressionLauncher"
        progressor.app_data_dir = lambda: app_data
        progressor.configure_frozen_profiles_path(app_data / "frozen_profiles")

        steam_root = root / "Library" / "Application Support" / "Steam"
        library = root / "External Steam Library"
        steam_root.mkdir(parents=True)
        (steam_root / "steamapps").mkdir()
        (steam_root / "steamapps" / "libraryfolders.vdf").write_text(
            f'"libraryfolders"\n{{\n  "0"\n  {{\n    "path" "{str(library).replace("\\", "\\\\")}"\n  }}\n}}\n',
            encoding="utf-8",
        )
        game_app = library / "steamapps" / "common" / "RimWorld" / "RimWorldMac.app"
        executable = game_app / "Contents" / "MacOS" / "RimWorldMac"
        executable.parent.mkdir(parents=True)
        executable.write_text("#!/bin/sh\n", encoding="utf-8")
        executable.chmod(0o755)
        (game_app / "Contents" / "Info.plist").write_bytes(
            plistlib.dumps({"CFBundleExecutable": "RimWorldMac"})
        )
        local_mods = game_app / "Mods"
        local_mods.mkdir(parents=True)
        workshop = library / "steamapps" / "workshop" / "content" / progressor.APP_ID
        workshop.mkdir(parents=True)

        mod_a = local_mods / "1111111111"
        mod_b = workshop / "2222222222"
        write_mod(mod_a, "progression.mod.a", "Progression Mod A")
        write_mod(mod_b, "progression.mod.b", "Progression Mod B")

        config = root / "Library" / "Application Support" / "RimWorld" / "Config" / "ModsConfig.xml"
        config.parent.mkdir(parents=True)
        config.write_text(
            """<?xml version="1.0" encoding="utf-8"?>
<ModsConfigData>
  <activeMods>
    <li>ludeon.rimworld</li>
    <li>progression.mod.a</li>
    <li>progression.mod.b</li>
  </activeMods>
</ModsConfigData>
""",
            encoding="utf-8",
        )
        saves = config.parent.parent / "Saves"
        saves.mkdir()
        (saves / "Colony.rws").write_text("save", encoding="utf-8")

        assert_true(progressor.rimworld_game_root_from_mods_path(local_mods) == game_app, "Mac .app game root was not detected from Mods path.")
        assert_true(progressor.rimworld_executable(game_app) == executable, "Mac RimWorld executable was not detected from Info.plist.")

        result = progressor.ScanResult(
            required={
                "1111111111": progressor.WorkshopItem("Core", "1111111111", "Progression Mod A"),
                "2222222222": progressor.WorkshopItem("Core", "2222222222", "Progression Mod B"),
            },
            required_order=["1111111111", "2222222222"],
            installed_ids={"1111111111", "2222222222"},
            installed_package_ids={
                "1111111111": "progression.mod.a",
                "2222222222": "progression.mod.b",
            },
            item_paths={"1111111111": mod_a, "2222222222": mod_b},
            local_steamcmd_ids={"1111111111"},
            steam_registered_ids={"2222222222"},
            missing_ids=[],
            unregistered_ids=[],
            extra_ids=[],
            ready_ids=["1111111111", "2222222222"],
            always_enabled_ids=set(),
            disabled_ids=set(),
            workshop_path=workshop,
            local_mods_path=local_mods,
            mods_config_path=config,
        )

        plans = progressor.plan_mod_snapshots(result, ["1111111111", "2222222222"])
        profile = progressor.create_frozen_profile(
            result,
            "Mac Smoke",
            ["Colony.rws"],
            plans,
            lambda _message: None,
        )
        manifest = json.loads((profile / "manifest.json").read_text(encoding="utf-8"))
        assert_true(manifest["game_executable"] == "Contents/MacOS/RimWorldMac", "Frozen profile recorded the wrong Mac executable.")
        staged = progressor.stage_frozen_profile("Mac Smoke", lambda _message: None)
        assert_true(staged.executable_path.name == "RimWorldMac", "Frozen stage did not return the Mac executable.")
        assert_true((profile / "Game" / "Mods" / "1111111111" / "About" / "About.xml").exists(), "Frozen local mod was not linked into Game/Mods.")
        assert_true((profile / "Game" / "Mods" / "2222222222" / "About" / "About.xml").exists(), "Frozen workshop mod was not linked into Game/Mods.")

        steamcmd_root = root / "SteamCMD"
        steamcmd_root.mkdir()
        symlink_calls: list[tuple[Path, Path, bool]] = []
        original_symlink_to = type(steamcmd_root).symlink_to
        try:
            if original_platform == "win32":
                def fake_symlink_to(self, target, target_is_directory=False):
                    symlink_calls.append((self, Path(target), target_is_directory))
                    self.mkdir(parents=True, exist_ok=False)

                type(steamcmd_root).symlink_to = fake_symlink_to
            redirect = progressor.prepare_steamcmd_local_download_root(
                steamcmd_root,
                local_mods,
                lambda _message: None,
            )
        finally:
            type(steamcmd_root).symlink_to = original_symlink_to
        if original_platform == "win32":
            assert_true(symlink_calls, "Mac SteamCMD redirect did not request a symlink.")
            assert_true(symlink_calls[0][1] == local_mods.resolve(), "Mac SteamCMD symlink target was wrong.")
            assert_true(symlink_calls[0][2] is True, "Mac SteamCMD symlink was not marked as a directory.")
        else:
            assert_true(redirect.is_symlink(), "Mac SteamCMD redirect was not created as a symlink.")
            assert_true(redirect.resolve().samefile(local_mods.resolve()), "Mac SteamCMD symlink did not point at local Mods.")

        fake_tar = root / "steamcmd_osx.tar.gz"
        make_fake_steamcmd_tar(fake_tar)
        progressor.urllib.request.urlopen = FakeUrlOpen(fake_tar)
        installed = progressor.install_steamcmd(lambda _message: None)
        assert_true(installed.name == "steamcmd.sh", "Mac SteamCMD installer did not resolve steamcmd.sh.")

        def fake_run(command, *args, **kwargs):
            if command[:2] == ["pgrep", "-if"]:
                return types.SimpleNamespace(stdout="", returncode=1)
            return original_run(command, *args, **kwargs)

        class FakePopen:
            def __init__(self, command, *args, **kwargs):
                launched_commands.append(command)

        progressor.subprocess.run = fake_run
        progressor.subprocess.Popen = FakePopen
        assert_true(progressor.rimworld_is_running() is False, "Mac RimWorld running check should be false for empty pgrep output.")
        progressor.launch_frozen_game(staged.executable_path, staged.user_data_path, lambda _message: None)
        assert_true(launched_commands and launched_commands[0][0].endswith("RimWorldMac"), "Frozen launch did not call the Mac executable.")
        assert_true(any(arg.startswith("-savedatafolder=") for arg in launched_commands[0]), "Frozen launch missed -savedatafolder.")

        print("macOS compatibility smoke passed")
        return 0
    finally:
        progressor.subprocess.Popen = original_popen
        progressor.subprocess.run = original_run
        progressor.urllib.request.urlopen = original_urlopen
        progressor.app_data_dir = original_app_data_dir
        progressor.sys.platform = original_platform
        os.environ.clear()
        os.environ.update(original_env)
        try:
            progressor.remove_tree(root)
        except Exception:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
