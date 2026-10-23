"""Resolve retired uploads and recover from unknown unavailable items explicitly."""
import importlib.util
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location('launcher_replacement_test', Path(__file__).resolve().parents[1] / 'progressor.py')
app = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = app
spec.loader.exec_module(app)

with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    for attr in ('ALWAYS_ENABLED_PATH', 'DISABLED_MODS_PATH', 'LOCAL_METADATA_CACHE_PATH', 'SORT_CACHE_PATH'):
        setattr(app, attr, root / (attr + '.json'))
    local, workshop, config = root / 'Game/Mods', root / 'Workshop', root / 'Config/ModsConfig.xml'
    local.mkdir(parents=True)
    workshop.mkdir()
    config.parent.mkdir()
    config.write_text('<ModsConfigData><version>1.7</version><activeMods><li>ludeon.rimworld</li><li>ludeon.rimworld.biotech</li></activeMods></ModsConfigData>')
    def mod(item_id, package, title='Test mod'):
        about = local / item_id / 'About/About.xml'
        about.parent.mkdir(parents=True)
        about.write_text(f'<ModMetaData><name>{title}</name><packageId>{package}</packageId><supportedVersions><li>1.6</li></supportedVersions></ModMetaData>')
        return about
    required = {}
    for old, (title, new, new_title, package) in app.WORKSHOP_REPLACEMENTS.items():
        required[old] = app.WorkshopItem('Content', old, '')
        if old != '3628433732':
            required[new] = app.WorkshopItem('Content', new, new_title)
            mod(new, package, new_title)
    def scan(snapshot=None, **kwargs):
        return app.scan_with_required(required if snapshot is None else snapshot, workshop, local, config, lambda _: None, **kwargs)
    original = dict(required)
    result = scan()
    assert required == original
    assert set(result.replaced_items) == set(app.WORKSHOP_REPLACEMENTS)
    assert app.download_target_ids(result) == ['3667792009'], 'Only the author re-upload needs downloading'
    app.save_disabled_ids(set(app.WORKSHOP_REPLACEMENTS))
    assert set(scan().replaced_items) == set(app.WORKSHOP_REPLACEMENTS), 'Disabling a retired ID must not hide its curated replacement'
    assert app.download_target_ids(scan()) == ['3667792009']
    app.save_disabled_ids(set())
    assert not set(result.required) & set(app.WORKSHOP_REPLACEMENTS)
    config_before = config.read_bytes()
    try: app.write_mods_config(result, lambda _: None)
    except RuntimeError as error: assert 'missing or changed' in str(error)
    else: raise AssertionError('Missing replacement must not be silently omitted')
    assert config.read_bytes() == config_before
    mod('3667792009', 'xubisca.mightylivertweak', 'Mighty-Liver Tweak')
    result = scan()
    assert not app.download_target_ids(result), 'Do not reject a 1.6-tagged replacement on 1.7'
    app.write_mods_config(result, lambda _: None)
    assert 'xubisca.mightylivertweak' in app.existing_active_mods(config)
    app.save_disabled_ids({'3667792009'})
    result = scan()
    app.write_mods_config(result, lambda _: None)
    assert 'xubisca.mightylivertweak' not in app.existing_active_mods(config)
    app.save_disabled_ids(set())
    result = scan(excluded_dlcs={'ludeon.rimworld.biotech'})
    assert '3667792009' in result.dlc_exclusions
    app.write_mods_config(result, lambda _: None)
    app.save_always_enabled_ids({'3226502149'})
    assert '3226502149' in scan().missing_ids, 'Explicit legacy pins stay visible for review'
    app.save_always_enabled_ids(set())
    # A future upload with the same remembered package needs no registry change.
    old = mod('88888888', 'test.future', 'Remembered upload')
    mod('88888889', 'test.future', 'Curated new upload')
    future = {'88888888': app.WorkshopItem('Core', '88888888', ''), '88888889': app.WorkshopItem('Core', '88888889', 'Curated new upload')}
    scan(future)
    old.unlink()
    assert scan(future).replaced_items == {'88888888': '88888889'}
    other = mod('88888890', 'test.unrelated', 'Curated new upload')
    different = {'88888888': future['88888888'], '88888890': app.WorkshopItem('Core', '88888890', 'Curated new upload')}
    assert '88888888' in scan(different).required and not scan(different).replaced_items, 'Matching titles cannot establish identity'
    unknown = '9999999999'
    unknown_snapshot = {unknown: app.WorkshopItem('Core', unknown, '')}
    missing = scan(unknown_snapshot)
    class Harness:
        download_with_unavailable_review = app.ProgressorApp.download_with_unavailable_review
        def __init__(self, approve): self.approve = approve; self.reviews = []
        def progress(self, *args): pass
        def update_busy_download_progress(self, *args): pass
        def review_unavailable_items(self, result, ids):
            self.reviews.append(ids)
            if self.approve: app.save_disabled_ids(set(ids))
            return self.approve
        def scan_paths_with_required(self, snapshot, progress): return scan(snapshot)
    with patch.object(app, 'run_steamcmd_downloads', side_effect=app.UnavailableWorkshopItems(missing, [unknown])) as downloads:
        cancelled = Harness(False)
        try: cancelled.download_with_unavailable_review(missing, unknown_snapshot)
        except app.SetupCancelled: pass
        else: raise AssertionError('Cancel must stop setup')
        assert not app.load_disabled_ids()
        approved = Harness(True)
        ready = approved.download_with_unavailable_review(missing, unknown_snapshot)
        assert not app.download_target_ids(ready) and unknown in ready.disabled_ids
        assert approved.reviews == [[unknown]] and downloads.call_count == 2, 'Never retry an explicitly skipped item'
    class PlayHarness(Harness):
        play_now = app.ProgressorApp.play_now
        def __init__(self, approve):
            super().__init__(approve)
            self.auto_update_on_launch = SimpleNamespace(get=lambda: False)
            self.steamcmd_path = SimpleNamespace(get=lambda: '')
        def auto_detect_invalid_paths(self): pass
        def after(self, delay, callback): callback()
        def render_result(self, *args): pass
        def run_busy_worker(self, message, worker): worker()
    with patch.object(app, 'rimworld_is_running', return_value=False), patch.object(app, 'fetch_required_items', return_value=unknown_snapshot), patch.object(app, 'run_steamcmd_downloads', side_effect=app.UnavailableWorkshopItems(missing, [unknown])), patch.object(app.messagebox, 'showerror') as errors:
        app.save_disabled_ids(set())
        before = config.read_bytes()
        with patch.object(app.webbrowser, 'open') as launch:
            PlayHarness(False).play_now()
            launch.assert_not_called()
            assert config.read_bytes() == before and not app.load_disabled_ids()
        with patch.object(app.webbrowser, 'open') as launch:
            PlayHarness(True).play_now()
            launch.assert_called_once_with(app.STEAM_RUN_RIMWORLD)
            assert app.load_disabled_ids() == {unknown}
        errors.assert_not_called()
print('Seven known replacements, re-upload downloads, 1.6/1.7 acceptance, exclusions/pins, automatic package matches, config guards and explicit skip/cancel passed')
