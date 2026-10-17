"""Exercise both live launch buttons without Tk, network, Steam or the game."""
import importlib.util
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('progressor_live_launch', Path(__file__).resolve().parents[1] / 'progressor.py')
app = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = app
spec.loader.exec_module(app)


class Value:
    def __init__(self, value): self.value = value
    def get(self): return self.value


class Harness:
    play_now = app.ProgressorApp.play_now
    advanced_launch = app.ProgressorApp.advanced_launch
    def __init__(self, result, auto_update):
        self.result = result
        self.auto_update_on_launch = Value(auto_update)
        self.steamcmd_path = Value('')
        self.current_result = None
        self.current_sort_result = None
        self.update_count = 0
    def auto_detect_invalid_paths(self): pass
    def progress(self, message): pass
    def scan_paths_with_required(self, required, progress): return self.result
    def apply_updates_before_launch(self, result, required):
        self.update_count += 1
        return result
    def after(self, delay, callback): callback()
    def render_result(self, *args): pass
    def run_busy_worker(self, label, worker): worker()


with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    app.ALWAYS_ENABLED_PATH = root / 'pins.json'
    app.DISABLED_MODS_PATH = root / 'disabled.json'
    app.LOCAL_METADATA_CACHE_PATH = root / 'metadata.json'
    app.SORT_CACHE_PATH = root / 'sort.json'
    local, workshop = root / 'Mods', root / 'Workshop'
    workshop.mkdir()
    for name, package in [('123', 'test.pack'), ('RandomWorlds', 'sebas.progressorrandomworlds')]:
        about = local / name / 'About'
        about.mkdir(parents=True)
        (about / 'About.xml').write_text(f'<ModMetaData><name>{name}</name><packageId>{package}</packageId></ModMetaData>')
    ids, packages, _ = app.scan_mod_folder(local, include_custom=True)
    addon = next(i for i in ids if packages[i] == 'sebas.progressorrandomworlds')
    app.save_always_enabled_ids({addon})
    required = {'123': app.WorkshopItem('Core', '123', 'Test pack')}
    config = root / 'Config' / 'ModsConfig.xml'
    config.parent.mkdir()
    def reset_config():
        config.write_text('<ModsConfigData><version>1.7</version><activeMods><li>ludeon.rimworld</li><li>test.pack</li></activeMods></ModsConfigData>')
    reset_config()
    result = app.scan_with_required(required, workshop, local, config, lambda _: None)
    with patch.object(app, 'rimworld_is_running', return_value=False), patch.object(app, 'fetch_required_items', return_value=required), patch.object(app.messagebox, 'showerror') as errors:
        for button in ('play_now', 'advanced_launch'):
            for auto_update in (False, True):
                reset_config()
                harness = Harness(result, auto_update)
                def check_launch(url):
                    assert url == app.STEAM_RUN_RIMWORLD
                    assert 'sebas.progressorrandomworlds' in app.existing_active_mods(config), 'Launch happened before pin was written'
                with patch.object(app.webbrowser, 'open', side_effect=check_launch) as launch:
                    getattr(harness, button)()
                    launch.assert_called_once()
                assert harness.update_count == int(auto_update)
        errors.assert_not_called()
        reset_config()
        with patch.object(app, 'write_mods_config', return_value=config), patch.object(app.webbrowser, 'open') as launch:
            Harness(result, False).advanced_launch()
            launch.assert_not_called()
            assert 'does not match' in errors.call_args.args[1]
        errors.reset_mock()
        result.always_enabled_ids.add('local.missing')
        with patch.object(app.webbrowser, 'open') as launch:
            Harness(result, False).play_now()
            launch.assert_not_called()
            assert 'Always Enabled' in errors.call_args.args[1]
        result.always_enabled_ids.remove('local.missing')
    with patch.object(app, 'rimworld_is_running', return_value=True), patch.object(app.messagebox, 'showinfo'), patch.object(app.webbrowser, 'open') as launch:
        reset_config()
        before = config.read_bytes()
        Harness(result, False).advanced_launch()
        launch.assert_not_called()
        assert config.read_bytes() == before
print('Both live launch buttons apply and verify pins with auto-update on/off; failures block launch; running game remains untouched.')
