from __future__ import annotations

import datetime as _dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from tkinter import BooleanVar, filedialog, messagebox, simpledialog, ttk
import tkinter as tk


APP_ID = "294100"
APP_NAME = "Progression Launcher"
COLLECTIONS = {
    "Core": "3521297585",
    "Content": "3521319712",
    "Cosmetics": "3637541646",
}

WORKSHOP_URL = "https://steamcommunity.com/sharedfiles/filedetails/?id={id}"
COLLECTION_DETAILS_URL = "https://api.steampowered.com/ISteamRemoteStorage/GetCollectionDetails/v1/"
PUBLISHED_FILE_DETAILS_URL = "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"
STEAM_RUN_RIMWORLD = "steam://rungameid/294100"
STEAM_COLLECTION_URL = "steam://url/CommunityFilePage/{id}"


def app_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Local"
    path = root / "ProgressionLauncher"
    path.mkdir(parents=True, exist_ok=True)
    return path


def asset_path(name: str) -> Path:
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    return bundle_root / name


CACHE_PATH = app_data_dir() / "collection_cache.json"
BUNDLED_CACHE_PATH = asset_path("collection_cache.json")
ALWAYS_ENABLED_PATH = app_data_dir() / "always_enabled.json"
FROZEN_PROFILES_PATH = app_data_dir() / "frozen_profiles"
STAGING_STATE_PATH = app_data_dir() / "staging_state.json"


@dataclass(frozen=True)
class WorkshopItem:
    collection: str
    item_id: str
    title: str = ""


@dataclass
class ScanResult:
    required: dict[str, WorkshopItem]
    required_order: list[str]
    installed_ids: set[str]
    installed_package_ids: dict[str, str]
    item_paths: dict[str, Path]
    local_steamcmd_ids: set[str]
    steam_registered_ids: set[str]
    missing_ids: list[str]
    unregistered_ids: list[str]
    extra_ids: list[str]
    ready_ids: list[str]
    always_enabled_ids: set[str]
    workshop_path: Path
    local_mods_path: Path
    mods_config_path: Path


@dataclass(frozen=True)
class QuarantinedMod:
    item_id: str
    quarantine_path: Path
    mod_path: Path
    package_id: str = ""


@dataclass(frozen=True)
class ModMetadata:
    item_id: str
    package_id: str
    name: str
    dependencies: tuple[str, ...]
    load_after: tuple[str, ...]
    load_before: tuple[str, ...]


@dataclass(frozen=True)
class SortResult:
    package_ids: list[str]
    metadata_count: int
    dependency_edges: int
    load_rule_edges: int
    broken_edges: int


def steam_root_candidates() -> list[Path]:
    candidates = [
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Steam",
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Steam",
    ]
    seen: set[Path] = set()
    unique: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve() if candidate.exists() else candidate
        if resolved not in seen:
            seen.add(resolved)
            unique.append(candidate)
    return unique


def steam_library_paths() -> list[Path]:
    libraries: list[Path] = []
    for steam_root in steam_root_candidates():
        if steam_root.exists():
            libraries.append(steam_root)
        library_file = steam_root / "steamapps" / "libraryfolders.vdf"
        if not library_file.exists():
            library_file = steam_root / "config" / "libraryfolders.vdf"
        if not library_file.exists():
            continue
        try:
            text = library_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for raw_path in re.findall(r'"path"\s*"([^"]+)"', text):
            path = Path(raw_path.replace("\\\\", "\\"))
            if path.exists():
                libraries.append(path)
    seen: set[Path] = set()
    unique: list[Path] = []
    for library in libraries:
        resolved = library.resolve() if library.exists() else library
        if resolved not in seen:
            seen.add(resolved)
            unique.append(library)
    return unique


