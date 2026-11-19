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
stable_05 = [release("v0.5.0", "ProgressionLauncher-v0.5.0.exe", "ProgressionLauncher-v0.5.0.exe.sha256")]
assert app.select_update(stable_05, "0.4.9", "win32", "AMD64").version == "0.5.0"
assert app.select_update(stable_05, "0.5", "win32", "AMD64") is None
assert app.select_update([release("v0.6", "ProgressionLauncher-v0.6.exe")], "0.5", "win32", "AMD64").version == "0.6"

with tempfile.TemporaryDirectory(prefix="launcher update test ") as folder:
    root = Path(folder)
    original = root / "Progression Launcher.exe"
    original.write_bytes(b"original")
    payload = b"MZ fake executable for the download test"
    checksum = hashlib.sha256(payload).hexdigest()
    listing = f"{checksum}  {exe}\n".encode()

    response = io.BytesIO(payload)
    response.headers = {"Content-Length": str(len(payload))}
    counts = []
    with patch.object(app, "open_release_asset", side_effect=[io.BytesIO(listing), response]):
        staged, digest = app.stage_windows_update(windows, original, lambda _: None,
                                                  lambda done, total: counts.append((done, total)))
    assert staged.read_bytes() == payload and digest == checksum
    assert counts[-1] == (len(payload), len(payload))
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
        # The fixture confirms only when the helper requests it, like the launcher.
        healthy = '''
var marker = System.Environment.GetEnvironmentVariable("PROGRESSION_UPDATE_READY");
if (marker != null) System.IO.File.WriteAllText(marker, "ready");
System.IO.File.WriteAllText("restart.txt", "restarted");
'''
        compile_fixture = """Add-Type -TypeDefinition $env:UPDATE_TEST_CODE -OutputAssembly $env:UPDATE_TEST_EXE -OutputType WindowsApplication"""
        powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"

        def make_fixture(body):
            code = "public class Fixture { public static void Main() {" + body + "} }"
            subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command", compile_fixture],
                           env=dict(os.environ, UPDATE_TEST_CODE=code, UPDATE_TEST_EXE=str(staged)), check=True,
                           creationflags=subprocess.CREATE_NO_WINDOW, timeout=30)
            return hashlib.sha256(staged.read_bytes()).hexdigest()

        # Capture a failure notification to a test file instead of opening a modal.
        script = app.WINDOWS_HANDOFF.replace(
            "[Windows.Forms.MessageBox]::Show($reason, 'Progression Launcher update failed') | Out-Null",
            "[IO.File]::WriteAllText((Join-Path $parent 'failure.txt'), $reason)",
        )

        def install_fixture(checksum):
            old = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1)"],
                                   creationflags=subprocess.CREATE_NO_WINDOW)
            with patch.object(app.os, "getpid", return_value=old.pid), patch.object(app, "WINDOWS_HANDOFF", script):
                helper = app.start_windows_handoff(original, staged, checksum)
            try:
                assert helper.wait(timeout=20) == 0
            finally:
                if helper.poll() is None:
                    helper.kill()
                    helper.wait()
                old.wait(timeout=5)

        checksum = make_fixture(healthy)
        install_fixture(checksum)
        marker = root / "restart.txt"
        assert hashlib.sha256(original.read_bytes()).hexdigest() == checksum
        backup, = (root / ".progression-launcher-backups").glob("*.exe")
        assert backup.read_bytes() == b"original"
        assert not stage.exists()
        assert not (root / "failure.txt").exists()

        stage.mkdir()
        bad_checksum = make_fixture("System.Environment.Exit(7);")
        marker.unlink(missing_ok=True)
        install_fixture(bad_checksum)
        assert hashlib.sha256(original.read_bytes()).hexdigest() == checksum
        assert "previous version was restored" in (root / "failure.txt").read_text()
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert marker.read_text() == "restarted" and not stage.exists()

print("Update channels, download progress, checksum rejection, and Windows startup recovery checks passed")
