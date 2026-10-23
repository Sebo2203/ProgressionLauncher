"""A verified merger can satisfy a retired pack item; unknown missing items cannot."""
import importlib.util
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch, Mock

spec = importlib.util.spec_from_file_location('progressor_merged_test', Path(__file__).resolve().parents[1]/'progressor.py')
app = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = app
spec.loader.exec_module(app)

with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    local, workshop = root/'Game/Mods', root/'Workshop'
    local.mkdir(parents=True); workshop.mkdir()
    config = root/'UserData/Config/ModsConfig.xml'
    config.parent.mkdir(parents=True)
    config.write_text('<ModsConfigData><version>1.7</version><activeMods><li>ludeon.rimworld</li><li>regrowth.botr.aspenforest</li></activeMods></ModsConfigData>')
    app.ALWAYS_ENABLED_PATH=root/'pins.json'; app.DISABLED_MODS_PATH=root/'disabled.json'
    app.LOCAL_METADATA_CACHE_PATH=root/'metadata.json'; app.SORT_CACHE_PATH=root/'sort.json'
    old_id, provider_id='2545774148','2260097569'
    provider=workshop/provider_id
    def put(path,text):
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
    put(provider/'About/About.xml','<ModMetaData><name>ReGrowth 2</name><packageId>regrowth.botr.core</packageId></ModMetaData>')
    put(provider/'loadFolders.xml','<loadFolders><v1.6><li>/</li><li>1.6</li></v1.6></loadFolders>')
    biome=provider/'1.6/Defs/BiomeDefs/Biomes_Aspen.xml'
    plants=provider/'1.6/Defs/ThingDefs_Plants/Plants_Wild_Aspen.xml'
    assembly=provider/'1.6/Assemblies/ReGrowthCore.dll'
    put(biome,'<Defs><BiomeDef><defName>RG_AspenForest</defName></BiomeDef></Defs>')
    put(plants,'<Defs>'+''.join(f'<ThingDef><defName>{name}</defName></ThingDef>' for name in ['RG_Plant_AspenGrass','RG_Plant_TreeAspenRed','RG_Plant_TreeAspenYellow'])+'</Defs>')
    put(assembly,'fixture BiomeWorker_AspenForest')
    required={old_id:app.WorkshopItem('Content',old_id,'ReGrowth 2: Aspen'),provider_id:app.WorkshopItem('Content',provider_id,'ReGrowth 2')}
    messages=[]
    scan=lambda:app.scan_with_required(required,workshop,local,config,messages.append)
    result=scan()
    assert result.merged_items=={old_id:provider_id}
    assert old_id not in result.required and not app.download_target_ids(result)
    assert old_id in required, 'Original collection snapshot must remain intact'
    assert any('Verified replacement' in m for m in messages)
    with patch.object(app,'rimworld_is_running',return_value=False):
        app.prepare_live_launch_config(result,messages.append)
    active=app.existing_active_mods(config)
    assert 'regrowth.botr.core' in active and 'regrowth.botr.aspenforest' not in active
    assert config.with_suffix('.xml.progressor_backup_'+app.timestamp()).exists() or list(config.parent.glob('*.progressor_backup_*'))

    payload=assembly.read_bytes();assembly.unlink()
    assert old_id in scan().missing_ids, 'Missing content must not satisfy merger'
    before=config.read_bytes()
    try:app.write_mods_config(result,messages.append)
    except RuntimeError as error:assert 'changed' in str(error)
    else:raise AssertionError('Recheck merged content before writing config')
    assert config.read_bytes()==before
    assembly.write_bytes(payload)
    payload=biome.read_text();biome.write_text('<broken')
    assert old_id in scan().missing_ids, 'Malformed content must block'
    biome.write_text(payload)
    app.save_disabled_ids({provider_id})
    assert old_id in scan().missing_ids, 'Disabled provider must block'
    app.save_disabled_ids(set())
    app.save_always_enabled_ids({old_id})
    assert old_id in scan().missing_ids, 'Explicit standalone pins must not be silently rewritten'
    app.save_always_enabled_ids(set())
    put(local/provider_id/'About/About.xml','<ModMetaData><packageId>regrowth.botr.core</packageId></ModMetaData>')
    assert old_id in scan().missing_ids, 'A stale preferred local copy must not borrow content from Workshop'
    (local/provider_id/'About/About.xml').unlink()
    original=config.read_text();config.write_text(original.replace('1.7','1.5'))
    assert old_id in scan().missing_ids, 'Content for another game version must not qualify'
    config.write_text(original)
    put(provider/'loadFolders.xml','<loadFolders><v1.7><li>1.7</li></v1.7><v1.6><li>1.6</li></v1.6></loadFolders>')
    assert old_id in scan().missing_ids, 'Do not use inactive version content'
    put(provider/'loadFolders.xml','<loadFolders><v1.6><li>1.6</li></v1.6></loadFolders>')

    unknown='9999999999'
    required[unknown]=app.WorkshopItem('Content',unknown,'')
    result=scan()
    assert unknown in result.missing_ids, 'Untitled unavailable items must not disappear from requirements'
    app.save_disabled_ids({unknown})
    assert unknown not in app.download_target_ids(scan()), 'Explicit exclusions must prevent downloads'
    app.save_always_enabled_ids({unknown})
    assert unknown in scan().missing_ids, 'Pins must take precedence over disabled choices'
    app.save_always_enabled_ids(set()); app.save_disabled_ids(set())
    def unavailable(ids, progress, **kwargs):
        kwargs['unavailable_out'].add(unknown)
        return {}
    with patch.object(app,'fetch_remote_update_times',side_effect=unavailable), patch.object(app,'find_or_install_steamcmd') as install:
        try:app.run_steamcmd_downloads(result,messages.append)
        except RuntimeError as error:assert unknown in str(error) and 'Steam cannot provide' in str(error)
        else:raise AssertionError('Unavailable downloads must block')
        install.assert_not_called()
    process=Mock();process.stdout=iter([f'ERROR! Download item {unknown} failed (File Not Found).\n']);process.wait.return_value=0
    with patch.object(app,'fetch_remote_update_times',return_value={}), patch.object(app,'find_or_install_steamcmd',return_value=root/'steamcmd.exe'), patch.object(app,'prepare_steamcmd_local_download_root',return_value=local), patch.object(app,'relocate_unregistered_workshop_mods'), patch.object(app.subprocess,'Popen',return_value=process) as popen:
        try:app.run_steamcmd_downloads(result,messages.append)
        except RuntimeError as error:assert 'Steam cannot provide' in str(error)
        else:raise AssertionError('File Not Found must block without a futile retry')
        assert popen.call_count==1
print('Verified merger, version/local precedence, disabled/pinned protection, config backup, unknown-item blocking and unavailable download checks passed')