def default_workshop_path() -> Path:
    candidates = [library / "steamapps" / "workshop" / "content" / APP_ID for library in steam_library_paths()]
    if not candidates:
        candidates = [
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Steam" / "steamapps" / "workshop" / "content" / APP_ID,
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Steam" / "steamapps" / "workshop" / "content" / APP_ID,
        ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def default_mods_config_path() -> Path:
    return (
        Path.home()
        / "AppData"
        / "LocalLow"
        / "Ludeon Studios"
        / "RimWorld by Ludeon Studios"
        / "Config"
        / "ModsConfig.xml"
    )


def default_rimworld_mods_path() -> Path:
    candidates = [library / "steamapps" / "common" / "RimWorld" / "Mods" for library in steam_library_paths()]
    if not candidates:
        candidates = [
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Steam" / "steamapps" / "common" / "RimWorld" / "Mods",
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Steam" / "steamapps" / "common" / "RimWorld" / "Mods",
        ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def find_steamcmd() -> Path | None:
    env_path = os.environ.get("STEAMCMD")
    candidates = []
    if env_path:
        candidates.append(Path(env_path))
    which = shutil.which("steamcmd") or shutil.which("steamcmd.exe")
    if which:
        candidates.append(Path(which))
    candidates.extend(
        [
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Steam" / "steamcmd.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Steam" / "steam" / "steamcmd.exe",
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Steam" / "steamcmd.exe",
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Steam" / "steam" / "steamcmd.exe",
            Path(r"C:\steamcmd\steamcmd.exe"),
            Path.cwd() / "steamcmd.exe",
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def rimworld_is_running() -> bool:
    if sys.platform != "win32":
        return False
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq RimWorld*.exe", "/FO", "CSV"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return "RimWorld" in result.stdout


def fetch_url(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 ProgressionLauncher/0.1",
            "Accept-Language": "en-US,en;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def post_steam_api(url: str, params: dict[str, str]) -> dict:
    data = urllib.parse.urlencode(params).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "User-Agent": "Mozilla/5.0 ProgressionLauncher/0.2",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def fetch_remote_update_times(item_ids: list[str], progress) -> dict[str, int]:
    update_times: dict[str, int] = {}
    for index in range(0, len(item_ids), 100):
        batch = item_ids[index : index + 100]
        params = {"itemcount": str(len(batch))}
        for batch_index, item_id in enumerate(batch):
            params[f"publishedfileids[{batch_index}]"] = item_id
        progress(f"Checking Steam update metadata for {len(batch)} mod(s)...")
        published_response = post_steam_api(PUBLISHED_FILE_DETAILS_URL, params)
        file_details = published_response.get("response", {}).get("publishedfiledetails", [])
        for detail in file_details:
            item_id = str(detail.get("publishedfileid", ""))
            if int(detail.get("result", 0)) != 1:
                continue
            raw_time = detail.get("time_updated") or detail.get("timeupdated") or 0
            try:
                update_times[item_id] = int(raw_time)
            except (TypeError, ValueError):
                continue
        time.sleep(0.2)
    return update_times


def html_unescape(text: str) -> str:
    replacements = {
        "&amp;": "&",
        "&quot;": '"',
        "&#39;": "'",
        "&lt;": "<",
        "&gt;": ">",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def fetch_collection_items_api(collection_name: str, collection_id: str) -> list[WorkshopItem]:
    collection_response = post_steam_api(
        COLLECTION_DETAILS_URL,
        {"collectioncount": "1", "publishedfileids[0]": collection_id},
    )
    details = collection_response.get("response", {}).get("collectiondetails", [])
    if not details:
        raise RuntimeError(f"Steam returned no collection details for {collection_name}.")
    children = details[0].get("children", [])
    child_ids = [
        str(child.get("publishedfileid", "")).strip()
        for child in children
        if str(child.get("publishedfileid", "")).strip().isdigit() and int(child.get("filetype", 0)) == 0
    ]
    if not child_ids:
        raise RuntimeError(f"Steam returned no Workshop children for {collection_name}.")

    items: list[WorkshopItem] = []
    titles: dict[str, str] = {}
    for index in range(0, len(child_ids), 100):
        batch = child_ids[index : index + 100]
        params = {"itemcount": str(len(batch))}
        for batch_index, item_id in enumerate(batch):
            params[f"publishedfileids[{batch_index}]"] = item_id
        published_response = post_steam_api(PUBLISHED_FILE_DETAILS_URL, params)
        file_details = published_response.get("response", {}).get("publishedfiledetails", [])
        for detail in file_details:
            item_id = str(detail.get("publishedfileid", ""))
            if int(detail.get("result", 0)) == 1 and int(detail.get("consumer_app_id", 0)) == int(APP_ID):
                titles[item_id] = str(detail.get("title", "")).strip()
        time.sleep(0.2)
    for item_id in child_ids:
        items.append(WorkshopItem(collection_name, item_id, titles.get(item_id, "")))
    return items


def parse_collection_items(collection_name: str, collection_id: str, html: str) -> list[WorkshopItem]:
    items: list[WorkshopItem] = []
    seen: set[str] = set()
    pattern = re.compile(
        r'id="sharedfile_(?P<id>\d+)".*?<div class="workshopItemTitle">(?P<title>.*?)</div>',
        re.DOTALL,
    )
    for match in pattern.finditer(html):
        item_id = match.group("id")
        if item_id in seen:
            continue
        title = re.sub(r"\s+", " ", match.group("title")).strip()
        title = html_unescape(re.sub(r"<.*?>", "", title))
        items.append(WorkshopItem(collection_name, item_id, title))
        seen.add(item_id)
    return items


def load_collection_cache() -> dict[str, WorkshopItem]:
    cache_path = CACHE_PATH if CACHE_PATH.exists() else BUNDLED_CACHE_PATH
    if not cache_path.exists():
        return {}
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    items: dict[str, WorkshopItem] = {}
    for entry in cached.get("items", []):
        item_id = str(entry.get("item_id", ""))
        if item_id.isdigit():
            items[item_id] = WorkshopItem(
                str(entry.get("collection", "")),
                item_id,
                str(entry.get("title", "")),
            )
    return items


def save_collection_cache(items: dict[str, WorkshopItem]) -> None:
    payload = {
        "updated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "items": [
            {"collection": item.collection, "item_id": item.item_id, "title": item.title}
            for item in items.values()
        ],
    }
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_always_enabled_ids() -> set[str]:
    if not ALWAYS_ENABLED_PATH.exists():
        return set()
    try:
        payload = json.loads(ALWAYS_ENABLED_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    ids = payload.get("item_ids", [])
    return {str(item_id) for item_id in ids if str(item_id).isdigit()}


def save_always_enabled_ids(item_ids: set[str]) -> None:
    ALWAYS_ENABLED_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"item_ids": sorted(item_ids, key=int)}
    ALWAYS_ENABLED_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def safe_profile_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_. -]+", "", name).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:80]


def frozen_profile_names() -> list[str]:
    if not FROZEN_PROFILES_PATH.exists():
        return []
    return sorted(
        [child.name for child in FROZEN_PROFILES_PATH.iterdir() if child.is_dir() and (child / "manifest.json").exists()],
        key=str.lower,
    )


def frozen_profile_path(profile_name: str) -> Path:
    return FROZEN_PROFILES_PATH / profile_name


def frozen_config_path(profile_name: str) -> Path:
    return frozen_profile_path(profile_name) / "Config"


def load_frozen_manifest(profile_name: str) -> dict:
    manifest_path = frozen_profile_path(profile_name) / "manifest.json"
    if not manifest_path.exists():
        raise RuntimeError(f"Frozen profile not found: {profile_name}")
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Frozen profile manifest could not be read: {exc}")


def fetch_required_items(progress) -> dict[str, WorkshopItem]:
    required: dict[str, WorkshopItem] = {}
    try:
        for name, collection_id in COLLECTIONS.items():
            progress(f"Fetching {name} collection via Steam API...")
            items = fetch_collection_items_api(name, collection_id)
            if not items:
                raise RuntimeError(f"No Workshop items found in {name}.")
            for item in items:
                required[item.item_id] = item
            progress(f"{name}: {len(items)} items")
        save_collection_cache(required)
        return required
    except Exception as api_error:
        progress(f"Steam API fetch failed: {api_error}")

    try:
        required.clear()
        for name, collection_id in COLLECTIONS.items():
            progress(f"Fetching {name} collection page...")
            html = fetch_url(WORKSHOP_URL.format(id=collection_id))
            items = parse_collection_items(name, collection_id, html)
            if not items:
                raise RuntimeError(f"No Workshop items found in {name}. Steam may have changed the page or blocked the request.")
            for item in items:
                required[item.item_id] = item
            progress(f"{name}: {len(items)} items")
            time.sleep(1.0)
        save_collection_cache(required)
        return required
    except Exception as html_error:
        cached = load_collection_cache()
        if cached:
            progress(f"Using cached collection list with {len(cached)} items after Steam fetch failure: {html_error}")
            return cached
        raise html_error


def read_package_id(mod_dir: Path) -> str:
    about_path = mod_dir / "About" / "About.xml"
    if not about_path.exists():
        return ""
    try:
        root = ET.parse(about_path).getroot()
    except ET.ParseError:
        return ""
    package = root.findtext("packageId") or root.findtext("PackageId") or ""
    return package.strip().lower()


def xml_text_values(parent: ET.Element | None, tag_name: str | None = None) -> list[str]:
    if parent is None:
        return []
    values: list[str] = []
    iterable = parent.iter(tag_name) if tag_name else parent.iter()
    for elem in iterable:
        if len(list(elem)):
            continue
        text = (elem.text or "").strip().lower()
        if text:
            values.append(text)
    return values


def read_mod_metadata(mod_dir: Path, item_id: str) -> ModMetadata | None:
    about_path = mod_dir / "About" / "About.xml"
    if not about_path.exists():
        return None
    try:
        root = ET.parse(about_path).getroot()
    except ET.ParseError:
        return None

    package_id = (root.findtext("packageId") or root.findtext("PackageId") or "").strip().lower()
    if not package_id:
        return None

    name = (root.findtext("name") or root.findtext("Name") or item_id).strip()
    dependencies = xml_text_values(root.find("modDependencies"), "packageId")
    load_after = xml_text_values(root.find("loadAfter"), "li")
    load_before = xml_text_values(root.find("loadBefore"), "li")
    return ModMetadata(
        item_id=item_id,
        package_id=package_id,
        name=name,
        dependencies=tuple(dict.fromkeys(dependencies)),
        load_after=tuple(dict.fromkeys(load_after)),
        load_before=tuple(dict.fromkeys(load_before)),
    )


def read_installed_metadata(item_paths: dict[str, Path], item_ids: list[str]) -> dict[str, ModMetadata]:
    metadata: dict[str, ModMetadata] = {}
    for item_id in item_ids:
        mod_path = item_paths.get(item_id)
        if not mod_path:
            continue
        meta = read_mod_metadata(mod_path, item_id)
        if meta and meta.package_id not in metadata:
            metadata[meta.package_id] = meta
    return metadata


def scan_mod_folder(root_path: Path) -> tuple[set[str], dict[str, str], dict[str, Path]]:
    installed_ids: set[str] = set()
    package_ids: dict[str, str] = {}
    item_paths: dict[str, Path] = {}
    if not root_path.exists():
        return installed_ids, package_ids, item_paths

    for child in root_path.iterdir():
        if not child.is_dir() or not child.name.isdigit():
            continue
        installed_ids.add(child.name)
        item_paths[child.name] = child
        package_id = read_package_id(child)
        if package_id:
            package_ids[child.name] = package_id
    return installed_ids, package_ids, item_paths


def find_quarantined_mods(workshop_path: Path) -> list[QuarantinedMod]:
    quarantined: list[QuarantinedMod] = []
    if not workshop_path.exists():
        return quarantined
    for quarantine_dir in sorted(workshop_path.glob(".progressor_quarantine_*"), key=lambda p: p.name, reverse=True):
        if not quarantine_dir.is_dir():
            continue
        for child in sorted(quarantine_dir.iterdir(), key=lambda p: p.name):
            if child.is_dir() and child.name.isdigit():
                quarantined.append(
                    QuarantinedMod(
                        item_id=child.name,
                        quarantine_path=quarantine_dir,
                        mod_path=child,
                        package_id=read_package_id(child),
                    )
                )
    return quarantined


def scan(workshop_path: Path, local_mods_path: Path, mods_config_path: Path, progress) -> ScanResult:
    required = fetch_required_items(progress)
    progress("Scanning local Workshop folder...")
    workshop_ids, workshop_package_ids, workshop_paths = scan_mod_folder(workshop_path)
    progress("Scanning RimWorld local Mods folder...")
    local_ids, local_package_ids, local_paths = scan_mod_folder(local_mods_path)
    registered_ids = registered_workshop_ids(workshop_path)
    steam_ready_ids = workshop_ids & registered_ids if registered_ids else workshop_ids
    installed_ids = workshop_ids | local_ids
    ready_ids = steam_ready_ids | local_ids
    package_ids = dict(workshop_package_ids)
    package_ids.update(local_package_ids)
    item_paths = dict(workshop_paths)
    item_paths.update(local_paths)
    required = {
        item_id: item
        for item_id, item in required.items()
        if item.title or item_id in installed_ids
    }
    required_ids = set(required)
    required_order = list(required)
    always_enabled_ids = load_always_enabled_ids()
    return ScanResult(
        required=required,
        required_order=required_order,
        installed_ids=installed_ids,
        installed_package_ids=package_ids,
        item_paths=item_paths,
        local_steamcmd_ids=local_ids,
        steam_registered_ids=steam_ready_ids,
        missing_ids=[item_id for item_id in required_order if item_id not in installed_ids],
        unregistered_ids=[item_id for item_id in required_order if item_id in workshop_ids and item_id not in ready_ids],
        extra_ids=sorted(installed_ids - required_ids, key=int),
        ready_ids=[item_id for item_id in required_order if item_id in ready_ids],
        always_enabled_ids=always_enabled_ids,
        workshop_path=workshop_path,
        local_mods_path=local_mods_path,
        mods_config_path=mods_config_path,
    )


def timestamp() -> str:
    return _dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def backup_file(path: Path) -> Path | None:
    if not path.exists():
        return None
    backup = path.with_suffix(path.suffix + f".progressor_backup_{timestamp()}")
    shutil.copy2(path, backup)
    return backup


def quarantine_mods(workshop_path: Path, mod_ids: list[str], progress) -> Path:
    quarantine_root = workshop_path / f".progressor_quarantine_{timestamp()}"
    quarantine_root.mkdir(parents=True, exist_ok=True)
    for mod_id in mod_ids:
        source = workshop_path / mod_id
        if not source.exists():
            continue
        target = quarantine_root / mod_id
        progress(f"Quarantining {mod_id}...")
        shutil.move(str(source), str(target))
    return quarantine_root


def restore_quarantined_mods(workshop_path: Path, mods: list[QuarantinedMod], progress) -> int:
    restored = 0
    for mod in mods:
        target = workshop_path / mod.item_id
        if target.exists():
            progress(f"Skipping {mod.item_id}: target already exists.")
            continue
        if not mod.mod_path.exists():
            progress(f"Skipping {mod.item_id}: quarantined folder no longer exists.")
            continue
        progress(f"Restoring {mod.item_id}...")
        shutil.move(str(mod.mod_path), str(target))
        restored += 1
    return restored


def frozen_active_item_ids(result: ScanResult) -> list[str]:
    active = [
        *result.ready_ids,
        *[
            item_id
            for item_id in sorted(result.always_enabled_ids, key=int)
            if item_id in result.installed_ids and item_id not in result.ready_ids
        ],
    ]
    return [item_id for item_id in active if item_id in result.item_paths]


def create_frozen_profile(result: ScanResult, profile_name: str, progress) -> Path:
    profile_name = safe_profile_name(profile_name)
    if not profile_name:
        raise RuntimeError("Profile name cannot be empty.")
    active_ids = frozen_active_item_ids(result)
    if not active_ids:
        raise RuntimeError("No active mods are available to freeze.")
    profile_root = frozen_profile_path(profile_name)
    mods_root = profile_root / "Mods"
    if profile_root.exists():
        raise RuntimeError(f"Frozen profile already exists: {profile_name}")
    mods_root.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, str]] = []
    for item_id in active_ids:
        source = result.item_paths[item_id]
        target = mods_root / item_id
        progress(f"Freezing {item_id}...")
        shutil.copytree(source, target)
        item = result.required.get(item_id)
        entries.append(
            {
                "item_id": item_id,
                "package_id": result.installed_package_ids.get(item_id, ""),
                "title": item.title if item else "",
                "source": str(source),
            }
        )
    manifest = {
        "name": profile_name,
        "created_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "item_ids": active_ids,
        "mods": entries,
    }
    config_source = result.mods_config_path.parent
    config_target = frozen_config_path(profile_name)
    if config_source.exists():
        progress("Freezing RimWorld config files...")
        shutil.copytree(config_source, config_target)
    else:
        config_target.mkdir(parents=True, exist_ok=True)
    (profile_root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return profile_root


def replace_directory(source: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)


def save_live_config_to_frozen(profile_name: str, live_config_path: Path, progress) -> None:
    if not profile_name or not live_config_path.exists():
        return
    target = frozen_config_path(profile_name)
    progress(f"Saving config changes into frozen profile: {profile_name}")
    replace_directory(live_config_path, target)


def stage_frozen_config(profile_name: str, live_config_path: Path, staging_root: Path, state: dict, save_state, progress) -> None:
    frozen_config = frozen_config_path(profile_name)
    if not frozen_config.exists():
        frozen_config.mkdir(parents=True, exist_ok=True)
    staged_config = staging_root / "live_config"
    state["config"] = {
        "live": str(live_config_path),
        "staged": str(staged_config),
    }
    if live_config_path.exists():
        progress("Staging live RimWorld config files...")
        shutil.move(str(live_config_path), str(staged_config))
    else:
        staged_config.mkdir(parents=True, exist_ok=True)
    save_state()
    progress("Applying frozen RimWorld config files...")
    shutil.copytree(frozen_config, live_config_path)


def restore_staged_live(progress) -> None:
    if not STAGING_STATE_PATH.exists():
        return
    try:
        state = json.loads(STAGING_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    profile_name = str(state.get("profile", ""))
    config_state = state.get("config", {})
    if isinstance(config_state, dict) and config_state.get("live") and config_state.get("staged"):
        live_config = Path(config_state.get("live", ""))
        staged_config = Path(config_state.get("staged", ""))
        if live_config.exists():
            save_live_config_to_frozen(profile_name, live_config, progress)
            progress("Removing staged frozen RimWorld config files...")
            shutil.rmtree(live_config)
        if staged_config.exists():
            progress("Restoring live RimWorld config files...")
            live_config.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(staged_config), str(live_config))
    restored = 0
    for entry in reversed(state.get("moved", [])):
        original = Path(entry.get("original", ""))
        staged = Path(entry.get("staged", ""))
        if not staged.exists():
            continue
        if original.exists():
            progress(f"Keeping staged copy because original already exists: {original}")
            continue
        original.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staged), str(original))
        restored += 1
    for path_text in state.get("frozen_copies", []):
        path = Path(path_text)
        if path.exists():
            shutil.rmtree(path)
    try:
        staging_root = Path(state.get("staging_root", ""))
        if staging_root.exists() and not any(staging_root.rglob("*")):
            shutil.rmtree(staging_root)
    except OSError:
        pass
    try:
        STAGING_STATE_PATH.unlink()
    except OSError:
        pass
    if restored:
        progress(f"Restored {restored} live mod folder(s) after frozen profile.")


def stage_frozen_profile(profile_name: str, workshop_path: Path, local_mods_path: Path, mods_config_path: Path, progress) -> set[str]:
    restore_staged_live(progress)
    manifest = load_frozen_manifest(profile_name)
    item_ids = [str(item_id) for item_id in manifest.get("item_ids", []) if str(item_id).isdigit()]
    profile_mods = frozen_profile_path(profile_name) / "Mods"
    if not item_ids:
        raise RuntimeError(f"Frozen profile contains no mods: {profile_name}")
    staging_root = app_data_dir() / "staged_live" / timestamp()
    staging_root.mkdir(parents=True, exist_ok=True)
    state = {
        "profile": profile_name,
        "staged_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "staging_root": str(staging_root),
        "moved": [],
        "frozen_copies": [],
    }
    def save_state() -> None:
        STAGING_STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")

    save_state()
    try:
        stage_frozen_config(profile_name, mods_config_path.parent, staging_root, state, save_state, progress)
        save_state()
        for item_id in item_ids:
            frozen_source = profile_mods / item_id
            if not frozen_source.exists():
                raise RuntimeError(f"Frozen profile is missing mod folder {item_id}.")
            for source_root, label in ((workshop_path, "workshop"), (local_mods_path, "local")):
                live_path = source_root / item_id
                if live_path.exists():
                    staged_path = staging_root / label / item_id
                    staged_path.parent.mkdir(parents=True, exist_ok=True)
                    progress(f"Staging live {label} copy of {item_id}...")
                    shutil.move(str(live_path), str(staged_path))
                    state["moved"].append({"original": str(live_path), "staged": str(staged_path)})
                    save_state()
            target = local_mods_path / item_id
            progress(f"Staging frozen {item_id}...")
            shutil.copytree(frozen_source, target)
            state["frozen_copies"].append(str(target))
            save_state()
    except OSError as exc:
        progress("Frozen staging hit a locked file. Rolling back staged files...")
        restore_staged_live(progress)
        raise RuntimeError(
            f"Could not stage frozen profile because a file is in use: {exc}. "
            "Close RimWorld, Steam update activity, RimSort, and file explorers pointed at mod folders, then try again."
        )
    return set(item_ids)


def registered_workshop_ids(workshop_path: Path) -> set[str]:
    manifest_path = workshop_path.parents[1] / f"appworkshop_{APP_ID}.acf"
    if not manifest_path.exists():
        return set()
    try:
        text = manifest_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return set()
    return set(re.findall(r'^\s*"(\d{7,})"\s*$', text, re.MULTILINE))


def steamcmd_acf_path(steamcmd_root: Path) -> Path:
    return steamcmd_root / "steamapps" / "workshop" / f"appworkshop_{APP_ID}.acf"


def parse_steamcmd_update_times(steamcmd_root: Path) -> dict[str, int]:
    manifest_path = steamcmd_acf_path(steamcmd_root)
    if not manifest_path.exists():
        return {}
    try:
        text = manifest_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {}
    update_times: dict[str, int] = {}
    for match in re.finditer(r'"(?P<id>\d{7,})"\s*\{(?P<body>.*?)\n\s*\}', text, re.DOTALL):
        item_id = match.group("id")
        body = match.group("body")
        time_match = re.search(r'"timeupdated"\s*"(?P<time>\d+)"', body, re.IGNORECASE)
        if not time_match:
            continue
        update_times[item_id] = int(time_match.group("time"))
    return update_times


def steamcmd_outdated_ids(result: ScanResult, steamcmd_root: Path, progress) -> tuple[list[str], list[str]]:
    local_ids = steamcmd_update_target_ids(result)
    if not local_ids:
        return [], []
    local_times = parse_steamcmd_update_times(steamcmd_root)
    remote_times = fetch_remote_update_times(local_ids, progress)
    outdated: list[str] = []
    unknown: list[str] = []
    for item_id in local_ids:
        local_time = local_times.get(item_id)
        remote_time = remote_times.get(item_id)
        if local_time is None or remote_time is None:
            unknown.append(item_id)
            continue
        if remote_time > local_time:
            outdated.append(item_id)
    return outdated, unknown


def path_is_junction_or_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction and is_junction())


