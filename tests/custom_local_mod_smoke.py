"""Exercise a named addon through scan, pin, sort, freeze and stage."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile

spec = importlib.util.spec_from_file_location('progressor_custom_smoke', Path(__file__).resolve().parents[1] / 'progressor.py')
app = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = app
spec.loader.exec_module(app)


def write_mod(path, package, after='', name=None):
    (path / 'About').mkdir(parents=True)
    (path / 'About' / 'About.xml').write_text(
        f'<ModMetaData><name>{name or package}</name><packageId>{package}</packageId>'
        f'<loadAfter><li>{after}</li></loadAfter></ModMetaData>', encoding='utf-8')
    (path / 'content.txt').write_text('original', encoding='utf-8')


with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    app.ALWAYS_ENABLED_PATH = root / 'app' / 'always_enabled.json'
    app.DISABLED_MODS_PATH = root / 'app' / 'disabled_mods.json'
    app.LOCAL_METADATA_CACHE_PATH = root / 'app' / 'metadata.json'
    app.SORT_CACHE_PATH = root / 'app' / 'sort.json'
    app.configure_frozen_profiles_path(root / 'frozen')
    game = root / 'Game'
    local = game / 'Mods'
    workshop = root / 'Workshop'
    workshop.mkdir()
    addon = local / 'Progressor Random Worlds'
    write_mod(addon, 'sebas.randomworlds', 'ferny.worldbuilder', name='Progressor Random Worlds')
    write_mod(workshop / '12345', 'ferny.worldbuilder')
    (local / 'unfinished folder').mkdir()
    game.joinpath('RimWorldWin64.exe').write_text('fixture executable', encoding='utf-8')
    game.joinpath('RimWorldMac').write_text('fixture executable', encoding='utf-8')
    config = root / 'UserData' / 'Config' / 'ModsConfig.xml'
    config.parent.mkdir(parents=True)
    config.write_text('<ModsConfigData><activeMods><li>ludeon.rimworld</li>'
                      '<li>sebas.randomworlds</li><li>ferny.worldbuilder</li>'
                      '</activeMods></ModsConfigData>', encoding='utf-8')
    required = {'12345': app.WorkshopItem('Core', '12345', 'Worldbuilder')}
    scan = lambda: app.scan_with_required(required, workshop, local, config, lambda _: None)
    result = scan()
    custom_id, = result.extra_ids
    assert custom_id.startswith('local.')
    assert result.item_paths[custom_id] == addon
    assert app.extra_mod_label(result, custom_id).startswith('Progressor Random Worlds')
    assert custom_id not in app.extra_mod_label(result, custom_id)
    assert custom_id not in result.local_steamcmd_ids
    assert custom_id not in app.steamcmd_update_target_ids(result)
    assert custom_id not in app.steam_workshop_update_target_ids(result)
    assert not app.scan_mod_folder(local)[0], 'Workshop-only scan must ignore named folders'
    assert 'sebas.randomworlds' not in app.build_vanilla_sorted_active_list(result).package_ids
    app.save_always_enabled_ids({custom_id})
    assert app.load_always_enabled_ids() == {custom_id}
    result = scan()
    ordered = app.build_vanilla_sorted_active_list(result).package_ids
    assert ordered.index('ferny.worldbuilder') < ordered.index('sebas.randomworlds')
    app.save_disabled_ids({custom_id})
    assert app.load_disabled_ids() == {custom_id}
    assert custom_id not in scan().disabled_ids, 'Always Enabled takes precedence'
    renamed = addon.with_name('Renamed Addon')
    addon.rename(renamed)
    result = scan()
    assert result.extra_ids == [custom_id], 'Pin identity must survive a folder rename'
    active = app.frozen_active_item_ids(result)
    assert custom_id in active
    plans = app.plan_mod_snapshots(result, active)
    profile = app.create_frozen_profile(result, 'Custom Mod Test', [], plans, lambda _: None)
    staged = app.stage_frozen_profile('Custom Mod Test', lambda _: None)
    assert custom_id in staged.item_ids
    frozen_content = profile / 'Game' / 'Mods' / custom_id / 'content.txt'
    assert frozen_content.read_text() == 'original'
    (renamed / 'content.txt').write_text('updated live addon', encoding='utf-8')
    assert frozen_content.read_text() == 'original', 'Live edits must not alter a frozen addon'
    for bad_id in ('../oops', 'local.../../oops', 'C:\\oops', 'local.bad', ''):
        assert not app.valid_mod_item_id(bad_id)
    # Read-only frozen files need the launcher's cleanup on Windows.
    app.remove_tree(root / 'frozen')
print('Custom local mod scan, pin, sort, freeze and isolation checks passed')
