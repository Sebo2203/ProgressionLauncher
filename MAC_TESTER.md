# Progression Launcher macOS Tester Notes

Thank you for testing the macOS build.

## What to Download

Download the GitHub Actions artifact named:

```text
Progression-Launcher-macOS
```

Inside it, open:

```text
Progression Launcher macOS.zip
```

Extract it, then open:

```text
Progression Launcher.app
```

The app is ad-hoc signed but not Apple-notarized. macOS may block the first launch. If that happens, right-click the app, choose `Open`, then confirm.

## Expected First Test

1. Close RimWorld.
2. Open `Progression Launcher.app`.
3. Press `PLAY NOW`.
4. Report whether it detects:
   - Steam Workshop mods
   - RimWorld local `Mods`
   - `ModsConfig.xml`
   - SteamCMD, or installs SteamCMD automatically
5. Let it download missing mods if needed.
6. Confirm RimWorld launches and sees the activated mod list.

## Expected macOS Paths

Typical Steam Workshop path:

```text
~/Library/Application Support/Steam/steamapps/workshop/content/294100
```

Typical RimWorld local mods path:

```text
~/Library/Application Support/Steam/steamapps/common/RimWorld/RimWorldMac.app/Mods
```

Typical ModsConfig path:

```text
~/Library/Application Support/RimWorld/Config/ModsConfig.xml
```

Launcher data path:

```text
~/Library/Application Support/ProgressionLauncher
```

## What to Report Back

Please send:

- A screenshot of the launcher after `PLAY NOW` finishes or fails.
- The last 20-40 lines from the Status panel.
- Whether SteamCMD auto-installed or required manual selection.
- Whether RimWorld launched.
- Whether the mod list inside RimWorld matches the launcher’s active load order.

## Known Caveat

This is an unsigned/not-notarized test build. Security prompts on first launch are expected and do not by themselves mean the launcher failed.
