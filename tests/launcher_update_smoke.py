"""Check update channels, verified downloads, and the Windows restart helper."""
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("update_smoke", Path(__file__).resolve().parents[1] / "progressor.py")
app = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = app
spec.loader.exec_module(app)


def release(tag, *names, draft=False, prerelease=False):
    return dict(tag_name=tag, draft=draft, prerelease=prerelease,
                assets=[dict(name=name, state="uploaded") for name in names])


exe = "ProgressionLauncher-v0.4.10.exe"
apple = "ProgressionLauncher-macOS-v0.4.10-arm64-test.zip"
intel = "ProgressionLauncher-macOS-v0.4.10-x86_64-test.zip"
linux = "ProgressionLauncher-Linux-v0.4.10-x86_64-test.tar.gz"
releases = [
    release("v0.4.11", "ProgressionLauncher-v0.4.11.exe", draft=True),
    release("v0.4.11-candidate.1", "ProgressionLauncher-v0.4.11.exe", prerelease=True),
    release("v0.4.11-macos-test", "ProgressionLauncher-macOS-v0.4.11-arm64-test.zip", prerelease=True),
    release("v0.4.10-linux-test", linux, prerelease=True),
    release("v0.4.10-macos-test", apple, intel, prerelease=True),
    release("v0.4.10", exe, exe + ".sha256"),
    release("v0.4.9", "ProgressionLauncher-v0.4.9.exe"),
]
windows = app.select_update(releases, "0.4.9", "win32", "AMD64")
assert windows.asset == exe and windows.checksum_available
assert app.select_update(releases, "0.4.10", "win32", "AMD64") is None
assert app.select_update(releases, "0.4.10-candidate.1", "win32", "AMD64") == windows
assert app.select_update(releases, "0.4.9", "darwin", "arm64").version == "0.4.11"
assert app.select_update(releases, "0.4.9", "darwin", "x86_64").asset == intel
assert app.select_update(releases, "0.4.9", "linux", "x86_64").asset == linux
assert app.select_update(releases, "0.4.9", "linux", "aarch64") is None

with tempfile.TemporaryDirectory(prefix="launcher update test ") as folder:
    root = Path(folder)
    original = root / "Progression Launcher.exe"
    original.write_bytes(b"original")
    payload = b"MZ fake executable for the download test"
    checksum = hashlib.sha256(payload).hexdigest()
    listing = f"{checksum}  {exe}\n".encode()

    with patch.object(app, "open_release_asset", side_effect=[io.BytesIO(listing), io.BytesIO(payload)]):
        staged, digest = app.stage_windows_update(windows, original, lambda _: None)
    assert staged.read_bytes() == payload and digest == checksum
    assert original.read_bytes() == b"original"
    shutil.rmtree(staged.parent)

    with patch.object(app, "open_release_asset", side_effect=[io.BytesIO(listing), io.BytesIO(b"wrong")]):
        try:
            app.stage_windows_update(windows, original, lambda _: None)
        except RuntimeError as exc:
            assert "checksum" in str(exc)
        else:
            raise AssertionError("An invalid download must be rejected")
    assert list(root.iterdir()) == [original]

    if sys.platform == "win32":
        stage = root / "staged"
        stage.mkdir()
        staged = stage / "verified-update.exe"
        # A tiny GUI fixture exits immediately after recording its working directory.
        compile_fixture = """
Add-Type -TypeDefinition 'public class Fixture { public static void Main() {
System.IO.File.WriteAllText("restart.txt", "restarted");
} }' -OutputAssembly $env:UPDATE_TEST_EXE -OutputType WindowsApplication
"""
        powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command", compile_fixture],
                       env=dict(os.environ, UPDATE_TEST_EXE=str(staged)), check=True,
                       creationflags=subprocess.CREATE_NO_WINDOW, timeout=30)
        checksum = hashlib.sha256(staged.read_bytes()).hexdigest()
        old = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1)"],
                               creationflags=subprocess.CREATE_NO_WINDOW)
        with patch.object(app.os, "getpid", return_value=old.pid):
            helper = app.start_windows_handoff(original, staged, checksum)
        try:
            assert helper.wait(timeout=20) == 0
        finally:
            if helper.poll() is None:
                helper.kill()
                helper.wait()
            old.wait(timeout=5)
        marker = root / "restart.txt"
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert marker.read_text() == "restarted"
        assert hashlib.sha256(original.read_bytes()).hexdigest() == checksum
        backup, = (root / ".progression-launcher-backups").glob("*.exe")
        assert backup.read_bytes() == b"original"
        assert not stage.exists()

print("Update channels, checksum rejection, and Windows replacement and restart checks passed")
