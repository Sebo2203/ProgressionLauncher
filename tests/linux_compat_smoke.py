"""Exercise Linux platform behavior without Steam, network, or launching the game."""
import importlib.util
import io
import os
from pathlib import Path
import sys
import tarfile
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('launcher_linux_test', Path(__file__).resolve().parents[1] / 'progressor.py')
app = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = app
spec.loader.exec_module(app)
host_platform = sys.platform

with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    home = root / 'Home'
    home.mkdir()
    with patch.object(app.sys, 'platform', 'linux'), patch.object(Path, 'home', return_value=home), patch.dict(os.environ, {'XDG_DATA_HOME': str(home / 'Data'), 'XDG_CONFIG_HOME': str(home / 'Config'), 'STEAMCMD': ''}), patch.object(app.shutil, 'which', return_value=None):
        assert app.app_data_dir() == home / 'Data/ProgressionLauncher'
        for attr in ('SETTINGS_PATH', 'ALWAYS_ENABLED_PATH', 'DISABLED_MODS_PATH', 'LOCAL_METADATA_CACHE_PATH', 'SORT_CACHE_PATH'):
            setattr(app, attr, root / (attr + '.json'))
        app.configure_frozen_profiles_path(root / 'Frozen')
        steam = home / 'Data/Steam'
        (steam / 'steamapps').mkdir(parents=True)
        library = root / 'External Library'
        library.mkdir()
        (steam / 'steamapps/libraryfolders.vdf').write_text('"libraryfolders" { "0" { "path" "' + str(library).replace('\\', '\\\\') + '" } }')
        game = library / 'steamapps/common/RimWorld'
        mods = game / 'Mods'
        about = mods / '11111111/About'
        about.mkdir(parents=True)
        (about / 'About.xml').write_text('<ModMetaData><name>Linux Mod</name><packageId>linux.fixture</packageId></ModMetaData>')
        executable = game / 'RimWorldLinux.x86_64'
        executable.write_text('#!/bin/sh\nexit 0\n')
        executable.chmod(0o755)
        workshop = library / 'steamapps/workshop/content/294100'
        workshop.mkdir(parents=True)
        config = home / 'Config/unity3d/Ludeon Studios/RimWorld by Ludeon Studios/Config/ModsConfig.xml'
        config.parent.mkdir(parents=True)
        config.write_text('<ModsConfigData><version>1.7</version><activeMods><li>ludeon.rimworld</li><li>linux.fixture</li></activeMods></ModsConfigData>')
        saves = config.parent.parent / 'Saves'
        saves.mkdir()
        (saves / 'Linux Colony.rws').write_text('fixture save')
        assert app.default_workshop_path() == workshop
        assert app.default_rimworld_mods_path() == mods
        assert app.default_mods_config_path() == config
        assert app.rimworld_executable(game) == executable
        for name in ('RimWorld', 'RimWorldLinux'):
            variant = root / name
            variant.mkdir()
            (variant / name).write_text('fixture')
            assert app.rimworld_executable(variant) == variant / name
        flatpak = home / '.var/app/com.valvesoftware.Steam/.local/share/Steam'
        flatpak.mkdir(parents=True)
        assert flatpak in app.steam_root_candidates()
        assert all(not str(path).endswith('.exe') for path in app.steamcmd_candidates())

        payload = io.BytesIO()
        with tarfile.open(fileobj=payload, mode='w:gz') as archive:
            script = b'#!/bin/sh\nexit 0\n'
            member = tarfile.TarInfo('steamcmd.sh')
            member.mode = 0o755
            member.size = len(script)
            archive.addfile(member, io.BytesIO(script))
        with patch.object(app.urllib.request, 'urlopen', return_value=io.BytesIO(payload.getvalue())) as download:
            steamcmd = app.install_steamcmd(lambda _: None)
            assert download.call_args.args[0].full_url.endswith('steamcmd_linux.tar.gz')
        assert app.resolved_executable_path(steamcmd.parent) == steamcmd
        assert app.find_steamcmd() == steamcmd
        with patch.object(app, 'find_steamcmd', return_value=Path('/usr/games/steamcmd')):
            assert app.find_or_install_steamcmd(lambda _: None) == steamcmd, 'Distribution wrappers must use a predictable writable root'
        if host_platform == 'win32':
            calls = []
            def link(path, target, target_is_directory=False):
                calls.append((target, target_is_directory))
                path.mkdir()
            with patch.object(type(root), 'symlink_to', link):
                app.prepare_steamcmd_local_download_root(steamcmd.parent, mods, lambda _: None)
            assert calls == [(mods.resolve(), True)]
        else:
            redirect = app.prepare_steamcmd_local_download_root(steamcmd.parent, mods, lambda _: None)
            assert redirect.is_symlink() and redirect.resolve() == mods.resolve()
        with patch.object(app.subprocess, 'run', return_value=SimpleNamespace(stdout=f'{os.getpid()}\n12345678\n')) as pgrep:
            assert app.rimworld_is_running()
            assert pgrep.call_args.args[0][:2] == ['pgrep', '-if']
        with patch.object(app.subprocess, 'run', return_value=SimpleNamespace(stdout=f'{os.getpid()}\n')):
            assert not app.rimworld_is_running()
        required = {'11111111': app.WorkshopItem('Core', '11111111', 'Linux Mod')}
        result = app.scan_with_required(required, workshop, mods, config, lambda _: None)
        plans = app.plan_mod_snapshots(result, ['11111111'])
        profile = app.create_frozen_profile(result, 'Linux test', ['Linux Colony.rws'], plans, lambda _: None)
        staged = app.stage_frozen_profile('Linux test', lambda _: None)
        assert staged.executable_path.name == executable.name
        assert staged.executable_path.is_file() and (profile / 'Game/Mods/11111111/About/About.xml').is_file()
        with patch.object(app.subprocess, 'Popen') as launch:
            app.launch_frozen_game(staged.executable_path, staged.user_data_path, lambda _: None)
            assert launch.call_args.args[0] == [str(staged.executable_path), '-savedatafolder=' + str(staged.user_data_path)]
            app.open_folder(mods)
            assert launch.call_args.args[0] == ['xdg-open', str(mods)]
    with patch.object(app.sys, 'platform', 'darwin'), patch.object(app.subprocess, 'Popen') as launch:
        app.open_folder(root)
        assert launch.call_args.args[0] == ['open', str(root)]
print('Linux Steam/XDG/Flatpak paths, SteamCMD archive and redirect, wrapper handling, process guard, executables, frozen profiles and folder actions passed')
