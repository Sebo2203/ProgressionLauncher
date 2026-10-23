"""Check list identity, selection and filtering using real withdrawn Tk widgets."""
import importlib.util
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('launcher_ui_test', Path(__file__).resolve().parents[1] / 'progressor.py')
app = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = app
spec.loader.exec_module(app)

with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    for attr in ('SETTINGS_PATH', 'ALWAYS_ENABLED_PATH', 'DISABLED_MODS_PATH', 'LOCAL_METADATA_CACHE_PATH', 'SORT_CACHE_PATH', 'ACTION_HISTORY_PATH', 'ACTIVITY_LOG_PATH'):
        setattr(app, attr, root / (attr + '.json'))
    local, workshop, config = root / 'Game/Mods', root / 'Workshop', root / 'Config/ModsConfig.xml'
    local.mkdir(parents=True)
    workshop.mkdir()
    config.parent.mkdir()
    config.write_text('<ModsConfigData><version>1.7</version><activeMods><li>ludeon.rimworld</li></activeMods></ModsConfigData>')
    required = {}
    for number, name, dependency in ((10000001, 'Harmony', ''), (10000002, 'Vanilla Expanded Framework', ''), (10000003, 'Anomaly Retexture', 'ludeon.rimworld.anomaly'), (10000004, 'Extra Local Mod', '')):
        about = local / str(number) / 'About'
        about.mkdir(parents=True)
        (about / 'About.xml').write_text(f'<ModMetaData><name>{name}</name><packageId>test.mod{number}</packageId><modDependencies><li><packageId>{dependency}</packageId></li></modDependencies></ModMetaData>')
        if number != 10000004: required[str(number)] = app.WorkshopItem('Core', str(number), name)
    required['9999999999'] = app.WorkshopItem('Content', '9999999999', 'Missing Workshop Mod')
    app.save_settings({'workshop_path': str(workshop), 'local_mods_path': str(local), 'mods_config_path': str(config), 'frozen_profiles_path': str(root / 'Frozen')})
    errors = []
    with patch.object(app.ProgressorApp, 'load_installed_on_startup'), patch.object(app, 'frozen_profile_names', return_value=[]):
        ui = app.ProgressorApp()
        ui.withdraw()
        ui.report_callback_exception = lambda *error: errors.append(error)
        result = app.scan_with_required(required, workshop, local, config, lambda _: None, excluded_dlcs={'ludeon.rimworld.anomaly'})
        ui.current_result = result
        ui.render_result(result)
        ui.update()
        assert len(ui.tree.get_children()) == 3, 'Game plus two eligible mods'
        assert len(ui.inactive_tree.get_children()) == 3, 'Extra, missing and DLC excluded'
        iid = 'active:10000002'
        ui.tree.selection_set(iid)
        ui.mod_selection_changed(ui.tree)
        ui.update()
        assert ui.detail_title.get() == 'Vanilla Expanded Framework'
        assert ui.selected_item_ids() == {'10000002'}
        assert ui.tree.item(iid, 'values')[1] == 'Vanilla Expanded Framework', 'Names must lead instead of Workshop IDs'
        before_ids = ui.tree.get_children()
        ui.apply_mod_filters()
        ui.update()
        assert ui.tree.get_children() == before_ids
        assert ui.selected_item_ids() == {'10000002'}, 'Refresh must retain selection'
        ui.mod_search.set('test.mod10000002')
        ui.apply_mod_filters()
        assert ui.tree.get_children() == (iid,), 'Search package IDs too'
        ui.clear_mod_search()
        ui.state_filter.set('Needs attention')
        ui.apply_mod_filters()
        assert not ui.tree.get_children()
        assert ui.inactive_tree.get_children() == ('inactive:9999999999',)
        ui.state_filter.set('DLC excluded')
        ui.apply_mod_filters()
        assert ui.inactive_tree.get_children() == ('inactive:10000003',)
        ui.state_filter.set('All states')
        ui.apply_mod_filters()
        ui.sort_inactive_mods('title')
        assert ui.mod_row_name(ui.row_records[ui.inactive_tree.get_children()[0]]) == 'Anomaly Retexture'
        ui.sort_inactive_mods('title')
        assert ui.mod_row_name(ui.row_records[ui.inactive_tree.get_children()[0]]) == 'Missing Workshop Mod'
        ui.inactive_tree.selection_set('inactive:10000004')
        ui.mod_selection_changed(ui.inactive_tree)
        ui.update()
        ui.always_enable_selected()
        ui.update()
        assert ui.selected_tree is ui.tree
        assert ui.selected_item_ids() == {'10000004'}, 'A pin moving to Active must stay selected'
        assert ui.detail_title.get() == 'Extra Local Mod'
        assert ui.tree.item('active:10000004', 'values')[2] == 'Pinned'
        ui.disable_selected()
        ui.update()
        assert ui.selected_tree is ui.inactive_tree
        assert ui.selected_item_ids() == {'10000004'}, 'Disabled selection moves to Inactive'
        ui.reset_selected()
        ui.update()
        assert not app.load_always_enabled_ids() and not app.load_disabled_ids()
        assert len(app.load_action_history()) == 3
        assert ui.undo_button.enabled
        ui.undo_button.invoke()
        assert app.load_disabled_ids() == {'10000004'}, 'Undo reset restores Disabled'
        ui.undo_last_mod_change()
        assert app.load_always_enabled_ids() == {'10000004'}, 'Undo disable restores Pinned'
        ui.undo_last_mod_change()
        assert not app.load_always_enabled_ids() and not app.load_disabled_ids()
        assert not ui.undo_button.enabled
        ui.change_mod_overrides({'10000001', '10000002'}, 'pinned', 'Enable / pin')
        assert len(app.latest_undoable_change()['mods']) == 2, 'Multi-selection is one undo action'
        app.save_always_enabled_ids({'10000001', '10000002', '77777777'})
        ui.undo_last_mod_change()
        assert app.load_always_enabled_ids() == {'77777777'}, 'Undo must preserve unrelated choices'
        app.save_always_enabled_ids(set())
        ui.change_mod_overrides({'10000001'}, 'pinned', 'Enable / pin')
        app.save_always_enabled_ids(set())
        ui.update_undo_button()
        assert not ui.undo_button.enabled, 'Conflicting external changes disable undo'
        ui.undo_last_mod_change()
        assert not app.load_always_enabled_ids(), 'Conflict must not overwrite current choices'
        app.save_always_enabled_ids({'10000001'})
        ui.undo_last_mod_change()
        assert not app.load_always_enabled_ids()
        history_size = len(app.load_action_history())
        ui.change_mod_overrides({'10000001'}, 'default', 'Use pack default')
        assert len(app.load_action_history()) == history_size, 'No-op must not consume an undo slot'
        prior_files = {path: path.read_bytes() for path in (app.ALWAYS_ENABLED_PATH, app.DISABLED_MODS_PATH, app.ACTION_HISTORY_PATH)}
        with patch.object(app, 'save_disabled_ids', side_effect=OSError('test save failure')):
            try: app.commit_mod_choices({'10000001'}, set(), {'kind': 'mods', 'id': 'failure', 'mods': []})
            except OSError: pass
            else: raise AssertionError('Expected save failure')
        assert all(path.read_bytes() == data for path, data in prior_files.items()), 'Failed save must roll back overrides and history'
        ui.update()
        log = app.ACTIVITY_LOG_PATH.read_text(encoding='utf-8')
        assert 'Extra Local Mod (10000004)' in log and 'Pinned → Disabled' in log and 'Undo:' in log
        ui.mod_search.set('nothingmatchesxyz')
        ui.apply_mod_filters()
        assert not ui.tree.get_children() and not ui.inactive_tree.get_children()
        assert 'No matches' in ui.table_title.get()
        assert not ui.selected_item_ids(), 'Search must not choose a different mod automatically'
        ui.clear_mod_search()
        panes = ui.main_pane.panes()
        ui.toggle_advanced()
        ui.toggle_advanced()
        assert ui.main_pane.panes() == panes, 'Mod library stays available when settings are closed'
        ui.toggle_activity()
        ui.toggle_activity()
        assert not ui.log_visible
        ui.geometry('1280x680')
        ui.deiconify()
        ui.update()
        assert ui.winfo_reqwidth() <= 1280, 'Default layout must fit the minimum window width'
        assert ui.tree.winfo_height() > 200 and ui.inactive_tree.winfo_height() > 200
        ui.withdraw()
        ui.set_busy('Checking mods')
        assert all(str(b['state']) == 'disabled' for b in ui.selection_buttons)
        assert not ui.undo_button.enabled
        ui.clear_busy()
        ui.update()
        assert not errors, errors
        ui.change_mod_overrides({'10000004'}, 'pinned', 'Enable / pin')
        ui.update()
        ui.destroy()
        restarted = app.ProgressorApp()
        restarted.withdraw()
        assert restarted.undo_button.enabled, 'Undo survives restart'
        assert 'Extra Local Mod (10000004)' in restarted.status.get('1.0', 'end'), 'Activity survives restart'
        restarted.undo_last_mod_change()
        assert not app.load_always_enabled_ids()
        restarted.destroy()
print('Dual lists, stable identities, selection moves, name/package search, attention/DLC filters, pins/defaults, settings, log and busy controls passed')
