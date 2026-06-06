# Progression Launcher

Windows-first helper for launching Ferny's Progression RimWorld modpack.

[**Download Progression Launcher for Windows**](https://sebo2203.github.io/ProgressionLauncher/?v=0.3.4)

Progression Launcher fetches Ferny's live Steam Workshop collections, compares them against your Steam Workshop folder and RimWorld local `Mods` folder, downloads missing items through SteamCMD, writes a backed-up `ModsConfig.xml`, and launches RimWorld through Steam.

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

## Paths

The app auto-detects Steam libraries, RimWorld's local `Mods` folder, SteamCMD, and RimWorld's `ModsConfig.xml` on startup. You can still edit every path manually under `Show Advanced Options`.

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
- `Disable Selected`: removes selected mods from the always-enabled list.
- `Freeze Current Setup`: copies the current active setup and RimWorld config files into an independent frozen profile.
- `Play Frozen`: stages the selected frozen profile and launches RimWorld from those copied mod folders/config files.
- `Restore Live Setup`: restores live Steam/SteamCMD folders after playing a frozen profile.
- `Activate + Vanilla Sort`: backs up `ModsConfig.xml`, activates Ferny mods plus always-enabled mods, and sorts them using RimWorld-style metadata rules.
- `Launch RimWorld`: opens RimWorld through Steam.

## Frozen Profiles

Frozen profiles are independent copies of the active mod folders and RimWorld config files at the time you freeze them. They are intended for saves that should not be affected by later Workshop or SteamCMD updates.

Select a profile in the `Frozen Profile` dropdown before pressing `Play Frozen`. Use `Refresh Profiles` if a newly-created profile does not appear immediately.

When you press `Play Frozen`, Progression Launcher temporarily stages live copies of the same Workshop IDs and the live RimWorld `Config` folder away, copies the frozen profile's folders/config into place, writes `ModsConfig.xml` for that frozen profile, and launches RimWorld.

When you press normal `PLAY NOW` or `Restore Live Setup`, the launcher first saves any config changes made during the frozen session back into that frozen profile, then restores the live mod folders and live config files.

Frozen profiles use extra disk space because they keep physical copies of mods. That is the cost of making the freeze real.

## SteamCMD Note

SteamCMD mode is supported by making SteamCMD download directly into RimWorld's local `Mods` folder through a junction:

```text
<SteamCMD>\steamapps\workshop\content\294100
```

to RimWorld's local `Mods` folder. If that SteamCMD content folder already contains old downloads, Progression Launcher moves numeric mod folders into local `Mods` and backs up any remaining folder before creating the junction.

Steam-subscribed Workshop mods are left to Steam's own update system.

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
