# Progression Launcher

Windows-first helper for launching Ferny's Progression RimWorld modpack.

[**Download Progression Launcher v0.4.2 for Windows**](https://sebo2203.github.io/ProgressionLauncher/?v=0.4.2)

Progression Launcher fetches Ferny's live Steam Workshop collections, compares them against your Steam Workshop folder and RimWorld local `Mods` folder, downloads missing items through SteamCMD, writes a backed-up `ModsConfig.xml`, and launches RimWorld through Steam.

## Requirements

- Windows 10 or Windows 11
- RimWorld installed through Steam
- An internet connection
- [SteamCMD](https://developer.valvesoftware.com/wiki/SteamCMD)

SteamCMD is required for downloading mods that the Steam client has not made loadable. If it is missing when a SteamCMD operation begins, Progression Launcher downloads the official Windows package directly from Valve and configures it automatically. You can also install it ahead of time with `Show Advanced Options` > `Install SteamCMD`.

You can also install SteamCMD manually:

1. Download Valve's official [`steamcmd.zip`](https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip).
2. Extract it into a permanent folder such as `C:\SteamCMD`.
3. Press `Auto Detect Paths`, or use the SteamCMD `Browse` button and select the extracted `steamcmd.exe`.

The displayed SteamCMD path should be a complete path such as:

```text
C:\SteamCMD\steamcmd.exe
```

Progression Launcher does not bundle or redistribute SteamCMD. The one-click installer downloads the current package directly from Valve so Valve remains the source of the executable and can provide its current version.

## Run

For players, the intended flow is:

1. Open Progression Launcher.
2. Press `PLAY NOW`.
3. Wait for RimWorld to launch.

Double-click:

```bat
run_progressor.bat
```

Or run:

```bat
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
```

The `Frozen Profiles` path can point to another local drive or folder. Changing it switches where profiles are listed and created; existing profiles are not moved automatically.

Typical Steam Workshop folder:

```text
C:\Program Files (x86)\Steam\steamapps\workshop\content\294100
```

Typical RimWorld local `Mods` folder:

```text
C:\Program Files (x86)\Steam\steamapps\common\RimWorld\Mods
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

Frozen profiles use a hidden shared immutable mod snapshot store inside the configured `Frozen Profiles` folder. The first profile stores each exact active mod version once. Later profiles hard-link unchanged versions from that store, preserving independent historical loadouts without consuming another full physical copy of the modpack. The confirmation distinguishes logical mod size from new shared storage actually required. Windows may still display the full logical folder size for hard-linked files even though their physical disk blocks are shared.

Removing a profile also removes stored mod versions that are no longer referenced by any remaining profile. The copied RimWorld game version and compact user data remain private to each profile.

`Play Frozen` validates every snapshotted mod with an on-screen remaining count and launches the copied historical RimWorld executable directly with RimWorld's `-savedatafolder` option pointed at the profile's private user-data folder. It does not move or modify the live setup, fetch Ferny's current collections, re-sort the profile, apply Cosmetics exclusion, or expose the copied game/mod folders to Steam Workshop updates. Frozen saves stay outside Steam Cloud's normal live save location.

Changes made during a frozen session are written directly into that profile. Normal `PLAY NOW` continues using the live user-data folder. Close RimWorld before switching sessions.

Profiles created by older launcher versions are not compatible with the full snapshot format. Remove them with `Remove Selected` and create a new profile.

The first shared snapshot can still consume many gigabytes because it must preserve the full active modpack once. Later profiles generally need only changed mod versions, another game snapshot, and their compact user data. Keep backups of important profiles on another drive; the launcher cannot protect against disk failure or manual profile deletion.

## SteamCMD Note

SteamCMD mode is supported by making SteamCMD download directly into RimWorld's local `Mods` folder through a junction:

```text
<SteamCMD>\steamapps\workshop\content\294100
```

to RimWorld's local `Mods` folder. If that SteamCMD content folder already contains old downloads, Progression Launcher moves numeric mod folders into local `Mods` and backs up any remaining folder before creating the junction.

Steam-subscribed Workshop mods are left to Steam's own update system.

SteamCMD is normally detected from the configured `STEAMCMD` environment variable, the system `PATH`, the launcher folder, the launcher's AppData installation, and common standalone, Scoop, and Chocolatey installation locations. Manually selected paths are stored as fully resolved absolute paths.

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