def download_target_ids(result: ScanResult) -> list[str]:
    seen: set[str] = set()
    targets: list[str] = []
    for item_id in [*result.missing_ids, *result.unregistered_ids]:
        if item_id not in seen:
            seen.add(item_id)
            targets.append(item_id)
    return targets


def prepare_steamcmd_local_download_root(steamcmd_root: Path, local_mods_path: Path, progress) -> Path:
    content_parent = steamcmd_root / "steamapps" / "workshop" / "content"
    downloaded_root = content_parent / APP_ID
    local_mods_path.mkdir(parents=True, exist_ok=True)
    content_parent.mkdir(parents=True, exist_ok=True)

    if path_is_junction_or_link(downloaded_root):
        try:
            if not downloaded_root.resolve().samefile(local_mods_path.resolve()):
                raise RuntimeError(
                    f"SteamCMD's {APP_ID} content folder is already linked to {downloaded_root.resolve()}, "
                    f"not the configured Local Mods path {local_mods_path}."
                )
        except OSError:
            raise RuntimeError(f"SteamCMD's {APP_ID} content folder is a link, but its target could not be verified.")
        progress(f"SteamCMD downloads are already linked to: {local_mods_path}")
        return downloaded_root

    if downloaded_root.exists():
        existing_items = [child for child in downloaded_root.iterdir() if child.is_dir() and child.name.isdigit()]
        moved = 0
        for child in existing_items:
            target = local_mods_path / child.name
            if target.exists():
                continue
            shutil.move(str(child), str(target))
            moved += 1
        if moved:
            progress(f"Moved {moved} existing SteamCMD mod folders into RimWorld local Mods.")

        if any(downloaded_root.iterdir()):
            backup = content_parent / f"{APP_ID}.progressor_backup_{timestamp()}"
            shutil.move(str(downloaded_root), str(backup))
            progress(f"Backed up old SteamCMD content folder to: {backup}")
        else:
            downloaded_root.rmdir()

    progress(f"Linking SteamCMD content folder to RimWorld local Mods: {local_mods_path}")
    completed = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(downloaded_root), str(local_mods_path)],
        cwd=str(content_parent),
        capture_output=True,
        text=True,
        errors="replace",
    )
    if completed.returncode != 0:
        details = (completed.stdout + "\n" + completed.stderr).strip()
        raise RuntimeError(f"Failed to create SteamCMD local-mod junction. {details}")
    return downloaded_root


