"""Exercise both live launch buttons without Tk, network, Steam or the game."""
import importlib.util
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
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
    app.write_mods_config(result, lambda _: None)
    with patch.object(app, 'backup_file', side_effect=AssertionError('Identical config should not be backed up')):
        app.write_mods_config(result, lambda _: None)

    mixed = SimpleNamespace(required_order=['101', '102', '103', '104'],
                            local_steamcmd_ids={'101', '104'}, disabled_ids={'104'},
                            always_enabled_ids=set(), missing_ids=['102'], unregistered_ids=[])
    ui = SimpleNamespace(
        progress=lambda _: None, after=lambda _, fn: fn(),
        show_activity=lambda: None, steamcmd_path=SimpleNamespace(set=lambda _: None),
        save_configured_paths=lambda: None, update_busy_check_progress=lambda *_: None,
        update_busy_download_progress=lambda *_: None, scan_paths_with_required=lambda *_: mixed,
    )
    with patch.object(app, 'fetch_remote_update_times', side_effect=[{'101': 2}, {'102': 2}]) as check, \
         patch.object(app, 'find_or_install_steamcmd', return_value=root / 'steamcmd'), \
         patch.object(app, 'workshop_outdated_ids', return_value=(['101'], [])), \
         patch.object(app, 'reuse_current_workshop_copies', return_value=[]), \
         patch.object(app, 'parse_steamcmd_update_times', return_value={'101': 1}), \
         patch.object(app, 'run_steamcmd_downloads') as downloads:
        app.ProgressorApp.apply_updates_before_launch(ui, mixed, {})
        assert [call.args[0] for call in check.call_args_list] == [['101'], ['102']]
        downloads.assert_called_once()
        assert downloads.call_args.kwargs['targets'] == ['101', '102']

        check.side_effect = [{'101': 2}, {}]
        downloads.reset_mock()
        app.ProgressorApp.apply_updates_before_launch(ui, mixed, {})
        assert downloads.call_args.kwargs['targets'] == ['101'], 'Unknown missing mod must keep its separate review path'
print('Both live launch buttons apply and verify pins with auto-update on/off; failures block launch; running game remains untouched.')
