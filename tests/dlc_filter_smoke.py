"""DLC filtering must cover hard dependency chains without deleting user choices."""
import importlib.util
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('progressor_dlc_test',Path(__file__).resolve().parents[1]/'progressor.py')
app=importlib.util.module_from_spec(spec);sys.modules[spec.name]=app;spec.loader.exec_module(app)

with tempfile.TemporaryDirectory() as folder:
    root=Path(folder); local=root/'Game/Mods'; workshop=root/'Workshop'
    local.mkdir(parents=True);workshop.mkdir()
    config=root/'Config/ModsConfig.xml';config.parent.mkdir()
    original='<ModsConfigData><version>1.7</version><activeMods><li>ludeon.rimworld</li>'+''.join(f'<li>{p}</li>' for p in app.DLC_PACKAGES)+'</activeMods></ModsConfigData>'
    config.write_text(original)
    for name, attr in [('pins','ALWAYS_ENABLED_PATH'),('disabled','DISABLED_MODS_PATH'),('metadata','LOCAL_METADATA_CACHE_PATH'),('sort','SORT_CACHE_PATH'),('settings','SETTINGS_PATH')]:setattr(app,attr,root/(name+'.json'))
    def mod(item,package,deps=(),extra=''):
        about=local/item/'About';about.mkdir(parents=True)
        (about/'About.xml').write_text('<ModMetaData><name>'+package+'</name><packageId>'+package+'</packageId><modDependencies>'+''.join(f'<li><packageId>{p}</packageId></li>' for p in deps)+'</modDependencies>'+extra+'</ModMetaData>')
    royalty='ludeon.rimworld.royalty';anomaly='ludeon.rimworld.anomaly';odyssey='ludeon.rimworld.odyssey';biotech='ludeon.rimworld.biotech'
    mod('10000001','test.direct',(royalty,))
    mod('10000002','test.transitive',('test.direct',))
    mod('10000003','test.cycle.a',('test.cycle.b',odyssey))
    mod('10000004','test.cycle.b',('test.cycle.a',))
    mod('10000005','test.optional',extra=f'<loadAfter><li>{anomaly}</li></loadAfter>')
    mod('10000006','test.anomaly',(anomaly,))
    mod('10000007','test.remembered',(anomaly,))
    mod('10000008','test.versioned',extra=f'<modDependenciesByVersion><v1.6/><v1.7><li><packageId>{biotech}</packageId></li></v1.7><v1.8><li><packageId>{odyssey}</packageId></li></v1.8></modDependenciesByVersion>')
    mod('Pinned Addon','test.pinned',(anomaly,))
    required={str(10000000+i):app.WorkshopItem('Core',str(10000000+i),'Test '+str(i)) for i in range(1,9)}
    def scan(excluded=()):return app.scan_with_required(required,workshop,local,config,lambda _:None,excluded_dlcs=set(excluded))
    initial=scan(); addon=next(i for i,p in initial.installed_package_ids.items() if p=='test.pinned')
    app.save_always_enabled_ids({'10000001',addon});pin_bytes=app.ALWAYS_ENABLED_PATH.read_bytes()
    assert not scan().dlc_exclusions
    assert '10000001' in scan().always_enabled_ids
    key_before=app.sort_cache_key(scan())
    # Leave a known requirement in the metadata cache, but remove its installed copy.
    (local/'10000007/About/About.xml').unlink()
    filtered=scan(app.DLC_PACKAGES)
    assert set(filtered.dlc_exclusions)=={'10000001','10000002','10000003','10000004','10000006','10000007','10000008',addon},filtered.dlc_exclusions
    assert '10000005' in filtered.ready_ids, 'Optional load order must not become a hard requirement'
    assert not app.download_target_ids(filtered), 'Previously known missing DLC mods must not be downloaded'
    assert not filtered.always_enabled_ids and app.ALWAYS_ENABLED_PATH.read_bytes()==pin_bytes
    assert app.sort_cache_key(filtered)!=key_before
    with patch.object(app,'rimworld_is_running',return_value=False):app.prepare_live_launch_config(filtered,lambda _:None)
    active=app.existing_active_mods(config)
    assert active==['ludeon.rimworld','test.optional'],active
    assert app.texture_optimization_paths(filtered)==[(local/'10000005').resolve()]
    assert list(config.parent.glob('*.progressor_backup_*')), 'Applying filters must retain config backup'
    assert app.ALWAYS_ENABLED_PATH.read_bytes()==pin_bytes
    config.write_text(original)
    restored=scan()
    assert {'10000001',addon} <= restored.always_enabled_ids
    # An excluded official DLC cannot leak through a stale supplied sort result.
    before=config.read_bytes()
    bad=app.SortResult(['ludeon.rimworld',royalty],0,0,0,0)
    try:app.write_mods_config(filtered,lambda _:None,bad)
    except RuntimeError as error:assert 'DLC-excluded' in str(error)
    else:raise AssertionError('Excluded DLC must be blocked before writing')
    assert config.read_bytes()==before
    # Use only the dependencies for the actual running game version.
    (root/'Game/Version.txt').write_text('1.6.9999')
    assert '10000008' not in scan([biotech]).dlc_exclusions
    (root/'Game/Version.txt').write_text('1.7.9999')
    assert '10000008' in scan([biotech]).dlc_exclusions
    assert '10000008' not in scan([odyssey]).dlc_exclusions, 'Ignore future-version requirements'
    # Each screenshot correction also works before any mod has been installed.
    for package,(item,dlc) in app.DLC_REQUIREMENT_CORRECTIONS.items():
        required[item]=app.WorkshopItem('Content',item,package)
    all_filtered=scan(app.DLC_PACKAGES)
    assert all(item in all_filtered.dlc_exclusions for item,_ in app.DLC_REQUIREMENT_CORRECTIONS.values())
    unknown='9999999999';required[unknown]=app.WorkshopItem('Content',unknown,'Unknown requirements')
    assert unknown in scan(app.DLC_PACKAGES).missing_ids, 'Never guess an unknown mod is safe to skip'
    app.save_settings({'excluded_dlcs':[anomaly,odyssey,'unrecognized'], 'exclude_cosmetics':True,'auto_update_on_launch':True})
    saved=app.load_settings();assert set(saved['excluded_dlcs'])=={anomaly,odyssey}
    assert saved['exclude_cosmetics'] and saved['auto_update_on_launch']
    for bad_value in (None,True,'anomaly',{}):assert not app.normalize_excluded_dlcs(bad_value)
print('DLC declarations, version branches, chains/cycles, optional rules, missing metadata, screenshot corrections, pins, settings, downloads, textures and config guards passed')
