# Progression Launcher

Windows and macOS helper for launching Ferny's Progression RimWorld modpack.

[**Download Progression Launcher v0.4.2 for Windows**](https://sebo2203.github.io/ProgressionLauncher/?v=0.4.2)

macOS test builds are produced by the `Build macOS` GitHub Actions workflow as an artifact named `Progression-Launcher-macOS`. See [MAC_TESTER.md](MAC_TESTER.md) for tester instructions.

Progression Launcher fetches Ferny's live Steam Workshop collections, compares them against your Steam Workshop folder and RimWorld local `Mods` folder, downloads missing items through SteamCMD, writes a backed-up `ModsConfig.xml`, and launches RimWorld through Steam.

## Requirements

- Windows 10/11 or macOS
- RimWorld installed through Steam
- An internet connection
- [SteamCMD](https://developer.valvesoftware.com/wiki/SteamCMD)

SteamCMD is required for downloading mods that the Steam client has not made loadable. If it is missing when a SteamCMD operation begins, Progression Launcher downloads the official Windows or macOS package directly from Valve and configures it automatically. You can also install it ahead of time with `Show Advanced Options` > `Install SteamCMD`.

You can also install SteamCMD manually:

1. Download Valve's official Windows [`steamcmd.zip`](https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip) or macOS [`steamcmd_osx.tar.gz`](https://steamcdn-a.akamaihd.net/client/installer/steamcmd_osx.tar.gz).
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

On macOS or from source, run:

```sh
python progressor.py
```

No third-party Python packages are required.

## Player Flow

`PLAY NOW` runs the full setup:

- scans Ferny's current Workshop collections
- checks whether mods are loadable from Steam Workshop or the local `Mods` folder
- downloads missing or non-loadable items through SteamCMD into local `Mods`
- leaves extra installed mods disabled
- keeps user-selected `Always Enabled` mods active
- activates and sorts using RimWorld-style dependency, `loadAfter`, and `loadBefore` rules
- launches RimWorld through Steam

Use `Show Advanced Options` for troubleshooting, manual paths, selecting always-enabled mods, frozen profiles, or running individual steps manually.

The mod table includes a live approximate-name search. Typing filters non-matching rows, selects the strongest match, and scrolls it into view. It also works in the `Active Load Order` view.

When frozen profiles exist, the selected profile is also available directly beneath `PLAY NOW`. The launcher remembers that selection between restarts. Hover over the adjacent `?` for a summary of the difference between live and frozen play.

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

SteamCMD mode is supported by making SteamCMD download directly into RimWorld's local `Mods` folder through a junction on Windows or a symlink on macOS:

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
outputs\dist\Progression Launcher.exe
```

To build a macOS app bundle on a Mac:

```sh
./build_macos.sh
```

The built app appears at:

```text
../dist/Progression Launcher.app
```

To run the local macOS compatibility smoke test from any development machine:

```sh
python tests/macos_compat_smoke.py
```

This simulates macOS path detection, SteamCMD extraction, SteamCMD symlink setup, frozen profile creation, and frozen launch command construction. A real Mac is still required to build and launch the final `.app`.
