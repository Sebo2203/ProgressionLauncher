"""SteamCMD output remains responsive during silent downloads and carriage-return updates."""
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('download_progress_test', Path(__file__).resolve().parents[1] / 'progressor.py')
app = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = app
spec.loader.exec_module(app)

# Real pipe: silence must produce status events while the child is still alive.
code = "import time; print('Connecting to Steam...', flush=True); time.sleep(.25); print('Downloading item 12345678 ...', flush=True); print('25%\\r50%\\r', end='', flush=True)"
process = subprocess.Popen([sys.executable, '-u', '-c', code], stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, text=True)
events = list(app.steamcmd_output_events(process, heartbeat_seconds=.05))
assert process.wait(timeout=5) == 0
assert None in events, 'A quiet live process must emit heartbeat events'
lines = [line.strip() for line in events if line is not None]
assert lines == ['Connecting to Steam...', 'Downloading item 12345678 ...', '25%', '50%'], lines
process.stdout.close()

# A closed output pipe is not proof that the child has finished.
process = subprocess.Popen([sys.executable, '-u', '-c',
    'import os,time; os.close(1); os.close(2); time.sleep(.25)'], stdout=subprocess.PIPE, text=True)
assert None in list(app.steamcmd_output_events(process, heartbeat_seconds=.05))
assert process.wait(timeout=5) == 0
process.stdout.close()

# The complete downloader still counts real completions and reports the mod's name.
with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    local = root / 'Mods'
    about = local / '12345678' / 'About'
    about.mkdir(parents=True)
    (about / 'About.xml').write_text('<ModMetaData><packageId>test.download</packageId></ModMetaData>')
    result = app.ScanResult.__new__(app.ScanResult)
    result.required = {'12345678': app.WorkshopItem('Core', '12345678', 'Example Mod')}
    result.local_mods_path = local
    log = root / 'workshop_log.txt'
    log.write_text('Old download item 99999999 requested by app\n')
    positions = {log: log.stat().st_size}
    assert app.steamcmd_log_updates(positions) == [], 'Do not replay old downloads'
    with log.open('a') as handle:
        handle.write('Running full workshop file validation\nDownload item 12345678 requested by app\n')
    updates = app.steamcmd_log_updates(positions)
    assert len(updates) == 2 and 'validation' in updates[0]
    assert app.steamcmd_log_updates(positions) == [], 'Do not repeat log messages'
    log.write_text('Download item 12345678 failed\n')
    assert 'failed' in app.steamcmd_log_updates(positions)[0], 'Handle rotated logs'
    messages, counts = [], []
    def output_events(process):
        yield 'Connecting to Steam...\n'
        yield 'Downloading item 12345678 ...\n'
        yield None
        yield 'Success. Downloaded item 12345678 (10 bytes)\n'
    from unittest.mock import Mock
    child = Mock()
    child.wait.return_value = 0
    child.stdout = iter([])
    with patch.object(app, 'fetch_remote_update_times') as check_metadata, \
         patch.object(app, 'find_or_install_steamcmd', return_value=root/'steamcmd'), \
         patch.object(app, 'relocate_unregistered_workshop_mods'), \
         patch.object(app, 'prepare_steamcmd_local_download_root', return_value=local), \
         patch.object(app, 'steamcmd_output_events', side_effect=output_events), \
         patch.object(app.subprocess, 'Popen', return_value=child) as popen:
        assert app.run_steamcmd_downloads(result, messages.append, targets=['12345678'],
            progress_count=lambda done,total: counts.append((done,total)),
            checked_update_times={'12345678': 123}) == local
        check_metadata.assert_not_called()
        if sys.platform == "win32":
            assert popen.call_args.kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW
    assert any('Example Mod (12345678)' in message for message in messages)
    assert any('Process is running; waiting for Steam.' in message for message in messages)
    assert any('Connecting to Steam' in message for message in messages)
    assert counts[0] == (0,1) and counts[-1] == (1,1)
    assert all(done in (0,1) for done,total in counts), 'Never invent download progress'
print('Quiet-process heartbeat, carriage-return output, EOF waiting, named downloads and completion counts passed')
