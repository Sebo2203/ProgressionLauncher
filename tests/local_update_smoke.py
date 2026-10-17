"""Regression: Steam's current copy must not certify an untracked local copy."""
import importlib.util
from pathlib import Path
import sys
import tempfile

spec = importlib.util.spec_from_file_location('progressor_update_smoke', Path(__file__).resolve().parents[1] / 'progressor.py')
app = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = app
spec.loader.exec_module(app)

with tempfile.TemporaryDirectory() as folder:
    manifest = Path(folder) / 'appworkshop_294100.acf'
    manifest.write_text('''"WorkshopItemsInstalled"
{
    "10000001"
    {
        "timeupdated" "100"
    }
    "10000002"
    {
        "timeupdated" "200"
    }
}
''')
    ids = ['10000001', '10000002', '2009463077', '10000004']
    remote = {'10000001': 200, '10000002': 200, '2009463077': 200}
    assert app.workshop_outdated_ids(ids, manifest, remote, refresh_untracked=True) == (
        ['10000001', '2009463077'], ['10000004'])
    assert app.workshop_outdated_ids(ids, manifest, remote) == (
        ['10000001'], ['2009463077', '10000004'])
    assert app.workshop_outdated_ids(['2009463077'], Path(folder)/'missing.acf', remote, refresh_untracked=True) == (
        ['2009463077'], [])
print('Local update regression checks passed')
