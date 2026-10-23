"""Prevent the real Load Them Last startup operation from requesting a restart."""
import importlib.util
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('progressor_load_last', Path(__file__).resolve().parents[1] / 'progressor.py')
app = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = app
spec.loader.exec_module(app)


def mod_startup_order(order, settings):
    # Independent translation of the installed mod's C# startup hook.
    original = list(order)
    order = [package for package in order if package not in settings]
    for package in settings:
        if package in original:
            order.append(package)
    return order


with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    app.ALWAYS_ENABLED_PATH = root / 'pins.json'
    app.DISABLED_MODS_PATH = root / 'disabled.json'
    app.LOCAL_METADATA_CACHE_PATH = root / 'metadata.json'
    app.SORT_CACHE_PATH = root / 'sort.json'
    local, workshop = root / 'Mods', root / 'Workshop'
    workshop.mkdir()
    packages = {'100': 'ferny.loadthemlast', '101': 'sk.noambient',
                '102': 'vr.missilegirl', '103': 'test.later', '104': 'test.pinned'}
    for item, package in packages.items():
        about = local / item / 'About'
        about.mkdir(parents=True)
        rules = '<loadAfter><li>vr.missilegirl</li></loadAfter>' if item == '103' else ''
        (about / 'About.xml').write_text(f'<ModMetaData><name>{item}</name><packageId>{package}</packageId>{rules}</ModMetaData>')
    settings = local / '100' / '1.6' / 'Settings.xml'
    settings.parent.mkdir()
    settings.write_text('<Settings><loadLast><li>sk.noambient</li><li>vr.missilegirl</li><li>absent.mod</li></loadLast></Settings>')
    future = local / '100' / '1.8' / 'Settings.xml'
    future.parent.mkdir()
    future.write_text('<Settings><loadLast><li>test.later</li></loadLast></Settings>')
    # An empty newer version folder must fall back to 1.6, as the mod does.
    (local / '100' / '1.7').mkdir()
    config = root / 'Config' / 'ModsConfig.xml'
    config.parent.mkdir()
    config.write_text('<ModsConfigData><version>1.7</version><activeMods><li>ludeon.rimworld</li></activeMods></ModsConfigData>')
    app.save_always_enabled_ids({'104'})
    required = {item: app.WorkshopItem('Core', item, package) for item, package in packages.items() if item != '104'}
    result = app.scan_with_required(required, workshop, local, config, lambda _: None)
    base = app.build_vanilla_sorted_active_list(result)
    assert base.package_ids[-2:] == ['sk.noambient', 'vr.missilegirl']
    assert set(base.package_ids) == {'ludeon.rimworld', *packages.values()}
    assert mod_startup_order(base.package_ids, ['sk.noambient', 'vr.missilegirl', 'absent.mod']) == base.package_ids
    app.write_mods_config(result, lambda _: None, base)
    assert app.load_cached_sort_result(result) == base
    # Editing only the mod's Settings.xml must invalidate the sort cache.
    settings.write_text('<Settings><loadLast><li>vr.missilegirl</li><li>sk.noambient</li></loadLast></Settings>')
    assert app.load_cached_sort_result(result) is None
    changed = app.get_or_build_sort_result(result)
    assert changed.package_ids[-2:] == ['vr.missilegirl', 'sk.noambient']
    selected = local / '100' / '1.7' / 'Settings.xml'
    selected.write_text('<Settings><loadLast><li>test.later</li></loadLast></Settings>')
    assert app.load_cached_sort_result(result) is None
    assert app.get_or_build_sort_result(result).package_ids[-1] == 'test.later'
    selected.write_text('<broken')
    try:
        app.get_or_build_sort_result(result)
        raise AssertionError('Malformed active settings must block launch')
    except RuntimeError as exc:
        assert 'Load Them Last' in str(exc)
    result.disabled_ids.add('100')
    disabled = app.build_vanilla_sorted_active_list(result)
    assert 'ferny.loadthemlast' not in disabled.package_ids
    assert disabled.package_ids.index('vr.missilegirl') < disabled.package_ids.index('test.later')
    # A pin re-enables the mod, even if it was also disabled.
    result.always_enabled_ids.add('100')
    selected.write_text('<Settings><loadLast><li>test.later</li></loadLast></Settings>')
    assert 'ferny.loadthemlast' in app.build_vanilla_sorted_active_list(result).package_ids
    selected.unlink()
    settings.unlink()
    assert app.load_them_last_settings(result, set(packages.values()), '1.7') == ('', [])

print('Load Them Last ordering is stable before game startup; version fallback, pins, disabled mods and settings cache invalidation passed.')