def relocate_unregistered_workshop_mods(result: ScanResult, targets: list[str], progress) -> int:
    moved = 0
    target_set = set(targets)
    for item_id in result.unregistered_ids:
        if item_id not in target_set:
            continue
        source = result.workshop_path / item_id
        target = result.local_mods_path / item_id
        if not source.exists() or target.exists():
            continue
        progress(f"Moving non-loadable Workshop folder {item_id} into local Mods...")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
        moved += 1
    if moved:
        progress(f"Moved {moved} Workshop-only folders into RimWorld local Mods.")
    return moved


def run_steamcmd_downloads(result: ScanResult, progress, targets: list[str] | None = None) -> Path:
    steamcmd = find_steamcmd()
    if not steamcmd:
        raise RuntimeError(
            "steamcmd.exe was not found. Install SteamCMD, place steamcmd.exe next to this app, "
            "or set a STEAMCMD environment variable pointing to it."
        )
    targets = targets or download_target_ids(result)
    if not targets:
        raise RuntimeError("There are no SteamCMD mods to download or validate.")

    progress(f"Using SteamCMD: {steamcmd}")
    steamcmd_root = steamcmd.parent
    relocate_unregistered_workshop_mods(result, targets, progress)
    downloaded_root = prepare_steamcmd_local_download_root(steamcmd_root, result.local_mods_path, progress)

    # SteamCMD accepts many +workshop_download_item commands in one invocation,
    # but huge command lines can hit Windows limits. Batches keep it boring.
    batch_size = 40
    for index in range(0, len(targets), batch_size):
        batch = targets[index : index + batch_size]
        progress(f"Downloading/validating batch {index // batch_size + 1}: {len(batch)} mods...")
        script_lines = ["@ShutdownOnFailedCommand 0", "@NoPromptForPassword 1", "login anonymous"]
        script_lines.extend(f"workshop_download_item {APP_ID} {item_id} validate" for item_id in batch)
        script_lines.append("quit")
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt", encoding="utf-8") as handle:
            handle.write("\n".join(script_lines))
            script_path = Path(handle.name)
        try:
            process = subprocess.Popen(
                [str(steamcmd), "+runscript", str(script_path)],
                cwd=str(steamcmd_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
            )
            assert process.stdout is not None
            for line in process.stdout:
                line = line.strip()
                if "Success. Downloaded item" in line or "ERROR!" in line or "FAILED" in line:
                    progress(line)
            return_code = process.wait()
            if return_code != 0:
                downloaded_count = sum(1 for item_id in batch if (downloaded_root / item_id).exists())
                if downloaded_count == 0:
                    raise RuntimeError(f"SteamCMD exited with code {return_code} before downloading this batch.")
                progress(f"SteamCMD exited with code {return_code}, but {downloaded_count}/{len(batch)} mods from this batch are present. Continuing...")
        finally:
            try:
                script_path.unlink()
            except OSError:
                pass

    return downloaded_root


def steamcmd_update_target_ids(result: ScanResult) -> list[str]:
    return [item_id for item_id in result.required_order if item_id in result.local_steamcmd_ids]


def existing_ludeon_active_mods(path: Path) -> list[str]:
    if not path.exists():
        return ["ludeon.rimworld"]
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return ["ludeon.rimworld"]
    active = root.find("activeMods")
    if active is None:
        return ["ludeon.rimworld"]
    package_ids = []
    for li in active.findall("li"):
        text = (li.text or "").strip().lower()
        if text.startswith("ludeon.rimworld") and text not in package_ids:
            package_ids.append(text)
    return package_ids or ["ludeon.rimworld"]


def existing_active_mods(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return []
    active = root.find("activeMods")
    if active is None:
        return []
    package_ids: list[str] = []
    for li in active.findall("li"):
        text = (li.text or "").strip().lower()
        if text and text not in package_ids:
            package_ids.append(text)
    return package_ids


def existing_config_version(path: Path) -> str:
    if not path.exists():
        return "1.6"
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return "1.6"
    return (root.findtext("version") or "1.6").strip()


def existing_known_expansions(path: Path) -> list[str]:
    defaults = [
        "ludeon.rimworld.royalty",
        "ludeon.rimworld.ideology",
        "ludeon.rimworld.biotech",
        "ludeon.rimworld.anomaly",
        "ludeon.rimworld.odyssey",
    ]
    if not path.exists():
        return defaults
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return defaults
    known = root.find("knownExpansions")
    if known is None:
        return defaults
    package_ids = []
    for li in known.findall("li"):
        text = (li.text or "").strip().lower()
        if text and text not in package_ids:
            package_ids.append(text)
    for default in defaults:
        if default not in package_ids:
            package_ids.append(default)
    return package_ids


def stable_topological_sort(nodes: list[str], edges: list[tuple[str, str]]) -> tuple[list[str], int]:
    node_set = set(nodes)
    priority = {package_id: index for index, package_id in enumerate(nodes)}
    outgoing: dict[str, set[str]] = {package_id: set() for package_id in nodes}
    incoming_count: dict[str, int] = {package_id: 0 for package_id in nodes}

    for before, after in edges:
        if before == after or before not in node_set or after not in node_set:
            continue
        if after not in outgoing[before]:
            outgoing[before].add(after)
            incoming_count[after] += 1

    remaining = set(nodes)
    ordered: list[str] = []
    broken_edges = 0
    while remaining:
        available = [package_id for package_id in remaining if incoming_count[package_id] == 0]
        if not available:
            chosen = min(remaining, key=lambda package_id: priority.get(package_id, 10**9))
            broken_edges += incoming_count[chosen]
            incoming_count[chosen] = 0
        else:
            chosen = min(available, key=lambda package_id: priority.get(package_id, 10**9))
        remaining.remove(chosen)
        ordered.append(chosen)
        for after in outgoing[chosen]:
            incoming_count[after] -= 1
    return ordered, broken_edges


def build_vanilla_sorted_active_list(result: ScanResult) -> SortResult:
    ludeon_mods = existing_ludeon_active_mods(result.mods_config_path)
    existing_order = existing_active_mods(result.mods_config_path)
    active_item_ids = [
        *result.ready_ids,
        *[
            item_id
            for item_id in sorted(result.always_enabled_ids, key=int)
            if item_id in result.installed_ids and item_id not in result.ready_ids
        ],
    ]
    metadata = read_installed_metadata(result.item_paths, active_item_ids)
    active_package_ids = [
        result.installed_package_ids[item_id]
        for item_id in active_item_ids
        if item_id in result.installed_package_ids
    ]

    active_set = set(ludeon_mods) | set(active_package_ids)
    pre_core_mods = [
        package_id
        for package_id, meta in metadata.items()
        if package_id in active_set and "ludeon.rimworld" in meta.load_before
    ]

    base_order: list[str] = []

    def add_base(package_id: str) -> None:
        package_id = package_id.lower()
        if package_id in active_set and package_id not in base_order:
            base_order.append(package_id)

    inserted_pre_core = False
    for package_id in [*existing_order, *ludeon_mods]:
        if package_id.lower() == "ludeon.rimworld" and not inserted_pre_core:
            for pre_core in pre_core_mods:
                add_base(pre_core)
            inserted_pre_core = True
        add_base(package_id)
    if not inserted_pre_core:
        for pre_core in pre_core_mods:
            add_base(pre_core)
    for package_id in active_package_ids:
        add_base(package_id)

    edges: list[tuple[str, str]] = []
    dependency_edges = 0
    load_rule_edges = 0
    ludeon_order = [
        "ludeon.rimworld",
        "ludeon.rimworld.royalty",
        "ludeon.rimworld.ideology",
        "ludeon.rimworld.biotech",
        "ludeon.rimworld.anomaly",
        "ludeon.rimworld.odyssey",
    ]
    for before, after in zip(ludeon_order, ludeon_order[1:]):
        if before in active_set and after in active_set:
            edges.append((before, after))
            load_rule_edges += 1
    for package_id, meta in metadata.items():
        if package_id not in active_set:
            continue
        for dependency in meta.dependencies:
            if dependency in active_set:
                edges.append((dependency, package_id))
                dependency_edges += 1
        for before_pkg in meta.load_after:
            if before_pkg in active_set:
                edges.append((before_pkg, package_id))
                load_rule_edges += 1
        for after_pkg in meta.load_before:
            if after_pkg in active_set:
                edges.append((package_id, after_pkg))
                load_rule_edges += 1

    sorted_package_ids, broken_edges = stable_topological_sort(base_order, edges)
    return SortResult(
        package_ids=sorted_package_ids,
        metadata_count=len(metadata),
        dependency_edges=dependency_edges,
        load_rule_edges=load_rule_edges,
        broken_edges=broken_edges,
    )


def write_mods_config(result: ScanResult, progress) -> Path:
    sort_result = build_vanilla_sorted_active_list(result)
    if not sort_result.package_ids:
        raise RuntimeError("No installed Workshop package IDs were found. Download the missing mods first, then scan again.")

    progress("Backing up ModsConfig.xml...")
    result.mods_config_path.parent.mkdir(parents=True, exist_ok=True)
    backup_file(result.mods_config_path)

    root = ET.Element("ModsConfigData")
    version = ET.SubElement(root, "version")
    version.text = existing_config_version(result.mods_config_path)
    active_mods = ET.SubElement(root, "activeMods")
    for package_id in sort_result.package_ids:
        li = ET.SubElement(active_mods, "li")
        li.text = package_id
    known_expansions = ET.SubElement(root, "knownExpansions")
    for dlc in existing_known_expansions(result.mods_config_path):
        li = ET.SubElement(known_expansions, "li")
        li.text = dlc

    tree = ET.ElementTree(root)
    ET.indent(tree, space="\t")
    tree.write(result.mods_config_path, encoding="utf-8", xml_declaration=True)
    progress(
        "Wrote "
        f"{len(sort_result.package_ids)} active mods using {sort_result.dependency_edges} dependency "
        f"and {sort_result.load_rule_edges} load-order rules."
    )
    if sort_result.broken_edges:
        progress(f"Sort note: broke {sort_result.broken_edges} conflicting/cyclic rules to finish the order.")
    return result.mods_config_path


class ProgressorApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1540x800")
        self.minsize(1280, 680)
        self.configure(bg="#101418")

        self.workshop_path = tk.StringVar(value=str(default_workshop_path()))
        self.local_mods_path = tk.StringVar(value=str(default_rimworld_mods_path()))
        self.mods_config_path = tk.StringVar(value=str(default_mods_config_path()))
        detected_steamcmd = find_steamcmd()
        self.steamcmd_path = tk.StringVar(value=str(detected_steamcmd) if detected_steamcmd else "")
        self.auto_activate_after_download = BooleanVar(value=True)
        self.current_result: ScanResult | None = None
        self.current_rows: list[tuple[str, str, str, str | None, QuarantinedMod | None]] = []
        self.state_filter = tk.StringVar(value="All states")
        self.pack_filter = tk.StringVar(value="All packs")
        self.frozen_profile = tk.StringVar(value="")
        self.busy_message = tk.StringVar(value="")
        self.frozen_profile_combo: ttk.Combobox | None = None
        self.row_item_ids: dict[str, str] = {}
        self.quarantined_rows: dict[str, QuarantinedMod] = {}
        self.advanced_visible = False
        self.logo_image: tk.PhotoImage | None = None
        self.progress_bar: ttk.Progressbar | None = None

        self._build_ui()

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background="#101418", foreground="#d7dedb", fieldbackground="#171d22")
        style.configure("TFrame", background="#101418")
        style.configure("TLabel", background="#101418", foreground="#d7dedb")
        style.configure("TLabelframe", background="#101418", foreground="#d7dedb", bordercolor="#2b353c")
        style.configure("TLabelframe.Label", background="#101418", foreground="#f2b35d")
        style.configure("TButton", background="#1b252b", foreground="#e9efec", bordercolor="#41515a", focusthickness=0, padding=(10, 6))
        style.map("TButton", background=[("active", "#26343d")], foreground=[("active", "#ffffff")])
        style.configure("TCheckbutton", background="#101418", foreground="#d7dedb")
        style.configure("TCombobox", fieldbackground="#161d22", foreground="#eef3ef", arrowcolor="#f2b35d")
        style.configure("TEntry", fieldbackground="#161d22", foreground="#eef3ef", insertcolor="#eef3ef")
        style.configure("Treeview", background="#12181d", foreground="#d7dedb", fieldbackground="#12181d", bordercolor="#2b353c", rowheight=24)
        style.configure("Treeview.Heading", background="#1d272e", foreground="#f2b35d")
        style.map("Treeview", background=[("selected", "#2d4b55")], foreground=[("selected", "#ffffff")])
        style.configure("TPanedwindow", background="#101418")

    def _build_ui(self) -> None:
        self._configure_styles()
        self.columnconfigure(0, weight=1)
        self.rowconfigure(4, weight=1)

        header = ttk.Frame(self, padding=(18, 14, 18, 8))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        logo_path = asset_path("progression_logo.png")
        if logo_path.exists():
            self.logo_image = tk.PhotoImage(file=str(logo_path)).subsample(2, 2)
            tk.Label(header, image=self.logo_image, bg="#101418", bd=0).grid(row=0, column=0, sticky="w")
        else:
            ttk.Label(header, text="PROGRESSION", font=("Segoe UI", 28, "bold"), foreground="#f2b35d").grid(row=0, column=0, sticky="w")

        quick = ttk.Frame(self, padding=(18, 4, 18, 12))
        quick.grid(row=1, column=0, sticky="ew")
        quick.columnconfigure(0, weight=1)
        self.play_button = tk.Button(
            quick,
            text="PLAY NOW",
            command=self.play_now,
            bg="#c27a2c",
            fg="#111111",
            activebackground="#f2b35d",
            activeforeground="#111111",
            font=("Segoe UI", 20, "bold"),
            relief="flat",
            padx=28,
            pady=14,
            cursor="hand2",
        )
        self.play_button.grid(row=0, column=0, sticky="ew")
        self.progress_bar = ttk.Progressbar(quick, mode="indeterminate")
        self.progress_bar.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.progress_bar.grid_remove()
        ttk.Label(
            quick,
            textvariable=self.busy_message,
            foreground="#f2b35d",
        ).grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Label(
            quick,
            text="Scans the pack, downloads missing mods, disables extras, activates and sorts, then launches RimWorld.",
            foreground="#9fb1ad",
        ).grid(row=3, column=0, sticky="w", pady=(6, 0))
        self.advanced_button = ttk.Button(quick, text="Show Advanced Options", command=self.toggle_advanced)
        self.advanced_button.grid(row=3, column=1, sticky="e", padx=(12, 0), pady=(6, 0))

        self.advanced_frame = ttk.Frame(self, padding=(18, 0, 18, 8))
        self.advanced_frame.columnconfigure(0, weight=1)

        paths = ttk.LabelFrame(self.advanced_frame, text="Paths", padding=12)
        paths.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        paths.columnconfigure(1, weight=1)
        ttk.Label(paths, text="Workshop").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(paths, textvariable=self.workshop_path).grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Button(paths, text="Browse", command=self.choose_workshop).grid(row=0, column=2, padx=(8, 0), pady=4)
        ttk.Label(paths, text="ModsConfig").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(paths, textvariable=self.mods_config_path).grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Button(paths, text="Browse", command=self.choose_mods_config).grid(row=1, column=2, padx=(8, 0), pady=4)
        ttk.Label(paths, text="Local Mods").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(paths, textvariable=self.local_mods_path).grid(row=2, column=1, sticky="ew", pady=4)
        ttk.Button(paths, text="Browse", command=self.choose_local_mods).grid(row=2, column=2, padx=(8, 0), pady=4)
        ttk.Label(paths, text="SteamCMD").grid(row=3, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(paths, textvariable=self.steamcmd_path).grid(row=3, column=1, sticky="ew", pady=4)
        ttk.Button(paths, text="Browse", command=self.choose_steamcmd).grid(row=3, column=2, padx=(8, 0), pady=4)
        ttk.Button(paths, text="Auto Detect Paths", command=self.auto_detect_paths).grid(row=4, column=2, sticky="e", padx=(8, 0), pady=(8, 0))
        toolbar = ttk.Frame(self.advanced_frame)
        toolbar.grid(row=1, column=0, sticky="ew")
        ttk.Button(toolbar, text="Scan Ferny's Pack", command=self.start_scan).pack(side="left")
        ttk.Button(toolbar, text="Download Missing", command=self.download_missing).pack(side="left", padx=6)
        ttk.Button(toolbar, text="Update SteamCMD Mods", command=self.update_steamcmd_mods).pack(side="left", padx=6)
        ttk.Button(toolbar, text="Always Enable Selected", command=self.always_enable_selected).pack(side="left", padx=6)
        ttk.Button(toolbar, text="Disable Selected", command=self.disable_selected).pack(side="left", padx=6)
        ttk.Button(toolbar, text="Freeze Current Setup", command=self.freeze_current_setup).pack(side="left", padx=6)
        ttk.Button(toolbar, text="Play Frozen", command=self.play_frozen).pack(side="left", padx=6)
        ttk.Button(toolbar, text="Restore Live Setup", command=self.restore_live_setup).pack(side="left", padx=6)
        ttk.Button(toolbar, text="Activate + Vanilla Sort", command=self.write_config).pack(side="left", padx=6)
        ttk.Checkbutton(toolbar, text="Auto-activate after download", variable=self.auto_activate_after_download).pack(side="left", padx=6)
        ttk.Button(toolbar, text="Launch RimWorld", command=lambda: webbrowser.open(STEAM_RUN_RIMWORLD)).pack(side="right")

        profile_row = ttk.Frame(self.advanced_frame)
        profile_row.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        ttk.Label(profile_row, text="Frozen Profile").pack(side="left")
        self.frozen_profile_combo = ttk.Combobox(
            profile_row,
            textvariable=self.frozen_profile,
            values=frozen_profile_names(),
            state="readonly",
            width=34,
        )
        self.frozen_profile_combo.pack(side="left", padx=(8, 0))
        ttk.Button(profile_row, text="Refresh Profiles", command=self.refresh_frozen_profiles).pack(side="left", padx=(8, 0))

        main = ttk.PanedWindow(self, orient="horizontal")
        main.grid(row=4, column=0, sticky="nsew", padx=18, pady=(0, 14))

        left = ttk.Frame(main)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)
        ttk.Label(left, text="Status", font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.status = tk.Text(
            left,
            height=12,
            wrap="word",
            state="disabled",
            bg="#0d1115",
            fg="#d7dedb",
            insertbackground="#d7dedb",
            relief="flat",
            padx=10,
            pady=8,
        )
        self.status.grid(row=1, column=0, sticky="nsew")
        main.add(left, weight=1)

        right = ttk.Frame(main)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=1)
        header_row = ttk.Frame(right)
        header_row.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 6))
        header_row.columnconfigure(0, weight=1)
        ttk.Label(header_row, text="Mod Differences", font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w")

        filters = ttk.Frame(right)
        filters.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 6))
        ttk.Label(filters, text="State").pack(side="left")
        state_combo = ttk.Combobox(
            filters,
            textvariable=self.state_filter,
            values=("All states", "Missing", "Needs SteamCMD", "Enabled", "Disabled", "Always Enabled"),
            state="readonly",
            width=16,
        )
        state_combo.pack(side="left", padx=(6, 14))
        state_combo.bind("<<ComboboxSelected>>", lambda _event: self.apply_mod_filters())
        ttk.Label(filters, text="Pack").pack(side="left")
        pack_combo = ttk.Combobox(
            filters,
            textvariable=self.pack_filter,
            values=("All packs", "Core", "Content", "Cosmetics", "Local", "Workshop"),
            state="readonly",
            width=16,
        )
        pack_combo.pack(side="left", padx=(6, 0))
        pack_combo.bind("<<ComboboxSelected>>", lambda _event: self.apply_mod_filters())

        self.tree = ttk.Treeview(right, columns=("state", "collection", "title"), show="headings")
        self.tree.heading("state", text="State")
        self.tree.heading("collection", text="Pack")
        self.tree.heading("title", text="Workshop ID / Title")
        self.tree.column("state", width=100, anchor="w")
        self.tree.column("collection", width=90, anchor="w")
        self.tree.column("title", width=520, anchor="w")
        self.tree.grid(row=2, column=0, sticky="nsew")
        tree_scroll = ttk.Scrollbar(right, orient="vertical", command=self.tree.yview)
        tree_scroll.grid(row=2, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=tree_scroll.set)
        main.add(right, weight=2)

        self.refresh_frozen_profiles()
        self.progress("Ready. Press Play Now for the full automatic setup, or open Advanced Options for manual controls.")

    def set_mod_rows(self, rows: list[tuple[str, str, str, str | None, QuarantinedMod | None]]) -> None:
        self.current_rows = rows
        self.apply_mod_filters()

    def apply_mod_filters(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self.row_item_ids.clear()
        self.quarantined_rows.clear()
        state_filter = self.state_filter.get()
        pack_filter = self.pack_filter.get()
        for state, collection, title, item_id, quarantined_mod in self.current_rows:
            if state_filter != "All states" and state != state_filter:
                continue
            if pack_filter != "All packs":
                if collection != pack_filter:
                    continue
            row_id = self.tree.insert("", "end", values=(state, collection, title))
            if item_id:
                self.row_item_ids[row_id] = item_id
            if quarantined_mod:
                self.quarantined_rows[row_id] = quarantined_mod

    def selected_item_ids(self) -> set[str]:
        return {
            self.row_item_ids[item]
            for item in self.tree.selection()
            if item in self.row_item_ids
        }

    def refresh_frozen_profiles(self) -> None:
        names = frozen_profile_names()
        if self.frozen_profile_combo is not None:
            self.frozen_profile_combo.configure(values=names)
        if names and self.frozen_profile.get() not in names:
            self.frozen_profile.set(names[0])
        elif not names:
            self.frozen_profile.set("")

    def toggle_advanced(self) -> None:
        self.advanced_visible = not self.advanced_visible
        if self.advanced_visible:
            self.advanced_frame.grid(row=2, column=0, sticky="ew")
            self.advanced_button.configure(text="Hide Advanced Options")
        else:
            self.advanced_frame.grid_remove()
            self.advanced_button.configure(text="Show Advanced Options")

    def progress(self, message: str) -> None:
        def append() -> None:
            self.status.configure(state="normal")
            self.status.insert("end", f"{_dt.datetime.now().strftime('%H:%M:%S')}  {message}\n")
            self.status.see("end")
            self.status.configure(state="disabled")

        self.after(0, append)

    def choose_workshop(self) -> None:
        path = filedialog.askdirectory(initialdir=self.workshop_path.get() or str(Path.home()))
        if path:
            self.workshop_path.set(path)

    def choose_mods_config(self) -> None:
        path = filedialog.askopenfilename(
            initialdir=str(Path(self.mods_config_path.get()).parent),
            filetypes=[("RimWorld config", "ModsConfig.xml"), ("XML files", "*.xml"), ("All files", "*.*")],
        )
        if path:
            self.mods_config_path.set(path)

    def choose_local_mods(self) -> None:
        path = filedialog.askdirectory(initialdir=self.local_mods_path.get() or str(Path.home()))
        if path:
            self.local_mods_path.set(path)

    def choose_steamcmd(self) -> None:
        initial = self.steamcmd_path.get()
        initial_dir = str(Path(initial).parent) if initial else str(Path.home())
        path = filedialog.askopenfilename(
            initialdir=initial_dir,
            filetypes=[("SteamCMD", "steamcmd.exe"), ("Executables", "*.exe"), ("All files", "*.*")],
        )
        if path:
            self.steamcmd_path.set(path)

    def auto_detect_paths(self) -> None:
        self.workshop_path.set(str(default_workshop_path()))
        self.local_mods_path.set(str(default_rimworld_mods_path()))
        self.mods_config_path.set(str(default_mods_config_path()))
        detected_steamcmd = find_steamcmd()
        self.steamcmd_path.set(str(detected_steamcmd) if detected_steamcmd else "")
        self.progress("Auto-detected paths from Steam libraries and standard RimWorld config locations.")

    def auto_detect_invalid_paths(self) -> None:
        detected: list[str] = []
        workshop = Path(self.workshop_path.get().strip()) if self.workshop_path.get().strip() else None
        if workshop is None or not workshop.exists():
            self.workshop_path.set(str(default_workshop_path()))
            detected.append("Workshop")

        local_mods = Path(self.local_mods_path.get().strip()) if self.local_mods_path.get().strip() else None
        if local_mods is None or not local_mods.exists():
            self.local_mods_path.set(str(default_rimworld_mods_path()))
            detected.append("Local Mods")

        mods_config = Path(self.mods_config_path.get().strip()) if self.mods_config_path.get().strip() else None
        if mods_config is None or not mods_config.parent.exists():
            self.mods_config_path.set(str(default_mods_config_path()))
            detected.append("ModsConfig")

        configured_steamcmd = Path(self.steamcmd_path.get().strip()) if self.steamcmd_path.get().strip() else None
        if configured_steamcmd is None or not configured_steamcmd.exists():
            detected_steamcmd = find_steamcmd()
            self.steamcmd_path.set(str(detected_steamcmd) if detected_steamcmd else "")
            if detected_steamcmd:
                detected.append("SteamCMD")

        if detected:
            self.progress(f"Play Now auto-detected invalid or missing paths: {', '.join(detected)}.")

    def run_worker(self, target) -> None:
        threading.Thread(target=target, daemon=True).start()

    def set_busy(self, message: str) -> None:
        self.play_button.configure(state="disabled", text=message.upper())
        self.busy_message.set(message)
        if self.progress_bar is not None:
            self.progress_bar.grid()
            self.progress_bar.start(12)

    def clear_busy(self) -> None:
        if self.progress_bar is not None:
            self.progress_bar.stop()
            self.progress_bar.grid_remove()
        self.busy_message.set("")
        self.play_button.configure(state="normal", text="PLAY NOW")

    def run_busy_worker(self, message: str, target) -> None:
        self.set_busy(message)

        def wrapped() -> None:
            try:
                target()
            finally:
                self.after(0, self.clear_busy)

        self.run_worker(wrapped)

    def scan_paths(self, progress) -> ScanResult:
        return scan(
            Path(self.workshop_path.get()),
            Path(self.local_mods_path.get()),
            Path(self.mods_config_path.get()),
            progress,
        )

    def play_now(self) -> None:
        self.auto_detect_invalid_paths()

        def worker() -> None:
            old_env = os.environ.get("STEAMCMD")
            try:
                steamcmd = self.steamcmd_path.get().strip()
                if steamcmd:
                    os.environ["STEAMCMD"] = steamcmd

                self.progress("Play Now started.")
                restore_staged_live(self.progress)
                result = self.scan_paths(self.progress)
                self.current_result = result
                self.after(0, lambda: self.render_result(result))

                pending_downloads = download_target_ids(result)
                if pending_downloads:
                    self.progress(f"{len(pending_downloads)} mods need SteamCMD local download. Downloading...")
                    run_steamcmd_downloads(result, self.progress)
                    result = self.scan_paths(self.progress)
                    self.current_result = result
                    self.after(0, lambda: self.render_result(result))

                if result.missing_ids:
                    raise RuntimeError(f"Cannot launch yet: {len(result.missing_ids)} required mods are still missing.")

                if result.unregistered_ids:
                    raise RuntimeError(
                        f"{len(result.unregistered_ids)} mods are still present only as non-loadable Workshop folders. "
                        "Run the SteamCMD download step again, or check that Local Mods points to RimWorld's Mods folder."
                    )
                write_mods_config(result, self.progress)
                self.progress("Launching RimWorld through Steam...")
                webbrowser.open(STEAM_RUN_RIMWORLD)
            except (RuntimeError, OSError, urllib.error.URLError) as exc:
                self.progress(f"Play Now failed: {exc}")
                error = str(exc)
                self.after(0, lambda: messagebox.showerror("Play Now failed", error))
            finally:
                if old_env is None:
                    os.environ.pop("STEAMCMD", None)
                else:
                    os.environ["STEAMCMD"] = old_env

        self.run_busy_worker("Preparing live setup...", worker)

    def start_scan(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self.progress("Starting scan...")

        def worker() -> None:
            try:
                result = self.scan_paths(self.progress)
                self.current_result = result
                self.after(0, lambda: self.render_result(result))
            except (RuntimeError, urllib.error.URLError, OSError) as exc:
                self.progress(f"Scan failed: {exc}")
                error = str(exc)
                self.after(0, lambda: messagebox.showerror("Scan failed", error))

        self.run_busy_worker("Scanning pack...", worker)

    def render_result(self, result: ScanResult) -> None:
        pinned_installed = result.always_enabled_ids & result.installed_ids
        disabled_extra_ids = [item_id for item_id in result.extra_ids if item_id not in result.always_enabled_ids]
        self.progress(
            f"Ready: {len(result.ready_ids)} loadable, {len(result.missing_ids)} missing, "
            f"{len(result.unregistered_ids)} need SteamCMD local download, "
            f"{len(disabled_extra_ids)} disabled extras, {len(pinned_installed)} always enabled."
        )
        ready_package_ids = {
            result.installed_package_ids[item_id]
            for item_id in result.ready_ids
            if item_id in result.installed_package_ids
        }
        self.progress(f"ModsConfig writer can activate {len(ready_package_ids)} unique Ferny package IDs.")
        rows: list[tuple[str, str, str, str | None, QuarantinedMod | None]] = []
        for item_id in result.missing_ids:
            item = result.required[item_id]
            rows.append(("Missing", item.collection, f"{item_id}  {item.title}", item_id, None))
        for item_id in result.unregistered_ids:
            item = result.required[item_id]
            rows.append(("Needs SteamCMD", item.collection, f"{item_id}  {item.title}", item_id, None))
        for item_id in result.extra_ids:
            state = "Always Enabled" if item_id in result.always_enabled_ids else "Disabled"
            source = "Local" if item_id in result.local_steamcmd_ids else "Workshop"
            package_id = result.installed_package_ids.get(item_id, "")
            label = f"{item_id}  {package_id}" if package_id else item_id
            rows.append((state, source, label, item_id, None))
        for item_id in result.ready_ids[:300]:
            item = result.required[item_id]
            source = "Local" if item_id in result.local_steamcmd_ids else item.collection
            state = "Always Enabled" if item_id in result.always_enabled_ids else "Enabled"
            rows.append((state, source, f"{item_id}  {item.title}", item_id, None))
        if len(result.ready_ids) > 300:
            rows.append(("Enabled", "...", f"{len(result.ready_ids) - 300} more installed required mods hidden", None, None))
        self.set_mod_rows(rows)

    def show_quarantine(self) -> None:
        workshop_path = Path(self.workshop_path.get())
        quarantined = find_quarantined_mods(workshop_path)
        self.progress(f"Quarantine contains {len(quarantined)} mod folders.")
        if not quarantined:
            self.set_mod_rows([("Disabled", "-", "No quarantined mods found.", None, None)])
            return
        rows: list[tuple[str, str, str, str | None, QuarantinedMod | None]] = []
        for mod in quarantined:
            label = f"{mod.item_id}"
            if mod.package_id:
                label += f"  {mod.package_id}"
            rows.append(("Disabled", mod.quarantine_path.name, label, mod.item_id, mod))
        self.set_mod_rows(rows)

    def always_enable_selected(self) -> None:
        selected = self.selected_item_ids()
        if not selected:
            messagebox.showinfo("Select mods", "Select one or more mods in the table first.")
            return
        always_enabled = load_always_enabled_ids()
        always_enabled.update(selected)
        save_always_enabled_ids(always_enabled)
        self.progress(f"Always enabled {len(selected)} selected mod(s).")
        if self.current_result:
            self.current_result.always_enabled_ids = always_enabled
            self.render_result(self.current_result)

    def disable_selected(self) -> None:
        selected = self.selected_item_ids()
        if not selected:
            messagebox.showinfo("Select mods", "Select one or more mods in the table first.")
            return
        always_enabled = load_always_enabled_ids()
        removed = selected & always_enabled
        always_enabled.difference_update(selected)
        save_always_enabled_ids(always_enabled)
        self.progress(f"Removed {len(removed)} mod(s) from Always Enabled.")
        if self.current_result:
            self.current_result.always_enabled_ids = always_enabled
            self.render_result(self.current_result)

    def freeze_current_setup(self) -> None:
        if rimworld_is_running():
            messagebox.showinfo("Close RimWorld", "Close RimWorld before freezing a setup so config and mod files can be copied cleanly.")
            return
        result = self.current_result
        if not result:
            messagebox.showinfo("Scan first", "Run a scan before freezing a setup.")
            return
        if result.missing_ids or result.unregistered_ids:
            messagebox.showinfo("Setup not ready", "Download missing/non-loadable mods before freezing this setup.")
            return
        default_name = f"Frozen {timestamp()}"
        name = simpledialog.askstring("Freeze Current Setup", "Frozen profile name:", initialvalue=default_name)
        if name is None:
            return
        profile_name = safe_profile_name(name)
        if not profile_name:
            messagebox.showinfo("Name required", "Enter a profile name.")
            return

        def worker() -> None:
            try:
                path = create_frozen_profile(result, profile_name, self.progress)
                self.progress(f"Frozen profile created: {path}")
                self.after(0, self.refresh_frozen_profiles)
                self.after(0, lambda: self.frozen_profile.set(profile_name))
            except (RuntimeError, OSError) as exc:
                self.progress(f"Freeze failed: {exc}")
                error = str(exc)
                self.after(0, lambda: messagebox.showerror("Freeze failed", error))

        self.run_busy_worker("Freezing setup...", worker)

    def play_frozen(self) -> None:
        if rimworld_is_running():
            messagebox.showinfo("Close RimWorld", "Close RimWorld before playing a frozen profile so live mod/config files can be staged safely.")
            return
        self.refresh_frozen_profiles()
        profile_name = self.frozen_profile.get().strip()
        if not profile_name:
            messagebox.showinfo("No frozen profile", "Create a frozen profile first with Freeze Current Setup.")
            return
        if profile_name not in frozen_profile_names():
            messagebox.showinfo("Select frozen profile", "Select a frozen profile from the Frozen Profile dropdown first.")
            return

        def worker() -> None:
            try:
                self.progress(f"Playing frozen profile: {profile_name}")
                profile_ids = stage_frozen_profile(
                    profile_name,
                    Path(self.workshop_path.get()),
                    Path(self.local_mods_path.get()),
                    Path(self.mods_config_path.get()),
                    self.progress,
                )
                result = self.scan_paths(self.progress)
                result.always_enabled_ids = set(profile_ids)
                self.current_result = result
                self.after(0, lambda: self.render_result(result))
                write_mods_config(result, self.progress)
                self.progress("Launching RimWorld through Steam with frozen profile...")
                webbrowser.open(STEAM_RUN_RIMWORLD)
            except (RuntimeError, OSError, urllib.error.URLError) as exc:
                self.progress(f"Play Frozen failed: {exc}")
                error = str(exc)
                self.after(0, lambda: messagebox.showerror("Play Frozen failed", error))

        self.run_busy_worker("Staging frozen profile...", worker)

    def restore_live_setup(self) -> None:
        def worker() -> None:
            try:
                restore_staged_live(self.progress)
                result = self.scan_paths(self.progress)
                self.current_result = result
                self.after(0, lambda: self.render_result(result))
                self.progress("Live setup restored.")
            except (RuntimeError, OSError, urllib.error.URLError) as exc:
                self.progress(f"Restore live failed: {exc}")
                error = str(exc)
                self.after(0, lambda: messagebox.showerror("Restore live failed", error))

        self.run_busy_worker("Restoring live setup...", worker)

    def open_quarantine_folder(self) -> None:
        workshop_path = Path(self.workshop_path.get())
        quarantines = [p for p in sorted(workshop_path.glob(".progressor_quarantine_*"), key=lambda p: p.name, reverse=True) if p.is_dir()]
        if not quarantines:
            messagebox.showinfo("No quarantine", "No .progressor_quarantine folders were found.")
            return
        os.startfile(quarantines[0])

    def quarantine_extra(self) -> None:
        result = self.current_result
        if not result:
            messagebox.showinfo("Scan first", "Run a scan before quarantining mods.")
            return
        if not result.extra_ids:
            messagebox.showinfo("No extras", "No extra local Workshop mods were found.")
            return
        if not messagebox.askyesno(
            "Quarantine extra mods",
            f"Move {len(result.extra_ids)} extra mod folders into a .progressor_quarantine folder?",
        ):
            return

        def worker() -> None:
            try:
                path = quarantine_mods(result.workshop_path, result.extra_ids, self.progress)
                self.progress(f"Quarantine complete: {path}")
                self.after(0, self.start_scan)
            except OSError as exc:
                self.progress(f"Quarantine failed: {exc}")
                error = str(exc)
                self.after(0, lambda: messagebox.showerror("Quarantine failed", error))

        self.run_busy_worker("Quarantining mods...", worker)

    def restore_selected_quarantine(self) -> None:
        selected = [self.quarantined_rows[item] for item in self.tree.selection() if item in self.quarantined_rows]
        if not selected:
            messagebox.showinfo("Select quarantined mods", "Click Show Quarantine, select one or more quarantined mods, then restore.")
            return
        if not messagebox.askyesno(
            "Restore selected mods",
            f"Restore {len(selected)} quarantined mod folder(s) back into the Workshop folder?",
        ):
            return

        def worker() -> None:
            try:
                restored = restore_quarantined_mods(Path(self.workshop_path.get()), selected, self.progress)
                self.progress(f"Restored {restored} quarantined mods.")
                self.after(0, self.show_quarantine)
            except OSError as exc:
                self.progress(f"Restore failed: {exc}")
                error = str(exc)
                self.after(0, lambda: messagebox.showerror("Restore failed", error))

        self.run_busy_worker("Restoring quarantined mods...", worker)

    def update_steamcmd_mods(self) -> None:
        result = self.current_result
        if not result:
            messagebox.showinfo("Scan first", "Run a scan before updating SteamCMD mods.")
            return
        local_targets = steamcmd_update_target_ids(result)
        if not local_targets:
            messagebox.showinfo("No SteamCMD mods", "No Ferny mods are currently installed through the local SteamCMD path.")
            return

        def worker() -> None:
            old_env = os.environ.get("STEAMCMD")
            try:
                steamcmd = self.steamcmd_path.get().strip()
                if steamcmd:
                    os.environ["STEAMCMD"] = steamcmd
                resolved_steamcmd = find_steamcmd()
                if not resolved_steamcmd:
                    raise RuntimeError(
                        "steamcmd.exe was not found. Install SteamCMD, place steamcmd.exe next to this app, "
                        "or set a STEAMCMD environment variable pointing to it."
                    )
                self.progress(f"Checking {len(local_targets)} local SteamCMD mod(s) for updates...")
                outdated, unknown = steamcmd_outdated_ids(result, resolved_steamcmd.parent, self.progress)
                if not outdated:
                    message = f"No SteamCMD mod updates found. {len(local_targets) - len(unknown)} mod(s) were checked."
                    if unknown:
                        message += f" {len(unknown)} mod(s) could not be compared because update metadata was missing."
                    self.progress(message)
                    self.after(0, lambda: messagebox.showinfo("No updates", message))
                    return

                preview = "\n".join(
                    f"- {item_id} {result.required[item_id].title}".strip()
                    for item_id in outdated[:12]
                )
                if len(outdated) > 12:
                    preview += f"\n...and {len(outdated) - 12} more"
                prompt = f"Steam reports {len(outdated)} newer SteamCMD mod(s).\n\n{preview}\n\nUpdate only these mods?"
                if unknown:
                    prompt += f"\n\n{len(unknown)} installed SteamCMD mod(s) could not be compared and will be skipped."
                should_update = threading.Event()
                prompt_done = threading.Event()

                def ask() -> None:
                    if messagebox.askyesno("Update SteamCMD mods", prompt):
                        should_update.set()
                    prompt_done.set()

                self.after(0, ask)
                while not prompt_done.wait(0.1):
                    pass
                if not should_update.is_set():
                    self.progress("SteamCMD update cancelled.")
                    return
                run_steamcmd_downloads(result, self.progress, targets=outdated)
                self.progress("SteamCMD update step complete. Scanning again...")
                fresh_result = self.scan_paths(self.progress)
                self.current_result = fresh_result
                self.after(0, lambda: self.render_result(fresh_result))
            except (RuntimeError, OSError, urllib.error.URLError) as exc:
                self.progress(f"Update failed: {exc}")
                error = str(exc)
                self.after(0, lambda: messagebox.showerror("Update failed", error))
            finally:
                if old_env is None:
                    os.environ.pop("STEAMCMD", None)
                else:
                    os.environ["STEAMCMD"] = old_env

        self.run_busy_worker("Checking SteamCMD updates...", worker)

    def download_missing(self) -> None:
        result = self.current_result
        if not result:
            messagebox.showinfo("Scan first", "Run a scan before downloading missing mods.")
            return
        targets = download_target_ids(result)
        if not targets:
            messagebox.showinfo("Nothing to download", "All required mods are already loadable.")
            return
        if not messagebox.askyesno(
            "Download missing mods",
            f"Ask SteamCMD to download or validate {len(targets)} item(s) into RimWorld's local Mods folder? "
            "Progression Launcher will link SteamCMD's RimWorld content folder to the Local Mods path first.",
        ):
            return

        def worker() -> None:
            try:
                steamcmd = self.steamcmd_path.get().strip()
                old_env = os.environ.get("STEAMCMD")
                if steamcmd:
                    os.environ["STEAMCMD"] = steamcmd
                run_steamcmd_downloads(result, self.progress)
                self.progress("Download step complete. Scanning again...")
                fresh_result = self.scan_paths(self.progress)
                self.current_result = fresh_result
                self.after(0, lambda: self.render_result(fresh_result))
                if self.auto_activate_after_download.get():
                    if fresh_result.missing_ids:
                        self.progress(f"Auto-activate skipped: {len(fresh_result.missing_ids)} mods are still missing.")
                    else:
                        if fresh_result.unregistered_ids:
                            self.progress(
                                f"Auto-activate skipped: {len(fresh_result.unregistered_ids)} mods still need SteamCMD local download."
                            )
                        else:
                            write_mods_config(fresh_result, self.progress)
            except (RuntimeError, OSError) as exc:
                self.progress(f"Download failed: {exc}")
                error = str(exc)
                self.after(0, lambda: messagebox.showerror("Download failed", error))
            finally:
                if old_env is None:
                    os.environ.pop("STEAMCMD", None)
                else:
                    os.environ["STEAMCMD"] = old_env

        self.run_busy_worker("Downloading missing mods...", worker)

    def write_config(self) -> None:
        result = self.current_result
        if not result:
            messagebox.showinfo("Scan first", "Run a scan before writing ModsConfig.xml.")
            return
        if result.missing_ids:
            proceed = messagebox.askyesno(
                "Missing mods",
                f"{len(result.missing_ids)} required mods are missing. Write a config using only installed required mods?",
            )
            if not proceed:
                return

        def worker() -> None:
            try:
                if result.unregistered_ids:
                    raise RuntimeError(
                        f"{len(result.unregistered_ids)} mods are present only as non-loadable Workshop folders. "
                        "Run Download Missing so SteamCMD installs them into the Local Mods folder, then activate again."
                    )
                path = write_mods_config(result, self.progress)
                self.after(0, lambda: messagebox.showinfo("ModsConfig written", f"Updated {path}"))
            except (RuntimeError, OSError) as exc:
                self.progress(f"Write failed: {exc}")
                error = str(exc)
                self.after(0, lambda: messagebox.showerror("Write failed", error))

        self.run_busy_worker("Writing mod config...", worker)


def main() -> int:
    if sys.platform != "win32":
        print("Progression Launcher is Windows-first right now. It can scan on other OSes, but paths may need manual setup.")
    app = ProgressorApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
