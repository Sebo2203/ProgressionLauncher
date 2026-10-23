# Progression Launcher

Windows, macOS and Linux helper for launching Ferny's Progression RimWorld modpack.

[**Download Progression Launcher v0.4.7 for Windows**](https://github.com/Sebo2203/ProgressionLauncher/releases/download/v0.4.7/ProgressionLauncher-v0.4.7.exe)

[**Download for macOS (Apple Silicon or Intel, test builds)**](https://github.com/Sebo2203/ProgressionLauncher/releases/tag/v0.4.7-macos-test)

[**Download for Linux x86_64 (experimental)**](https://github.com/Sebo2203/ProgressionLauncher/releases/tag/v0.4.7-linux-test)

The [download page](https://sebo2203.github.io/ProgressionLauncher/) lists all three platforms. Mac and Linux packages are built and checked on native GitHub runners before publication. See [MAC_TESTER.md](MAC_TESTER.md) and [LINUX_TESTER.md](LINUX_TESTER.md) for tester instructions.

Progression Launcher fetches Ferny's live Steam Workshop collections, compares them against your Steam Workshop folder and RimWorld local `Mods` folder, downloads missing items through SteamCMD, writes a backed-up `ModsConfig.xml`, and launches RimWorld through Steam.

The next local candidate resolves seven retired Workshop uploads to corresponding editions curated in the pack or re-uploaded by their author. Once a mod's package ID is known, the launcher can also reuse a matching, loadable item from the current pack without another manual mapping. New identities cannot be inferred from a title or a missing Steam page. Unidentified unavailable entries open a review with `Cancel setup` and `Skip listed mods and continue`; skipping is saved, logged by name/ID, and undoable. A 1.6 supported-version tag alone does not reject a replacement on 1.7.

## Requirements

- Windows 10/11 x64, macOS (Intel or Apple Silicon), or Linux x86_64
- RimWorld installed through Steam
- An internet connection
- [SteamCMD](https://developer.valvesoftware.com/wiki/SteamCMD)

SteamCMD is required for downloading mods that the Steam client has not made loadable. If it is missing when a SteamCMD operation begins, Progression Launcher downloads the matching official Windows, macOS or Linux package directly from Valve and configures it automatically. You can also install it ahead of time with `Show Advanced Options` > `Locations` > `Install SteamCMD`.

Windows is verified locally. Mac and Linux builds have automated platform checks; real game-launch testing is still needed before those platforms can be considered stable. Linux support remains experimental. SteamOS uses the Linux build in desktop mode; controller and gaming-mode integration have not been tested.

You can also install SteamCMD manually:

1. Download Valve's official Windows [`steamcmd.zip`](https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip), macOS [`steamcmd_osx.tar.gz`](https://steamcdn-a.akamaihd.net/client/installer/steamcmd_osx.tar.gz), or Linux [`steamcmd_linux.tar.gz`](https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz).
2. Extract it into a permanent folder such as `C:\SteamCMD` on Windows or `~/SteamCMD` on macOS.
3. Press `Auto Detect Paths`, or use the SteamCMD `Browse` button and select the extracted `steamcmd.exe` or `steamcmd.sh`.

The displayed SteamCMD path should be a complete path such as:

```text
C:\SteamCMD\steamcmd.exe
~/SteamCMD/steamcmd.sh
```

Progression Launcher does not bundle or redistribute SteamCMD. The one-click installer downloads the current package directly from Valve so Valve remains the source of the executable and can provide its current version.

## Run

For players, the intended flow is:

1. Open Progression Launcher.
2. Press `PLAY NOW`.
3. Wait for RimWorld to launch.

Only one Progression Launcher window or version can run at a time. A newer launcher also detects older packaged releases that predate this guard and asks the player to close them before continuing. Old executable files may remain on disk safely; they are not deleted automatically.

Double-click:

```bat
run_progressor.bat
```

On macOS, Linux or from source, run:

```sh
python progressor.py
```

No third-party Python packages are required.

Linux source installs also need Tk (`python3-tk` on Debian/Ubuntu). SteamCMD requires the distribution's 32-bit runtime libraries, commonly `lib32gcc-s1` and `lib32stdc++6` on Debian/Ubuntu. The launcher installs SteamCMD in your user data folder; it does not install system packages or require root. Linux folder actions use `xdg-open`. Steam libraries, XDG paths and common Flatpak Steam locations are detected, but sandbox permissions can still require manual paths.

## Player Flow

`PLAY NOW` runs the full setup:

- scans Ferny's current Workshop collections
- checks whether mods are loadable from Steam Workshop or the local `Mods` folder
- downloads missing or non-loadable items through SteamCMD into local `Mods`
- leaves extra installed mods disabled
- keeps user-selected `Always Enabled` mods active, including named local addons
- activates and sorts using RimWorld-style dependency, `loadAfter`, and `loadBefore` rules
- launches RimWorld through Steam

Use `Show Advanced Options` for troubleshooting, manual paths, selecting always-enabled mods, frozen profiles, or running individual steps manually.

Under `Skip DLC`, check any DLC you want to leave out: Royalty, Ideology, Biotech, Anomaly, or Odyssey. The launcher remembers your choices and excludes those DLCs, mods that require them, and mods that depend on an excluded mod. Excluded mods appear as `DLC excluded` in the table. Saved pins return when you clear the filter; existing frozen profiles keep their original contents.

Known and previously read DLC requirements are skipped before downloading. A mod whose requirements are not known yet may need to download first, then is checked again before activation. The launcher also includes corrections for ten Anomaly and Odyssey mods with missing declarations.

The mod library shows the next launch's active load order beside inactive and missing mods. Select a mod to inspect its status, package ID, requirements, and folder. Use `Enable / pin`, `Disable`, or `Use pack default` to manage your overrides, then `Apply & sort` to save without launching. The active list stays in dependency order; click an inactive-list heading to sort by name, status, or pack.

The curved-arrow button beside `Use pack default` undoes your last manual pin, disable or reset action (`Ctrl+Z`, or `Ã¢Å’ËœZ` on Mac). A multi-mod change is undone together. Undo history survives restarts and preserves unrelated choices. It restores your saved overrides; `Apply & sort` writes the resulting load order. DLC and Cosmetics filters still apply.

`Show activity` records each changed mod's name, ID and previous/new state, plus settings changes and operations such as scans, downloads and launches. Recent activity is restored when the launcher reopens. Logs and the last 500 manual mod actions are saved locally under the launcher's data folder in `activity/`; routine search and selection changes are omitted. Undo does not reverse downloads, game launches, profile deletion or applied game configuration.

Search both lists by name, Workshop ID, or package ID (`Ctrl+F`; `Escape` clears). Exact matches take priority, with approximate-name matching when needed. `Needs attention` shows missing or non-loadable mods. Filtering keeps your selection when it still matches. The activity log is available through `Show activity`; paths and less-used controls stay under `Show Advanced Options` > `Locations`.

When frozen profiles exist, the selected profile is also available directly beneath `PLAY NOW`. The launcher remembers that selection between restarts. Hover over the adjacent `?` for a summary of the difference between live and frozen play.

## What is new in v0.4.7

- Respect Load Them Last's mod order before launch to avoid an unnecessary RimWorld restart.

See [CHANGELOG.md](CHANGELOG.md) for release history. Existing frozen profiles are unchanged.

Texture optimization uses the bundled [todds 0.4.1 encoder](https://github.com/todds-encoder/todds/tree/0.4.1), under the Mozilla Public License 2.0. License and source information are in `todds/`.

## Paths

The app auto-detects Steam libraries, RimWorld's local `Mods` folder, SteamCMD, and RimWorld's `ModsConfig.xml` on startup. You can still edit every path manually under `Show Advanced Options`.

Frozen profiles default to:

```text
%LOCALAPPDATA%\ProgressionLauncher\frozen_profiles
~/Library/Application Support/ProgressionLauncher/frozen_profiles
```

The `Frozen Profiles` path can point to another local drive or folder. Changing it switches where profiles are listed and created; existing profiles are not moved automatically.

Typical Steam Workshop folder:

```text
C:\Program Files (x86)\Steam\steamapps\workshop\content\294100
~/Library/Application Support/Steam/steamapps/workshop/content/294100
```

Typical RimWorld local `Mods` folder:

```text
C:\Program Files (x86)\Steam\steamapps\common\RimWorld\Mods
~/Library/Application Support/Steam/steamapps/common/RimWorld/RimWorldMac.app/Mods
```

Typical RimWorld `ModsConfig.xml` path:

```text
%USERPROFILE%\AppData\LocalLow\Ludeon Studios\RimWorld by Ludeon Studios\Config\ModsConfig.xml
~/Library/Application Support/RimWorld/Config/ModsConfig.xml
```

## Buttons

- `Scan Ferny's Pack`: fetches Steam collection contents and compares them with local folders.
- `Download Missing`: uses SteamCMD to install missing or non-loadable mods into RimWorld's local `Mods` folder.
- `Update SteamCMD Mods`: compares SteamCMD-local Ferny mods against Steam update metadata, then validates/downloads only mods with newer Workshop versions.
- `Always Enable Selected`: pins selected installed mods so they stay active even if they are not part of Ferny's pack.
- `Reset Selected`: removes the selected mods' launcher override and follows Ferny's current pack status.
- `Always Disable Selected`: keeps selected mods disabled even when they are part of Ferny's pack.
- `Install SteamCMD`: downloads the current official SteamCMD package from Valve into the launcher's AppData folder.
- `Freeze Current Setup`: lets you choose the saves to preserve, estimates the required space, then copies the active mods, game version, settings, and persistent mod data into an independent frozen profile.
- `Play Frozen`: validates and launches the selected profile with its private game, mods, and user-data folder.
- `Remove Selected`: permanently deletes the selected frozen profile and its copied game, mods, settings, and saves.
- `Remove Incomplete Copies`: finds temporary `.creating_*` folders left behind by interrupted freezes, reports their combined size, and removes them after confirmation.
- `Apply Mod List + Sort`: backs up `ModsConfig.xml`, applies Ferny mods plus your always-enabled/disabled choices, and sorts them using RimWorld-style metadata rules.
- `Launch RimWorld`: opens RimWorld through Steam.

## Frozen Profiles

New frozen profiles are self-contained historical snapshots intended for saves that must survive later pack, mod, configuration, and RimWorld updates. A compact profile copies:

- the exact mods active in `ModsConfig.xml`, in that saved load order
- the current RimWorld game files and DLC data
- the saves selected during profile creation and their matching `.old` backups
- settings, scenarios, ideologies, xenotypes, presets, and ordinary mod-owned persistent data

Known disposable data is excluded: unrelated saves and backups, logs, RealRuins downloads, RocketMan data, MissileGirl cache data, startup-impact data, and developer output. The launcher shows estimated game, mod, and compact user-data sizes plus destination free space before copying.

Frozen profiles use a hidden shared immutable mod snapshot store inside the configured `Frozen Profiles` folder. Mod files are stored by content, so identical files are shared even when they occur in different mods or different mod versions. Profiles and version snapshots hard-link those stored files, preserving independent historical loadouts without consuming another physical copy of unchanged content.

On Windows, the immutable mod store also uses transparent NTFS compression when supported. RimWorld reads these as ordinary files, so `Play Frozen` does not need an archive extraction or staging step. Existing full frozen profiles are migrated into the content-addressed store when another profile is created; this reconstructs a manually removed store and deduplicates existing files without changing their contents.

The confirmation distinguishes logical mod size from new shared storage actually required. Windows may still display the full logical folder size for hard-linked files even though their physical disk blocks are shared.

Removing a profile also removes stored mod versions that are no longer referenced by any remaining profile. The copied RimWorld game version and compact user data remain private to each profile.

`Play Frozen` validates every snapshotted mod with an on-screen remaining count and launches the copied historical RimWorld executable directly with RimWorld's `-savedatafolder` option pointed at the profile's private user-data folder. It does not move or modify the live setup, fetch Ferny's current collections, re-sort the profile, apply Cosmetics exclusion, or expose the copied game/mod folders to Steam Workshop updates. Frozen saves stay outside Steam Cloud's normal live save location.

Changes made during a frozen session are written directly into that profile. Normal `PLAY NOW` continues using the live user-data folder. Close RimWorld before switching sessions.

Very old legacy profiles that did not include a complete game, mod, and user-data snapshot are not compatible with the current full snapshot format. Full snapshot profiles remain playable and can be migrated to the newer deduplicated storage.

The first shared snapshot can still consume many gigabytes because it must preserve the full active modpack once. Compression depends on the file types: XML and other uncompressed data shrink well, while textures and audio that are already compressed may not. Later profiles generally need only genuinely new file content, another game snapshot, and their compact user data. Keep backups of important profiles on another drive; the launcher cannot protect against disk failure or manual profile deletion.

## SteamCMD Note

SteamCMD mode is supported by making SteamCMD download directly into RimWorld's local `Mods` folder through a junction on Windows or a symlink on macOS/Linux:

```text
<SteamCMD>\steamapps\workshop\content\294100
<SteamCMD>/steamapps/workshop/content/294100
```

to RimWorld's local `Mods` folder. If that SteamCMD content folder already contains old downloads, Progression Launcher moves numeric mod folders into local `Mods` and backs up any remaining folder before creating the redirect.

Steam-subscribed Workshop mods are left to Steam's own update system.

SteamCMD is normally detected from the configured `STEAMCMD` environment variable, the system `PATH`, the launcher folder, the launcher's app-data installation, and common standalone locations. On Windows it also checks Scoop and Chocolatey locations; on macOS it checks common Homebrew paths. Manually selected paths are stored as fully resolved absolute paths.

## Safety

`Write ModsConfig` creates a backup next to the original file before writing:

```text
ModsConfig.xml.progressor_backup_YYYYMMDD_HHMMSS
```

Progression Launcher does not delete extra mods. It simply leaves non-Ferny extras out of `ModsConfig.xml` unless you mark them as always enabled.

## Distribution

To build a single-file Windows executable:

```bat
build_exe.bat
```

The built app appears at:

```text
dist\ProgressionLauncher-v0.4.7.exe
```

To build a macOS app bundle on a Mac:

```sh
./build_macos.sh
```

The built app appears at:

```text
dist/Progression Launcher.app
```

To run the local macOS compatibility smoke test from any development machine:

```sh
python tests/macos_compat_smoke.py
```

This simulates macOS path detection, SteamCMD extraction, SteamCMD symlink setup, frozen profile creation, and frozen launch command construction. A real Mac is still required to build and launch the final `.app`.

To build the Linux x86_64 bundle on Linux:

```sh
bash build_linux.sh
```

The build downloads a checksum-verified native texture encoder and creates `dist/ProgressionLauncher-Linux-v<version>-x86_64-test.tar.gz`. Extract the archive and run `ProgressionLauncher/ProgressionLauncher`. Build on Ubuntu 24.04 for the baseline used by the Linux workflow; other distributions still need validation.

Run all regression scripts with `python tests/run_smoke.py`. On headless Linux, use `xvfb-run -a python tests/run_smoke.py`. The non-Windows texture check needs its native encoder (`python tests/fetch_native_encoder.py`). `tests/linux_compat_smoke.py` can also simulate Linux-specific behavior from Windows; that does not replace native testing. GitHub checks now target Windows, both Mac architectures and Linux.
