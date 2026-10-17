"""Run the bundled encoder on disposable PNGs, never the live mod pack."""
import hashlib
import importlib.util
from pathlib import Path
import struct
import sys
import tempfile
from unittest.mock import patch
import zlib

spec = importlib.util.spec_from_file_location('progressor_texture_test', Path(__file__).resolve().parents[1] / 'progressor.py')
app = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = app
spec.loader.exec_module(app)

def png(path, alpha=False):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    pixel = bytes((180, 90, 30, 100)) if alpha else bytes((180, 90, 30))
    raw = b''.join(b'\0' + pixel * 16 for _ in range(16))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 16, 16, 8, 6 if alpha else 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))

def mod(path, package):
    (path/'About').mkdir(parents=True)
    (path/'About/About.xml').write_text(f'<ModMetaData><packageId>{package}</packageId></ModMetaData>')
    png(path/'Textures/test.png')

with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    app.ALWAYS_ENABLED_PATH = root/'pins.json'
    app.DISABLED_MODS_PATH = root/'disabled.json'
    app.LOCAL_METADATA_CACHE_PATH = root/'metadata.json'
    local, workshop = root/'Mods', root/'Workshop'
    workshop.mkdir()
    mod(local/'100', 'test.pack')
    mod(local/'200', 'test.disabled')
    mod(local/'Custom Addon', 'test.addon')
    mod(local/'Extra', 'test.extra')
    png(local/'100/Preview.png')
    png(local/'Custom Addon/Textures/alpha.png', True)
    ids, packages, _ = app.scan_mod_folder(local, include_custom=True)
    addon = next(i for i in ids if packages[i] == 'test.addon')
    app.save_always_enabled_ids({addon})
    app.save_disabled_ids({'200'})
    required = {i:app.WorkshopItem('Core',i,i) for i in ('100','200')}
    result = app.scan_with_required(required, workshop, local, root/'ModsConfig.xml', lambda _:None)
    paths = app.texture_optimization_paths(result)
    assert set(paths) == {(local/'100').resolve(), (local/'Custom Addon').resolve()}
    originals = {p:hashlib.sha256(p.read_bytes()).hexdigest() for p in local.rglob('*.png')}
    with patch.object(app, 'app_data_dir', return_value=root/'App'), patch.object(app, 'rimworld_is_running', return_value=False):
        log = app.run_texture_optimization(result, print)
        assert log.is_file()
        generated = list(local.rglob('*.dds'))
        assert len(generated) == 3
        for dds in generated:
            content = dds.read_bytes()
            assert content[:4] == b'DDS '
            assert struct.unpack_from('<II',content,12) == (16,16)
        before = {p:p.stat().st_mtime_ns for p in generated}
        app.run_texture_optimization(result, lambda _:None)
        assert before == {p:p.stat().st_mtime_ns for p in generated}, 'Current DDS should not be rewritten'
        assert all(hashlib.sha256(p.read_bytes()).hexdigest() == digest for p,digest in originals.items())
        with patch.object(app.subprocess, 'Popen') as process, patch.object(app, 'rimworld_is_running', return_value=True):
            try: app.run_texture_optimization(result, lambda _:None)
            except RuntimeError as error: assert 'Close RimWorld' in str(error)
            else: raise AssertionError('Must block while game runs')
            process.assert_not_called()
        with patch.object(app.subprocess, 'Popen') as process:
            process.return_value.stdout = iter(['encoder failed\n'])
            process.return_value.wait.return_value = 1
            try: app.run_texture_optimization(result, lambda _:None)
            except RuntimeError as error: assert 'exit 1' in str(error)
            else: raise AssertionError('Must report encoder failure')
    result.item_paths[addon] = root/'Unrelated'
    (root/'Unrelated').mkdir()
    try: app.texture_optimization_paths(result)
    except RuntimeError: pass
    else: raise AssertionError('Reject outside mod roots')
print('Real todds conversion, pin/disabled targeting, PNG preservation, DDS dimensions, incremental skip, game guard and failure handling passed.')
