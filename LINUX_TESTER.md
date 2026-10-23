# Progression Launcher v0.4.5 for Linux

Download the **x86_64** archive, extract it, and run `ProgressionLauncher/ProgressionLauncher` inside the extracted folder. Keep the executable and its `_internal` folder together.

This is an experimental build, built on Ubuntu 24.04. Other distributions and SteamOS still need real game-launch testing. On Steam Deck, use desktop mode.

SteamCMD needs your distribution's 32-bit runtime libraries, commonly `lib32gcc-s1` and `lib32stdc++6` on Debian/Ubuntu. Folder actions use `xdg-open`. The launcher can install its own SteamCMD copy without root, but it does not install system packages. Flatpak permissions may require manually selecting paths.

Please check Steam library and game/config detection, PLAY NOW, DLC exclusions, pins, undo after restarting, and frozen profiles. Close RimWorld before optimizing textures. Original PNGs and existing frozen profiles are preserved.

The build includes the native todds 0.4.1 encoder and its license. Report your distribution, desktop environment, Steam installation type, and the error from Show activity or Open logs.
