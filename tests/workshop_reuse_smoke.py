"""Only an installed, matching current Steam copy can replace a stale local duplicate."""
import importlib.util
from pathlib import Path
import sys
import tempfile

spec = importlib.util.spec_from_file_location('progressor_reuse_smoke', Path(__file__).resolve().parents[1] / 'progressor.py')
app = importlib.util.module_from_spec(spec); sys.modules[spec.name] = app; spec.loader.exec_module(app)

def write_mod(root, package, content):
    (root/'About').mkdir(parents=True)
    (root/'About'/'About.xml').write_text(f'<ModMetaData><name>{package}</name><packageId>{package}</packageId></ModMetaData>')
    (root/'payload').write_text(content)

with tempfile.TemporaryDirectory() as folder:
    root=Path(folder); local=root/'Game'/'Mods'; workshop=root/'steamapps'/'workshop'/'content'/'294100'
    app.LOCAL_METADATA_CACHE_PATH=root/'metadata.json'; app.ALWAYS_ENABLED_PATH=root/'pins.json'; app.DISABLED_MODS_PATH=root/'disabled.json'
    app.app_data_dir=lambda: root/'app'
    app.rimworld_is_running=lambda: False
    for item, package in [('10000001','test.current'),('10000002','test.stale'),('10000003','test.mismatch')]:
        write_mod(local/item, package, 'old local content')
        write_mod(workshop/item, package if item!='10000003' else 'other.package', 'new Steam content')
    manifest=workshop.parents[1]/'appworkshop_294100.acf'
    manifest.write_text('''"AppWorkshop"
{
 "WorkshopItemsInstalled"
 {
  "10000001" { "timeupdated" "200" }
  "10000002" { "timeupdated" "100" }
  "10000003" { "timeupdated" "200" }
 }
 "WorkshopItemDetails"
 {
  "10000002" { "timeupdated" "200" }
 }
}
''')
    times=app.parse_workshop_update_times(manifest)
    assert times['10000002']==100, 'Metadata cache must never certify undownloaded content'
    remote={item:200 for item in ('10000001','10000002','10000003')}
    required={item:app.WorkshopItem('Core',item,item) for item in remote}
    config=root/'ModsConfig.xml'
    scan=lambda:app.scan_with_required(required,workshop,local,config,lambda _:None)
    result=scan()
    reused=app.reuse_current_workshop_copies(result,list(remote),remote,lambda _:None)
    assert reused==['10000001']
    assert not (local/'10000001').exists()
    backups=list((root/'app'/'repair_backups').glob('duplicate-local-mods-*'))
    assert len(backups)==1 and (backups[0]/'10000001'/'payload').read_text()=='old local content'
    assert (backups[0]/'restoration.json').exists()
    fresh=scan()
    assert fresh.item_paths['10000001']==workshop/'10000001'
    assert '10000001' not in app.steamcmd_update_target_ids(fresh)
    assert app.reuse_current_workshop_copies(fresh,list(remote),remote,lambda _:None)==[], 'Second launch must not repeat work'
    assert (local/'10000002').exists() and (local/'10000003').exists()
    app.rimworld_is_running=lambda:True
    manifest.write_text(manifest.read_text().replace('"10000002" { "timeupdated" "100" }','"10000002" { "timeupdated" "200" }'))
    blocked=False
    try: app.reuse_current_workshop_copies(scan(),['10000002'],remote,lambda _:None)
    except RuntimeError: blocked=True
    assert blocked and (local/'10000002').exists(), 'Never move mod folders while RimWorld is running'
print('Workshop reuse, genuine installed versions, backup preservation and no-repeat checks passed')
