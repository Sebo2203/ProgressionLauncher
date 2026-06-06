from __future__ import annotations

import datetime as _dt
import concurrent.futures
import hashlib
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
import zipfile
from dataclasses import dataclass
from pathlib import Path
from tkinter import BooleanVar, filedialog, messagebox, simpledialog, ttk
import tkinter as tk


APP_ID = "294100"
APP_NAME = "Progression Launcher"
APP_VERSION = "0.4.0"
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
STEAMCMD_DOWNLOAD_URL = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"


def app_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Local"
    path = root / "ProgressionLauncher"
    path.mkdir(parents=True, exist_ok=True)
    return path


def asset_path(name: str) -> Path:
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    return bundle_root / name


def executable_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


CACHE_PATH = app_data_dir() / "collection_cache.json"
BUNDLED_CACHE_PATH = asset_path("collection_cache.json")
ALWAYS_ENABLED_PATH = app_data_dir() / "always_enabled.json"
DISABLED_MODS_PATH = app_data_dir() / "disabled_mods.json"
FROZEN_PROFILES_PATH = app_data_dir() / "frozen_profiles"
STAGING_STATE_PATH = app_data_dir() / "staging_state.json"
SETTINGS_PATH = app_data_dir() / "settings.json"
LOCAL_METADATA_CACHE_PATH = app_data_dir() / "local_metadata_cache.json"
SORT_CACHE_PATH = app_data_dir() / "sort_cache.json"
STEAM_API_SEMAPHORE = threading.BoundedSemaphore(4)


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
    disabled_ids: set[str]
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


def resolved_executable_path(raw_path: str | Path | None) -> Path | None:
    if not raw_path:
        return None
    text = os.path.expandvars(os.path.expanduser(str(raw_path).strip().strip('"')))
    if not text:
        return None
    candidate = Path(text)
    if candidate.is_dir():
        candidate /= "steamcmd.exe"
    try:
        candidate = candidate.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if candidate.is_file() and candidate.name.lower() == "steamcmd.exe":
        return candidate
    return None


def steamcmd_candidates() -> list[Path]:
    env_path = os.environ.get("STEAMCMD")
    candidates: list[Path] = []
    if env_path:
        candidates.append(Path(env_path))
    which = shutil.which("steamcmd") or shutil.which("steamcmd.exe")
    if which:
        candidates.append(Path(which))
    home = Path.home()
    local_app_data = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
    program_data = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
    candidates.extend(
        [
            executable_dir() / "steamcmd.exe",
            executable_dir() / "steamcmd" / "steamcmd.exe",
            app_data_dir() / "SteamCMD" / "steamcmd.exe",
            home / "steamcmd" / "steamcmd.exe",
            home / "SteamCMD" / "steamcmd.exe",
            local_app_data / "SteamCMD" / "steamcmd.exe",
            local_app_data / "Programs" / "SteamCMD" / "steamcmd.exe",
            home / "scoop" / "apps" / "steamcmd" / "current" / "steamcmd.exe",
            program_data / "chocolatey" / "lib" / "steamcmd" / "tools" / "steamcmd.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Steam" / "steamcmd.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Steam" / "steam" / "steamcmd.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "SteamCMD" / "steamcmd.exe",
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Steam" / "steamcmd.exe",
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Steam" / "steam" / "steamcmd.exe",
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "SteamCMD" / "steamcmd.exe",
            Path(r"C:\steamcmd\steamcmd.exe"),
        ]
    )
    return candidates


def find_steamcmd() -> Path | None:
    seen: set[str] = set()
    for candidate in steamcmd_candidates():
        key = os.path.normcase(os.path.abspath(str(candidate)))
        if key in seen:
            continue
        seen.add(key)
        resolved = resolved_executable_path(candidate)
        if resolved:
            return resolved
    return None


def install_steamcmd(progress) -> Path:
    install_dir = app_data_dir() / "SteamCMD"
    executable = install_dir / "steamcmd.exe"
    install_dir.mkdir(parents=True, exist_ok=True)
    progress("Downloading SteamCMD from Valve...")
    request = urllib.request.Request(
        STEAMCMD_DOWNLOAD_URL,
        headers={"User-Agent": f"{APP_NAME}/SteamCMD installer"},
    )
    archive_path: Path | None = None
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as archive:
                shutil.copyfileobj(response, archive)
                archive_path = Path(archive.name)
        progress("Installing SteamCMD...")
        with zipfile.ZipFile(archive_path) as archive:
            members = archive.infolist()
            for member in members:
                destination = (install_dir / member.filename).resolve()
                if install_dir.resolve() not in destination.parents and destination != install_dir.resolve():
                    raise RuntimeError("Valve's SteamCMD archive contained an unsafe path.")
            archive.extractall(install_dir)
    finally:
        if archive_path:
            archive_path.unlink(missing_ok=True)
    resolved = resolved_executable_path(executable)
    if not resolved:
        raise RuntimeError("SteamCMD downloaded, but steamcmd.exe was not found after extraction.")
    progress(f"SteamCMD installed at {resolved}")
    return resolved


def find_or_install_steamcmd(progress) -> Path:
    existing = find_steamcmd()
    if existing:
        return existing
    progress("SteamCMD is not installed or could not be detected; installing it from Valve...")
    return install_steamcmd(progress)


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
    with STEAM_API_SEMAPHORE:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))


def fetch_remote_update_times(
    item_ids: list[str],
    progress,
    progress_count=None,
    unavailable_out: set[str] | None = None,
) -> dict[str, int]:
    update_times: dict[str, int] = {}
    unavailable_ids = unavailable_out if unavailable_out is not None else set()
    requested_ids = list(dict.fromkeys(item_ids))
    total = len(requested_ids)

    def report_count() -> None:
        checked = len(set(update_times) | unavailable_ids)
        remaining = max(total - checked, 0)
        progress(f"Steam metadata: {checked}/{total} checked, {remaining} left.")
        if progress_count is not None:
            progress_count(checked, total)

    def fetch_batches(pending_ids: list[str], batch_size: int, retry_number: int = 0) -> None:
        for index in range(0, len(pending_ids), batch_size):
            batch = pending_ids[index : index + batch_size]
            params = {"itemcount": str(len(batch))}
            for batch_index, item_id in enumerate(batch):
                params[f"publishedfileids[{batch_index}]"] = item_id
            label = "Retrying" if retry_number else "Checking"
            checked = len(set(update_times) | unavailable_ids)
            progress(
                f"{label} Steam metadata for {len(batch)} mod(s); "
                f"{max(total - checked, 0)} left to check."
            )
            try:
                published_response = post_steam_api(PUBLISHED_FILE_DETAILS_URL, params)
            except urllib.error.URLError as exc:
                progress(f"Steam metadata request failed for this batch: {exc}")
                continue
            file_details = published_response.get("response", {}).get("publishedfiledetails", [])
            for detail in file_details:
                item_id = str(detail.get("publishedfileid", ""))
                if int(detail.get("result", 0)) != 1:
                    if item_id in requested_ids:
                        unavailable_ids.add(item_id)
                    continue
                raw_time = detail.get("time_updated") or detail.get("timeupdated") or 0
                try:
                    update_times[item_id] = int(raw_time)
                except (TypeError, ValueError):
                    continue
            report_count()
            time.sleep(0.2)

    report_count()
    fetch_batches(requested_ids, 100)
    for retry_number, batch_size in enumerate((25, 10), start=1):
        missing_ids = [
            item_id
            for item_id in requested_ids
            if item_id not in update_times and item_id not in unavailable_ids
        ]
        if not missing_ids:
            break
        progress(
            f"Steam omitted metadata for {len(missing_ids)} mod(s); "
            f"retrying in batches of {batch_size}."
        )
        time.sleep(0.8 * retry_number)
        fetch_batches(missing_ids, batch_size, retry_number)
    report_count()
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


def fetch_collection_items_api(
    collection_name: str,
    collection_id: str,
    cached_items: dict[str, WorkshopItem] | None = None,
) -> list[WorkshopItem]:
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
    cached_items = cached_items or {}
    titles: dict[str, str] = {}
    batches = [child_ids[index : index + 100] for index in range(0, len(child_ids), 100)]

    def fetch_title_batch(batch: list[str]) -> dict[str, str]:
        params = {"itemcount": str(len(batch))}
        for batch_index, item_id in enumerate(batch):
            params[f"publishedfileids[{batch_index}]"] = item_id
        published_response = post_steam_api(PUBLISHED_FILE_DETAILS_URL, params)
        file_details = published_response.get("response", {}).get("publishedfiledetails", [])
        batch_titles: dict[str, str] = {}
        for detail in file_details:
            item_id = str(detail.get("publishedfileid", ""))
            if int(detail.get("result", 0)) == 1 and int(detail.get("consumer_app_id", 0)) == int(APP_ID):
                batch_titles[item_id] = str(detail.get("title", "")).strip()
        return batch_titles

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(fetch_title_batch, batch) for batch in batches]
        for future in concurrent.futures.as_completed(futures):
            titles.update(future.result())

    for item_id in child_ids:
        title = titles.get(item_id, "")
        if not title and item_id in cached_items:
            title = cached_items[item_id].title
        items.append(WorkshopItem(collection_name, item_id, title))
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


def load_disabled_ids() -> set[str]:
    if not DISABLED_MODS_PATH.exists():
        return set()
    try:
        payload = json.loads(DISABLED_MODS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    ids = payload.get("item_ids", [])
    return {str(item_id) for item_id in ids if str(item_id).isdigit()}


def save_disabled_ids(item_ids: set[str]) -> None:
    DISABLED_MODS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"item_ids": sorted(item_ids, key=int)}
    DISABLED_MODS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_settings() -> dict[str, object]:
    if not SETTINGS_PATH.exists():
        return {}
    try:
        payload = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    settings: dict[str, object] = {}
    for key in {"workshop_path", "local_mods_path", "mods_config_path", "steamcmd_path"}:
        value = payload.get(key)
        if value:
            settings[key] = str(value)
    settings["exclude_cosmetics"] = payload.get("exclude_cosmetics") is True
    settings["auto_update_on_launch"] = payload.get("auto_update_on_launch") is True
    return settings


def save_settings(settings: dict[str, object]) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def cached_cosmetic_ids() -> set[str]:
    return {
        item_id
        for item_id, item in load_collection_cache().items()
        if item.collection == "Cosmetics"
    }


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
    cached = load_collection_cache()
    try:
        def fetch_collection(entry: tuple[str, str]) -> tuple[str, list[WorkshopItem]]:
            name, collection_id = entry
            progress(f"Fetching {name} collection via Steam API...")
            return name, fetch_collection_items_api(name, collection_id, cached)

        fetched: dict[str, list[WorkshopItem]] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(COLLECTIONS)) as executor:
            futures = [executor.submit(fetch_collection, entry) for entry in COLLECTIONS.items()]
            for future in concurrent.futures.as_completed(futures):
                name, items = future.result()
                if not items:
                    raise RuntimeError(f"No Workshop items found in {name}.")
                fetched[name] = items
                progress(f"{name}: {len(items)} items")

        for name in COLLECTIONS:
            items = fetched[name]
            for item in items:
                required[item.item_id] = item
        progress("Fetched live Workshop metadata; cache is reserved for missing titles or Steam outages.")
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


_local_metadata_cache: dict[str, dict] | None = None
_local_metadata_cache_dirty = False
_local_metadata_cache_hits = 0


def load_local_metadata_cache() -> dict[str, dict]:
    global _local_metadata_cache
    if _local_metadata_cache is not None:
        return _local_metadata_cache
    try:
        payload = json.loads(LOCAL_METADATA_CACHE_PATH.read_text(encoding="utf-8"))
        entries = payload.get("entries", {})
        _local_metadata_cache = entries if isinstance(entries, dict) else {}
    except (OSError, json.JSONDecodeError):
        _local_metadata_cache = {}
    return _local_metadata_cache


def save_local_metadata_cache() -> None:
    global _local_metadata_cache_dirty
    if not _local_metadata_cache_dirty:
        return
    LOCAL_METADATA_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_METADATA_CACHE_PATH.write_text(
        json.dumps({"entries": load_local_metadata_cache()}, indent=2),
        encoding="utf-8",
    )
    _local_metadata_cache_dirty = False


def cached_mod_metadata(mod_dir: Path, item_id: str) -> ModMetadata | None:
    global _local_metadata_cache_dirty, _local_metadata_cache_hits
    about_path = mod_dir / "About" / "About.xml"
    if not about_path.exists():
        return None
    try:
        stat = about_path.stat()
    except OSError:
        return read_mod_metadata(mod_dir, item_id)
    signature = [stat.st_mtime_ns, stat.st_size]
    cache = load_local_metadata_cache()
    key = str(about_path.resolve())
    cached = cache.get(key)
    if isinstance(cached, dict) and cached.get("signature") == signature:
        _local_metadata_cache_hits += 1
        metadata = cached.get("metadata")
        if not isinstance(metadata, dict):
            return None
        return ModMetadata(
            item_id=item_id,
            package_id=str(metadata.get("package_id", "")),
            name=str(metadata.get("name", item_id)),
            dependencies=tuple(str(value) for value in metadata.get("dependencies", [])),
            load_after=tuple(str(value) for value in metadata.get("load_after", [])),
            load_before=tuple(str(value) for value in metadata.get("load_before", [])),
        )

    metadata = read_mod_metadata(mod_dir, item_id)
    cache[key] = {
        "signature": signature,
        "metadata": (
            {
                "package_id": metadata.package_id,
                "name": metadata.name,
                "dependencies": list(metadata.dependencies),
                "load_after": list(metadata.load_after),
                "load_before": list(metadata.load_before),
            }
            if metadata
            else None
        ),
    }
    _local_metadata_cache_dirty = True
    return metadata


def read_installed_metadata(item_paths: dict[str, Path], item_ids: list[str]) -> dict[str, ModMetadata]:
    metadata: dict[str, ModMetadata] = {}
    for item_id in item_ids:
        mod_path = item_paths.get(item_id)
        if not mod_path:
            continue
        meta = cached_mod_metadata(mod_path, item_id)
        if meta and meta.package_id not in metadata:
            metadata[meta.package_id] = meta
    save_local_metadata_cache()
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
        metadata = cached_mod_metadata(child, child.name)
        if metadata and metadata.package_id:
            package_ids[child.name] = metadata.package_id
    save_local_metadata_cache()
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


def scan_with_required(
    required_snapshot: dict[str, WorkshopItem],
    workshop_path: Path,
    local_mods_path: Path,
    mods_config_path: Path,
    progress,
    exclude_cosmetics: bool = False,
) -> ScanResult:
    cache_hits_before = _local_metadata_cache_hits
    required = dict(required_snapshot)
    cosmetic_ids = {
        item_id
        for item_id, item in required.items()
        if item.collection == "Cosmetics"
    }
    if exclude_cosmetics:
        required = {
            item_id: item
            for item_id, item in required.items()
            if item_id not in cosmetic_ids
        }
        progress(f"Cosmetics excluded: {len(cosmetic_ids)} pack items will not be downloaded or enabled.")
    progress("Scanning local Workshop folder...")
    workshop_ids, workshop_package_ids, workshop_paths = scan_mod_folder(workshop_path)
    progress("Scanning RimWorld local Mods folder...")
    local_ids, local_package_ids, local_paths = scan_mod_folder(local_mods_path)
    reused_metadata = _local_metadata_cache_hits - cache_hits_before
    if reused_metadata:
        progress(f"Reused stat-verified metadata for {reused_metadata} unchanged local mod files.")
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
    disabled_ids = load_disabled_ids()
    disabled_ids.difference_update(always_enabled_ids)
    if exclude_cosmetics:
        always_enabled_ids.difference_update(cosmetic_ids)
        disabled_ids.update(cosmetic_ids & installed_ids)
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
        disabled_ids=disabled_ids,
        workshop_path=workshop_path,
        local_mods_path=local_mods_path,
        mods_config_path=mods_config_path,
    )


def scan(
    workshop_path: Path,
    local_mods_path: Path,
    mods_config_path: Path,
    progress,
    exclude_cosmetics: bool = False,
) -> ScanResult:
    return scan_with_required(
        fetch_required_items(progress),
        workshop_path,
        local_mods_path,
        mods_config_path,
        progress,
        exclude_cosmetics,
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
        *[
            item_id
            for item_id in result.ready_ids
            if item_id not in result.disabled_ids or item_id in result.always_enabled_ids
        ],
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


def parse_workshop_update_times(manifest_path: Path) -> dict[str, int]:
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


def parse_steamcmd_update_times(steamcmd_root: Path) -> dict[str, int]:
    return parse_workshop_update_times(steamcmd_acf_path(steamcmd_root))


def steam_client_acf_path(workshop_path: Path) -> Path:
    return workshop_path.parents[1] / f"appworkshop_{APP_ID}.acf"


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


def steam_workshop_update_target_ids(result: ScanResult) -> list[str]:
    return [
        item_id
        for item_id in result.required_order
        if item_id in result.steam_registered_ids and item_id not in result.local_steamcmd_ids
    ]


def workshop_outdated_ids(
    item_ids: list[str],
    manifest_path: Path,
    remote_times: dict[str, int],
    fallback_manifest_paths: list[Path] | None = None,
) -> tuple[list[str], list[str]]:
    local_times = parse_workshop_update_times(manifest_path)
    for fallback_path in fallback_manifest_paths or []:
        fallback_times = parse_workshop_update_times(fallback_path)
        for item_id, update_time in fallback_times.items():
            local_times.setdefault(item_id, update_time)
    outdated: list[str] = []
    unknown: list[str] = []
    for item_id in item_ids:
        local_time = local_times.get(item_id)
        remote_time = remote_times.get(item_id)
        if local_time is None or remote_time is None:
            unknown.append(item_id)
        elif remote_time > local_time:
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


def run_steamcmd_downloads(
    result: ScanResult,
    progress,
    targets: list[str] | None = None,
    progress_count=None,
) -> Path:
    steamcmd = find_or_install_steamcmd(progress)
    targets = targets or download_target_ids(result)
    if not targets:
        raise RuntimeError("There are no SteamCMD mods to download or validate.")

    targets = list(dict.fromkeys(targets))
    total = len(targets)
    completed_ids: set[str] = set()
    failed_item_ids: set[str] = set()

    def report_count() -> None:
        completed = len(completed_ids)
        remaining = max(total - completed, 0)
        progress(f"SteamCMD progress: {completed}/{total} complete, {remaining} remaining.")
        if progress_count is not None:
            progress_count(completed, total)

    progress(f"Using SteamCMD: {steamcmd}")
    report_count()
    steamcmd_root = steamcmd.parent
    relocate_unregistered_workshop_mods(result, targets, progress)
    downloaded_root = prepare_steamcmd_local_download_root(steamcmd_root, result.local_mods_path, progress)

    def loadable_ids(item_ids: list[str]) -> set[str]:
        return {item_id for item_id in item_ids if read_package_id(downloaded_root / item_id)}

    def execute_batches(item_ids: list[str], retry: bool = False) -> bool:
        detected_error = False
        batch_size = 200
        for index in range(0, len(item_ids), batch_size):
            batch = item_ids[index : index + batch_size]
            action = "Retrying with validation" if retry else "Downloading"
            progress(f"{action} batch {index // batch_size + 1}: {len(batch)} mods...")
            script_lines = ["@ShutdownOnFailedCommand 0", "@NoPromptForPassword 1", "login anonymous"]
            validate_suffix = " validate" if retry else ""
            script_lines.extend(
                f"workshop_download_item {APP_ID} {item_id}{validate_suffix}"
                for item_id in batch
            )
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
                    upper_line = line.upper()
                    failure_markers = ("ERROR!", "FAILED", "FAILURE", "NO CONNECTION", "TIMED OUT", "TIMEOUT")
                    line_failed = any(marker in upper_line for marker in failure_markers)
                    if "SUCCESS. DOWNLOADED ITEM" in upper_line or line_failed:
                        progress(line)
                    if line_failed:
                        detected_error = True
                        item_match = re.search(r"\bitem\s+(\d+)\b", line, re.IGNORECASE)
                        if item_match and item_match.group(1) in targets:
                            failed_item_ids.add(item_match.group(1))
                    match = re.search(r"Success\.\s+Downloaded item\s+(\d+)", line, re.IGNORECASE)
                    if match and match.group(1) in targets and match.group(1) not in completed_ids:
                        completed_ids.add(match.group(1))
                        report_count()
                return_code = process.wait()
                if return_code != 0:
                    detected_error = True
                    progress(f"SteamCMD exited with code {return_code}; affected mods will be checked.")
                completed_ids.update(loadable_ids(batch))
                report_count()
            finally:
                try:
                    script_path.unlink()
                except OSError:
                    pass
        return detected_error

    error_detected = execute_batches(targets)
    if error_detected:
        loadable = loadable_ids(targets)
        retry_ids = [
            item_id
            for item_id in targets
            if item_id in failed_item_ids or item_id not in loadable
        ]
        if retry_ids:
            progress(
                f"SteamCMD reported an error. Retrying {len(retry_ids)} affected, missing, or incomplete mod(s)..."
            )
            execute_batches(retry_ids, retry=True)
            loadable = loadable_ids(targets)
            incomplete = [item_id for item_id in targets if item_id not in loadable]
            if incomplete:
                preview = ", ".join(incomplete[:10])
                suffix = f" and {len(incomplete) - 10} more" if len(incomplete) > 10 else ""
                raise RuntimeError(
                    f"{len(incomplete)} SteamCMD mod(s) are still missing or incomplete after retry: "
                    f"{preview}{suffix}. Check the connection and run Download Missing again."
                )
        else:
            progress("SteamCMD reported an error, but all requested mods passed the presence check.")

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
        *[
            item_id
            for item_id in result.ready_ids
            if item_id not in result.disabled_ids or item_id in result.always_enabled_ids
        ],
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


def sort_cache_key(result: ScanResult) -> str:
    active_item_ids = [
        *[
            item_id
            for item_id in result.ready_ids
            if item_id not in result.disabled_ids or item_id in result.always_enabled_ids
        ],
        *[
            item_id
            for item_id in sorted(result.always_enabled_ids, key=int)
            if item_id in result.installed_ids and item_id not in result.ready_ids
        ],
    ]
    about_signatures: list[list[object]] = []
    for item_id in active_item_ids:
        mod_path = result.item_paths.get(item_id)
        about_path = mod_path / "About" / "About.xml" if mod_path else None
        try:
            stat = about_path.stat() if about_path else None
        except OSError:
            stat = None
        about_signatures.append(
            [
                item_id,
                result.installed_package_ids.get(item_id, ""),
                stat.st_mtime_ns if stat else 0,
                stat.st_size if stat else 0,
            ]
        )
    try:
        config_digest = hashlib.sha256(result.mods_config_path.read_bytes()).hexdigest()
    except OSError:
        config_digest = ""
    payload = {
        "required_order": result.required_order,
        "active_item_ids": active_item_ids,
        "always_enabled_ids": sorted(result.always_enabled_ids, key=int),
        "disabled_ids": sorted(result.disabled_ids, key=int),
        "about_signatures": about_signatures,
        "config_digest": config_digest,
    }
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_cached_sort_result(result: ScanResult) -> SortResult | None:
    try:
        payload = json.loads(SORT_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("key") != sort_cache_key(result):
        return None
    sort_data = payload.get("sort_result")
    if not isinstance(sort_data, dict):
        return None
    try:
        return SortResult(
            package_ids=[str(value) for value in sort_data["package_ids"]],
            metadata_count=int(sort_data["metadata_count"]),
            dependency_edges=int(sort_data["dependency_edges"]),
            load_rule_edges=int(sort_data["load_rule_edges"]),
            broken_edges=int(sort_data["broken_edges"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def save_cached_sort_result(result: ScanResult, sort_result: SortResult) -> None:
    payload = {
        "key": sort_cache_key(result),
        "sort_result": {
            "package_ids": sort_result.package_ids,
            "metadata_count": sort_result.metadata_count,
            "dependency_edges": sort_result.dependency_edges,
            "load_rule_edges": sort_result.load_rule_edges,
            "broken_edges": sort_result.broken_edges,
        },
    }
    SORT_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    SORT_CACHE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def get_or_build_sort_result(result: ScanResult, progress=None) -> SortResult:
    cached = load_cached_sort_result(result)
    if cached is not None:
        if progress:
            progress("Reused cached load order; all collection, config, and local metadata signatures match.")
        return cached
    sort_result = build_vanilla_sorted_active_list(result)
    save_cached_sort_result(result, sort_result)
    return sort_result


def write_mods_config(
    result: ScanResult,
    progress,
    sort_result: SortResult | None = None,
) -> Path:
    sort_result = sort_result or get_or_build_sort_result(result, progress)
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
    save_cached_sort_result(result, sort_result)
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
        self.title(f"{APP_NAME} v{APP_VERSION}")
        self.geometry("1580x800")
        self.minsize(1280, 680)
        self.configure(bg="#101418")

        saved_settings = load_settings()
        self.workshop_path = tk.StringVar(
            value=str(saved_settings.get("workshop_path", default_workshop_path()))
        )
        self.local_mods_path = tk.StringVar(
            value=str(saved_settings.get("local_mods_path", default_rimworld_mods_path()))
        )
        self.mods_config_path = tk.StringVar(
            value=str(saved_settings.get("mods_config_path", default_mods_config_path()))
        )
        configured_steamcmd = resolved_executable_path(saved_settings.get("steamcmd_path"))
        detected_steamcmd = configured_steamcmd or find_steamcmd()
        self.steamcmd_path = tk.StringVar(
            value=str(detected_steamcmd or "")
        )
        self.auto_activate_after_download = BooleanVar(value=True)
        self.auto_update_on_launch = BooleanVar(
            value=saved_settings.get("auto_update_on_launch") is True
        )
        self.exclude_cosmetics = BooleanVar(value=saved_settings.get("exclude_cosmetics") is True)
        self.current_result: ScanResult | None = None
        self.current_sort_result: SortResult | None = None
        self.current_rows: list[tuple[str, str, str, str | None, QuarantinedMod | None]] = []
        self.load_order_rows: list[tuple[str, str, str, str | None, QuarantinedMod | None]] = []
        self.table_view = tk.StringVar(value="Mod Differences")
        self.table_title = tk.StringVar(value="Mod Differences")
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
        self.mod_context_menu: tk.Menu | None = None
        self.frozen_frame: ttk.Frame | None = None
        self.frozen_visible = False

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.close_app)

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
        ttk.Label(
            header,
            text=f"v{APP_VERSION}",
            font=("Segoe UI", 11, "bold"),
            foreground="#9fb1ad",
        ).grid(row=0, column=1, sticky="ne", padx=(14, 0), pady=(4, 0))

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
        ttk.Label(paths, text="Steam Workshop Mods").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        workshop_entry = ttk.Entry(paths, textvariable=self.workshop_path)
        workshop_entry.grid(row=0, column=1, sticky="ew", pady=4)
        workshop_entry.bind("<FocusOut>", lambda _event: self.save_configured_paths())
        ttk.Button(paths, text="Browse", command=self.choose_workshop).grid(row=0, column=2, padx=(8, 0), pady=4)
        ttk.Label(paths, text="ModsConfig").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        mods_config_entry = ttk.Entry(paths, textvariable=self.mods_config_path)
        mods_config_entry.grid(row=1, column=1, sticky="ew", pady=4)
        mods_config_entry.bind("<FocusOut>", lambda _event: self.save_configured_paths())
        ttk.Button(paths, text="Browse", command=self.choose_mods_config).grid(row=1, column=2, padx=(8, 0), pady=4)
        ttk.Label(paths, text="Local Mods").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=4)
        local_mods_entry = ttk.Entry(paths, textvariable=self.local_mods_path)
        local_mods_entry.grid(row=2, column=1, sticky="ew", pady=4)
        local_mods_entry.bind("<FocusOut>", lambda _event: self.save_configured_paths())
        ttk.Button(paths, text="Browse", command=self.choose_local_mods).grid(row=2, column=2, padx=(8, 0), pady=4)
        ttk.Label(paths, text="SteamCMD").grid(row=3, column=0, sticky="w", padx=(0, 8), pady=4)
        steamcmd_entry = ttk.Entry(paths, textvariable=self.steamcmd_path)
        steamcmd_entry.grid(row=3, column=1, sticky="ew", pady=4)
        steamcmd_entry.bind("<FocusOut>", lambda _event: self.save_configured_paths())
        ttk.Button(paths, text="Browse", command=self.choose_steamcmd).grid(row=3, column=2, padx=(8, 0), pady=4)
        ttk.Button(paths, text="Install SteamCMD", command=self.install_steamcmd_for_user).grid(
            row=4, column=1, sticky="e", pady=(8, 0)
        )
        ttk.Button(paths, text="Auto Detect Paths", command=self.auto_detect_paths).grid(row=4, column=2, sticky="e", padx=(8, 0), pady=(8, 0))
        toolbar = ttk.Frame(self.advanced_frame)
        toolbar.grid(row=1, column=0, sticky="ew")
        ttk.Button(toolbar, text="Scan Ferny's Pack", command=self.start_scan).pack(side="left")
        ttk.Button(toolbar, text="Download Missing", command=self.download_missing).pack(side="left", padx=6)
        ttk.Button(toolbar, text="Check Mod Updates", command=self.update_steamcmd_mods).pack(side="left", padx=6)
        ttk.Button(toolbar, text="Always Enable Selected", command=self.always_enable_selected).pack(side="left", padx=6)
        ttk.Button(toolbar, text="Reset Selected", command=self.reset_selected).pack(side="left", padx=6)
        ttk.Button(toolbar, text="Always Disable Selected", command=self.disable_selected).pack(side="left", padx=6)
        ttk.Button(toolbar, text="Activate + Vanilla Sort", command=self.write_config).pack(side="left", padx=6)
        self.frozen_button = ttk.Button(toolbar, text="Frozen Profiles", command=self.toggle_frozen_options)
        self.frozen_button.pack(side="left", padx=6)
        ttk.Button(toolbar, text="Launch RimWorld", command=self.advanced_launch).pack(side="right")

        options_row = ttk.Frame(self.advanced_frame)
        options_row.grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Checkbutton(
            options_row,
            text="Auto-enable after download",
            variable=self.auto_activate_after_download,
        ).pack(side="left")
        ttk.Checkbutton(
            options_row,
            text="Auto-update on launch",
            variable=self.auto_update_on_launch,
            command=self.save_configured_paths,
        ).pack(side="left", padx=6)
        ttk.Checkbutton(
            options_row,
            text="Exclude Cosmetics pack",
            variable=self.exclude_cosmetics,
            command=self.cosmetics_setting_changed,
        ).pack(side="left", padx=6)

        self.frozen_frame = ttk.Frame(self.advanced_frame, padding=(0, 8, 0, 0))
        self.frozen_frame.grid(row=3, column=0, sticky="ew")
        ttk.Label(self.frozen_frame, text="Frozen Profile").pack(side="left")
        self.frozen_profile_combo = ttk.Combobox(
            self.frozen_frame,
            textvariable=self.frozen_profile,
            values=frozen_profile_names(),
            state="readonly",
            width=34,
        )
        self.frozen_profile_combo.pack(side="left", padx=(8, 0))
        ttk.Button(self.frozen_frame, text="Refresh Profiles", command=self.refresh_frozen_profiles).pack(side="left", padx=(8, 0))
        ttk.Button(self.frozen_frame, text="Freeze Current Setup", command=self.freeze_current_setup).pack(side="left", padx=(8, 0))
        ttk.Button(self.frozen_frame, text="Play Frozen", command=self.play_frozen).pack(side="left", padx=(8, 0))
        ttk.Button(self.frozen_frame, text="Restore Live Setup", command=self.restore_live_setup).pack(side="left", padx=(8, 0))
        self.frozen_frame.grid_remove()

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
        ttk.Label(header_row, textvariable=self.table_title, font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w")

        filters = ttk.Frame(right)
        filters.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 6))
        ttk.Label(filters, text="View").pack(side="left")
        view_combo = ttk.Combobox(
            filters,
            textvariable=self.table_view,
            values=("Mod Differences", "Active Load Order"),
            state="readonly",
            width=18,
        )
        view_combo.pack(side="left", padx=(6, 14))
        view_combo.bind("<<ComboboxSelected>>", lambda _event: self.apply_mod_filters())
        ttk.Label(filters, text="State").pack(side="left")
        self.state_combo = ttk.Combobox(
            filters,
            textvariable=self.state_filter,
            values=(
                "All states",
                "Missing",
                "Needs SteamCMD",
                "Enabled",
                "Disabled",
                "Always Enabled",
                "Always Disabled",
            ),
            state="readonly",
            width=16,
        )
        self.state_combo.pack(side="left", padx=(6, 14))
        self.state_combo.bind("<<ComboboxSelected>>", lambda _event: self.apply_mod_filters())
        ttk.Label(filters, text="Pack").pack(side="left")
        self.pack_combo = ttk.Combobox(
            filters,
            textvariable=self.pack_filter,
            values=("All packs", "Core", "Content", "Cosmetics", "Local", "Workshop"),
            state="readonly",
            width=16,
        )
        self.pack_combo.pack(side="left", padx=(6, 0))
        self.pack_combo.bind("<<ComboboxSelected>>", lambda _event: self.apply_mod_filters())

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
        self.tree.bind("<Button-3>", self.show_mod_context_menu)
        self.mod_context_menu = tk.Menu(
            self,
            tearoff=False,
            bg="#171d22",
            fg="#eef3ef",
            activebackground="#2d4b55",
            activeforeground="#ffffff",
        )
        self.mod_context_menu.add_command(
            label="Open Steam Workshop Page",
            command=self.open_selected_workshop_page,
        )
        self.mod_context_menu.add_command(
            label="Copy Workshop URL",
            command=self.copy_selected_workshop_url,
        )
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
        load_order_view = self.table_view.get() == "Active Load Order"
        if load_order_view:
            self.table_title.set("Active Load Order")
            self.tree.heading("state", text="Order")
            self.tree.heading("collection", text="Source")
            self.tree.heading("title", text="Workshop ID / Mod / Package ID")
            self.state_combo.configure(state="disabled")
            self.pack_combo.configure(state="disabled")
            rows = self.load_order_rows
        else:
            self.table_title.set("Mod Differences")
            self.tree.heading("state", text="State")
            self.tree.heading("collection", text="Pack")
            self.tree.heading("title", text="Workshop ID / Title")
            self.state_combo.configure(state="readonly")
            self.pack_combo.configure(state="readonly")
            rows = self.current_rows
        state_filter = self.state_filter.get()
        pack_filter = self.pack_filter.get()
        for state, collection, title, item_id, quarantined_mod in rows:
            if not load_order_view and state_filter != "All states" and state != state_filter:
                continue
            if not load_order_view and pack_filter != "All packs":
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

    def selected_workshop_item_id(self) -> str | None:
        for row_id in self.tree.selection():
            item_id = self.row_item_ids.get(row_id)
            if item_id:
                return item_id
            values = self.tree.item(row_id, "values")
            if len(values) >= 3:
                match = re.match(r"(\d{7,})\b", str(values[2]))
                if match:
                    return match.group(1)
        return None

    def show_mod_context_menu(self, event: tk.Event) -> None:
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            return
        self.tree.selection_set(row_id)
        self.tree.focus(row_id)
        if self.mod_context_menu is not None:
            has_workshop_page = self.selected_workshop_item_id() is not None
            state = "normal" if has_workshop_page else "disabled"
            self.mod_context_menu.entryconfigure(0, state=state)
            self.mod_context_menu.entryconfigure(1, state=state)
            try:
                self.mod_context_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.mod_context_menu.grab_release()

    def open_selected_workshop_page(self) -> None:
        item_id = self.selected_workshop_item_id()
        if item_id:
            webbrowser.open(WORKSHOP_URL.format(id=item_id))

    def copy_selected_workshop_url(self) -> None:
        item_id = self.selected_workshop_item_id()
        if not item_id:
            return
        url = WORKSHOP_URL.format(id=item_id)
        self.clipboard_clear()
        self.clipboard_append(url)
        self.update()
        self.progress(f"Copied Workshop URL for {item_id}.")

    def refresh_frozen_profiles(self) -> None:
        names = frozen_profile_names()
        if self.frozen_profile_combo is not None:
            self.frozen_profile_combo.configure(values=names)
        if names and self.frozen_profile.get() not in names:
            self.frozen_profile.set(names[0])
        elif not names:
            self.frozen_profile.set("")

    def toggle_frozen_options(self) -> None:
        self.frozen_visible = not self.frozen_visible
        if self.frozen_frame is None:
            return
        if self.frozen_visible:
            self.refresh_frozen_profiles()
            self.frozen_frame.grid()
            self.frozen_button.configure(text="Hide Frozen Profiles")
        else:
            self.frozen_frame.grid_remove()
            self.frozen_button.configure(text="Frozen Profiles")

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
            self.save_configured_paths()

    def choose_mods_config(self) -> None:
        path = filedialog.askopenfilename(
            initialdir=str(Path(self.mods_config_path.get()).parent),
            filetypes=[("RimWorld config", "ModsConfig.xml"), ("XML files", "*.xml"), ("All files", "*.*")],
        )
        if path:
            self.mods_config_path.set(path)
            self.save_configured_paths()

    def choose_local_mods(self) -> None:
        path = filedialog.askdirectory(initialdir=self.local_mods_path.get() or str(Path.home()))
        if path:
            self.local_mods_path.set(path)
            self.save_configured_paths()

    def choose_steamcmd(self) -> None:
        initial = self.steamcmd_path.get()
        initial_dir = str(Path(initial).parent) if initial else str(Path.home())
        path = filedialog.askopenfilename(
            initialdir=initial_dir,
            filetypes=[("SteamCMD", "steamcmd.exe"), ("Executables", "*.exe"), ("All files", "*.*")],
        )
        if path:
            resolved = resolved_executable_path(path)
            self.steamcmd_path.set(str(resolved) if resolved else path)
            self.save_configured_paths()

    def install_steamcmd_for_user(self) -> None:
        def worker() -> None:
            try:
                installed_path = install_steamcmd(self.progress)
                self.after(0, lambda: self.steamcmd_path.set(str(installed_path)))
                self.after(0, self.save_configured_paths)
                self.after(
                    0,
                    lambda: messagebox.showinfo(
                        "SteamCMD installed",
                        f"SteamCMD was installed and configured at:\n\n{installed_path}",
                    ),
                )
            except (RuntimeError, OSError, urllib.error.URLError, zipfile.BadZipFile) as exc:
                error = str(exc)
                self.progress(f"SteamCMD installation failed: {error}")
                self.after(0, lambda: messagebox.showerror("SteamCMD installation failed", error))

        self.run_busy_worker("Installing SteamCMD...", worker)

    def save_configured_paths(self) -> None:
        steamcmd_text = self.steamcmd_path.get().strip()
        resolved_steamcmd = resolved_executable_path(steamcmd_text)
        if resolved_steamcmd:
            steamcmd_text = str(resolved_steamcmd)
            if self.steamcmd_path.get() != steamcmd_text:
                self.steamcmd_path.set(steamcmd_text)
        try:
            save_settings(
                {
                    "workshop_path": self.workshop_path.get().strip(),
                    "local_mods_path": self.local_mods_path.get().strip(),
                    "mods_config_path": self.mods_config_path.get().strip(),
                    "steamcmd_path": steamcmd_text,
                    "exclude_cosmetics": self.exclude_cosmetics.get(),
                    "auto_update_on_launch": self.auto_update_on_launch.get(),
                }
            )
        except OSError as exc:
            self.progress(f"Could not save paths: {exc}")

    def close_app(self) -> None:
        self.save_configured_paths()
        self.destroy()

    def cosmetics_setting_changed(self) -> None:
        self.save_configured_paths()
        state = "excluded" if self.exclude_cosmetics.get() else "included"
        self.progress(f"Cosmetics pack is now {state}.")
        if self.current_result is not None:
            self.start_scan()

    def auto_detect_paths(self) -> None:
        self.workshop_path.set(str(default_workshop_path()))
        self.local_mods_path.set(str(default_rimworld_mods_path()))
        self.mods_config_path.set(str(default_mods_config_path()))
        detected_steamcmd = find_steamcmd()
        self.steamcmd_path.set(str(detected_steamcmd) if detected_steamcmd else "")
        self.save_configured_paths()
        if detected_steamcmd:
            self.progress(f"Auto-detected SteamCMD at {detected_steamcmd}")
        else:
            self.progress(
                "SteamCMD was not found. Use Install SteamCMD for automatic setup, "
                "or select steamcmd.exe manually."
            )

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

        configured_steamcmd = resolved_executable_path(self.steamcmd_path.get())
        if configured_steamcmd:
            canonical_path = str(configured_steamcmd)
            if self.steamcmd_path.get() != canonical_path:
                self.steamcmd_path.set(canonical_path)
                detected.append("SteamCMD")
        else:
            detected_steamcmd = find_steamcmd()
            self.steamcmd_path.set(str(detected_steamcmd) if detected_steamcmd else "")
            if detected_steamcmd:
                detected.append("SteamCMD")

        if detected:
            self.save_configured_paths()
            self.progress(f"Play Now auto-detected invalid or missing paths: {', '.join(detected)}.")

    def run_worker(self, target) -> None:
        threading.Thread(target=target, daemon=True).start()

    def set_busy(self, message: str) -> None:
        self.play_button.configure(state="disabled", text=message.upper())
        self.busy_message.set(message)
        if self.progress_bar is not None:
            self.progress_bar.stop()
            self.progress_bar.configure(mode="indeterminate", value=0)
            self.progress_bar.grid()
            self.progress_bar.start(12)

    def update_busy_download_progress(self, completed: int, total: int) -> None:
        def apply() -> None:
            remaining = max(total - completed, 0)
            if self.progress_bar is not None:
                self.progress_bar.stop()
                self.progress_bar.configure(mode="determinate", maximum=max(total, 1), value=completed)
                self.progress_bar.grid()
            self.busy_message.set(f"{completed} of {total} mods complete - {remaining} remaining")
            self.play_button.configure(text=f"{completed}/{total} MODS")

        self.after(0, apply)

    def update_busy_check_progress(self, checked: int, total: int) -> None:
        def apply() -> None:
            remaining = max(total - checked, 0)
            if self.progress_bar is not None:
                self.progress_bar.stop()
                self.progress_bar.configure(mode="determinate", maximum=max(total, 1), value=checked)
                self.progress_bar.grid()
            self.busy_message.set(f"{checked} of {total} mods checked - {remaining} left")
            self.play_button.configure(text=f"{checked}/{total} CHECKED")

        self.after(0, apply)

    def clear_busy(self) -> None:
        if self.progress_bar is not None:
            self.progress_bar.stop()
            self.progress_bar.configure(mode="indeterminate", value=0)
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
        self.save_configured_paths()
        return scan(
            Path(self.workshop_path.get()),
            Path(self.local_mods_path.get()),
            Path(self.mods_config_path.get()),
            progress,
            exclude_cosmetics=self.exclude_cosmetics.get(),
        )

    def scan_paths_with_required(
        self,
        required: dict[str, WorkshopItem],
        progress,
    ) -> ScanResult:
        self.save_configured_paths()
        return scan_with_required(
            required,
            Path(self.workshop_path.get()),
            Path(self.local_mods_path.get()),
            Path(self.mods_config_path.get()),
            progress,
            exclude_cosmetics=self.exclude_cosmetics.get(),
        )

    def apply_updates_before_launch(
        self,
        result: ScanResult,
        required_snapshot: dict[str, WorkshopItem],
    ) -> ScanResult:
        local_targets = steamcmd_update_target_ids(result)
        workshop_targets = steam_workshop_update_target_ids(result)
        all_targets = list(dict.fromkeys([*local_targets, *workshop_targets]))
        if not all_targets:
            self.progress("No installed mods are available for update comparison.")
            return result

        self.progress(
            f"Pre-launch update check: {len(local_targets)} local and "
            f"{len(workshop_targets)} Steam Workshop mod(s)."
        )
        unavailable_ids: set[str] = set()
        remote_times = fetch_remote_update_times(
            all_targets,
            self.progress,
            progress_count=self.update_busy_check_progress,
            unavailable_out=unavailable_ids,
        )
        resolved_steamcmd = find_or_install_steamcmd(self.progress) if local_targets else find_steamcmd()
        if resolved_steamcmd:
            self.after(0, lambda: self.steamcmd_path.set(str(resolved_steamcmd)))
            self.after(0, self.save_configured_paths)

        if local_targets and resolved_steamcmd:
            local_outdated, local_unknown = workshop_outdated_ids(
                local_targets,
                steamcmd_acf_path(resolved_steamcmd.parent),
                remote_times,
                fallback_manifest_paths=[steam_client_acf_path(result.workshop_path)],
            )
        else:
            local_outdated, local_unknown = [], []
        workshop_outdated, workshop_unknown = workshop_outdated_ids(
            workshop_targets,
            steam_client_acf_path(result.workshop_path),
            remote_times,
        )

        if local_outdated:
            self.progress(f"Updating {len(local_outdated)} local SteamCMD mod(s) before launch...")
            run_steamcmd_downloads(
                result,
                self.progress,
                targets=local_outdated,
                progress_count=self.update_busy_download_progress,
            )
            result = self.scan_paths_with_required(required_snapshot, self.progress)
        if workshop_outdated:
            self.progress(
                f"{len(workshop_outdated)} subscribed Workshop mod(s) need updates; "
                "Steam will apply them as RimWorld launches."
            )
        unknown_count = len(set(local_unknown) | set(workshop_unknown))
        if unknown_count:
            self.progress(f"{unknown_count} installed mod(s) could not be version-compared.")
        if not local_outdated and not workshop_outdated:
            self.progress("Pre-launch update check found no updates.")
        return result

    def advanced_launch(self) -> None:
        auto_update = self.auto_update_on_launch.get()
        if not auto_update:
            webbrowser.open(STEAM_RUN_RIMWORLD)
            return
        self.auto_detect_invalid_paths()

        def worker() -> None:
            old_env = os.environ.get("STEAMCMD")
            try:
                steamcmd = self.steamcmd_path.get().strip()
                if steamcmd:
                    os.environ["STEAMCMD"] = steamcmd
                required_snapshot = fetch_required_items(self.progress)
                result = self.scan_paths_with_required(required_snapshot, self.progress)
                result = self.apply_updates_before_launch(result, required_snapshot)
                self.current_result = result
                sort_result = get_or_build_sort_result(result, self.progress)
                self.current_sort_result = sort_result
                self.after(0, lambda: self.render_result(result, sort_result))
                self.progress("Launching RimWorld through Steam...")
                webbrowser.open(STEAM_RUN_RIMWORLD)
            except (RuntimeError, OSError, urllib.error.URLError) as exc:
                self.progress(f"Launch update failed: {exc}")
                error = str(exc)
                self.after(0, lambda: messagebox.showerror("Launch update failed", error))
            finally:
                if old_env is None:
                    os.environ.pop("STEAMCMD", None)
                else:
                    os.environ["STEAMCMD"] = old_env

        self.run_busy_worker("Checking updates before launch...", worker)

    def play_now(self) -> None:
        self.auto_detect_invalid_paths()
        auto_update = self.auto_update_on_launch.get()

        def worker() -> None:
            old_env = os.environ.get("STEAMCMD")
            try:
                steamcmd = self.steamcmd_path.get().strip()
                if steamcmd:
                    os.environ["STEAMCMD"] = steamcmd

                self.progress("Play Now started.")
                restore_staged_live(self.progress)
                required_snapshot = fetch_required_items(self.progress)
                result = self.scan_paths_with_required(required_snapshot, self.progress)
                if auto_update:
                    result = self.apply_updates_before_launch(result, required_snapshot)

                pending_downloads = download_target_ids(result)
                if pending_downloads:
                    self.progress(f"{len(pending_downloads)} mods need SteamCMD local download. Downloading...")
                    run_steamcmd_downloads(
                        result,
                        self.progress,
                        progress_count=self.update_busy_download_progress,
                    )
                    self.progress("Download complete. Rechecking local folders against the same live pack snapshot...")
                    result = self.scan_paths_with_required(required_snapshot, self.progress)

                if result.missing_ids:
                    self.current_result = result
                    self.after(0, lambda: self.render_result(result))
                    raise RuntimeError(f"Cannot launch yet: {len(result.missing_ids)} required mods are still missing.")

                if result.unregistered_ids:
                    self.current_result = result
                    self.after(0, lambda: self.render_result(result))
                    raise RuntimeError(
                        f"{len(result.unregistered_ids)} mods are still present only as non-loadable Workshop folders. "
                        "Run the SteamCMD download step again, or check that Local Mods points to RimWorld's Mods folder."
                    )
                sort_result = get_or_build_sort_result(result, self.progress)
                write_mods_config(result, self.progress, sort_result)
                self.current_result = result
                self.current_sort_result = sort_result
                self.after(0, lambda: self.render_result(result, sort_result))
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

    def build_load_order_rows(
        self,
        result: ScanResult,
        sort_result: SortResult | None = None,
    ) -> list[tuple[str, str, str, str | None, QuarantinedMod | None]]:
        sort_result = sort_result or get_or_build_sort_result(result, self.progress)
        active_item_ids = [
            *[
                item_id
                for item_id in result.ready_ids
                if item_id not in result.disabled_ids or item_id in result.always_enabled_ids
            ],
            *[
                item_id
                for item_id in sorted(result.always_enabled_ids, key=int)
                if item_id in result.installed_ids and item_id not in result.ready_ids
            ],
        ]
        package_to_item: dict[str, str] = {}
        for item_id in active_item_ids:
            package_id = result.installed_package_ids.get(item_id, "").lower()
            if package_id and package_id not in package_to_item:
                package_to_item[package_id] = item_id

        ludeon_titles = {
            "ludeon.rimworld": "RimWorld",
            "ludeon.rimworld.royalty": "Royalty",
            "ludeon.rimworld.ideology": "Ideology",
            "ludeon.rimworld.biotech": "Biotech",
            "ludeon.rimworld.anomaly": "Anomaly",
            "ludeon.rimworld.odyssey": "Odyssey",
        }
        rows: list[tuple[str, str, str, str | None, QuarantinedMod | None]] = []
        for position, package_id in enumerate(sort_result.package_ids, start=1):
            package_id = package_id.lower()
            item_id = package_to_item.get(package_id)
            if item_id:
                item = result.required.get(item_id)
                metadata = read_mod_metadata(result.item_paths[item_id], item_id)
                if item and item.title:
                    title = item.title
                elif metadata:
                    title = metadata.name
                else:
                    title = package_id
                if item_id in result.local_steamcmd_ids:
                    source = "Local"
                elif item:
                    source = item.collection
                else:
                    source = "Workshop"
                label = f"{item_id}  {title}  [{package_id}]"
            else:
                source = "Game"
                title = ludeon_titles.get(package_id, package_id)
                label = f"{title}  [{package_id}]"
            rows.append((str(position), source, label, item_id, None))

        self.progress(
            f"Load-order preview: {len(rows)} active entries, "
            f"{sort_result.dependency_edges} dependency and "
            f"{sort_result.load_rule_edges} load-order rules."
        )
        return rows

    def render_result(
        self,
        result: ScanResult,
        sort_result: SortResult | None = None,
    ) -> None:
        sort_result = sort_result or get_or_build_sort_result(result, self.progress)
        self.current_sort_result = sort_result
        pinned_installed = result.always_enabled_ids & result.installed_ids
        disabled_installed_ids = result.disabled_ids & result.installed_ids
        disabled_extra_ids = [item_id for item_id in result.extra_ids if item_id not in result.always_enabled_ids]
        self.progress(
            f"Ready: {len(result.ready_ids)} loadable, {len(result.missing_ids)} missing, "
            f"{len(result.unregistered_ids)} need SteamCMD local download, "
            f"{len(disabled_installed_ids | set(disabled_extra_ids))} disabled, "
            f"{len(pinned_installed)} always enabled."
        )
        ready_package_ids = {
            result.installed_package_ids[item_id]
            for item_id in result.ready_ids
            if item_id in result.installed_package_ids
            and (item_id not in result.disabled_ids or item_id in result.always_enabled_ids)
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
            if item_id in result.always_enabled_ids:
                state = "Always Enabled"
            elif item_id in result.disabled_ids:
                state = "Always Disabled"
            else:
                state = "Disabled"
            source = "Local" if item_id in result.local_steamcmd_ids else "Workshop"
            package_id = result.installed_package_ids.get(item_id, "")
            label = f"{item_id}  {package_id}" if package_id else item_id
            rows.append((state, source, label, item_id, None))
        for item_id in result.ready_ids:
            item = result.required[item_id]
            source = "Local" if item_id in result.local_steamcmd_ids else item.collection
            if item_id in result.always_enabled_ids:
                state = "Always Enabled"
            elif item_id in result.disabled_ids:
                state = "Always Disabled"
            else:
                state = "Enabled"
            rows.append((state, source, f"{item_id}  {item.title}", item_id, None))
        self.load_order_rows = self.build_load_order_rows(result, sort_result)
        self.set_mod_rows(rows)

    def show_quarantine(self) -> None:
        self.table_view.set("Mod Differences")
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
        if self.exclude_cosmetics.get():
            cosmetic_selected = selected & cached_cosmetic_ids()
            selected.difference_update(cosmetic_selected)
            if cosmetic_selected:
                self.progress(
                    f"Skipped {len(cosmetic_selected)} cosmetic mod(s) because Cosmetics exclusion is enabled."
                )
            if not selected:
                messagebox.showinfo(
                    "Cosmetics excluded",
                    "Turn off Exclude Cosmetics pack before marking cosmetic mods as Always Enabled.",
                )
                return
        always_enabled = load_always_enabled_ids()
        always_enabled.update(selected)
        save_always_enabled_ids(always_enabled)
        disabled = load_disabled_ids()
        disabled.difference_update(selected)
        save_disabled_ids(disabled)
        self.progress(f"Always enabled {len(selected)} selected mod(s).")
        if self.current_result:
            self.current_result.always_enabled_ids = always_enabled
            self.current_result.disabled_ids = disabled
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
        disabled = load_disabled_ids()
        disabled.update(selected)
        save_disabled_ids(disabled)
        self.progress(
            f"Always disabled {len(selected)} selected mod(s); "
            f"{len(removed)} removed from Always Enabled."
        )
        if self.current_result:
            self.current_result.always_enabled_ids = always_enabled
            self.current_result.disabled_ids = disabled
            self.render_result(self.current_result)

    def reset_selected(self) -> None:
        selected = self.selected_item_ids()
        if not selected:
            messagebox.showinfo("Select mods", "Select one or more mods in the table first.")
            return
        always_enabled = load_always_enabled_ids()
        disabled = load_disabled_ids()
        enabled_overrides = selected & always_enabled
        disabled_overrides = selected & disabled
        always_enabled.difference_update(selected)
        disabled.difference_update(selected)
        save_always_enabled_ids(always_enabled)
        save_disabled_ids(disabled)
        self.progress(
            f"Reset {len(selected)} selected mod(s) to Ferny's current pack status; "
            f"removed {len(enabled_overrides)} Always Enabled and "
            f"{len(disabled_overrides)} Always Disabled override(s)."
        )
        if self.current_result:
            self.current_result.always_enabled_ids = always_enabled
            self.current_result.disabled_ids = disabled
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
                if self.exclude_cosmetics.get():
                    excluded_profile_ids = profile_ids & cached_cosmetic_ids()
                    profile_ids.difference_update(excluded_profile_ids)
                    if excluded_profile_ids:
                        self.progress(
                            f"Cosmetics exclusion disabled {len(excluded_profile_ids)} mod(s) from the frozen profile."
                        )
                result = self.scan_paths(self.progress)
                result.always_enabled_ids = set(profile_ids)
                result.disabled_ids.difference_update(profile_ids)
                sort_result = get_or_build_sort_result(result, self.progress)
                self.current_result = result
                self.current_sort_result = sort_result
                self.after(0, lambda: self.render_result(result, sort_result))
                write_mods_config(result, self.progress, sort_result)
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
            messagebox.showinfo("Scan first", "Run a scan before checking mod updates.")
            return
        local_targets = steamcmd_update_target_ids(result)
        workshop_targets = steam_workshop_update_target_ids(result)
        if not local_targets and not workshop_targets:
            messagebox.showinfo("No mods to check", "No installed Ferny mods are available for update comparison.")
            return

        def worker() -> None:
            old_env = os.environ.get("STEAMCMD")
            try:
                steamcmd = self.steamcmd_path.get().strip()
                if steamcmd:
                    os.environ["STEAMCMD"] = steamcmd
                resolved_steamcmd = (
                    find_or_install_steamcmd(self.progress) if local_targets else find_steamcmd()
                )
                if resolved_steamcmd:
                    self.after(0, lambda: self.steamcmd_path.set(str(resolved_steamcmd)))
                    self.after(0, self.save_configured_paths)

                all_targets = list(dict.fromkeys([*local_targets, *workshop_targets]))
                self.progress(
                    f"Checking {len(local_targets)} SteamCMD and "
                    f"{len(workshop_targets)} Steam Workshop mod(s) for updates..."
                )
                unavailable_ids: set[str] = set()
                remote_times = fetch_remote_update_times(
                    all_targets,
                    self.progress,
                    progress_count=self.update_busy_check_progress,
                    unavailable_out=unavailable_ids,
                )
                if local_targets and resolved_steamcmd:
                    local_outdated, local_unknown = workshop_outdated_ids(
                        local_targets,
                        steamcmd_acf_path(resolved_steamcmd.parent),
                        remote_times,
                        fallback_manifest_paths=[steam_client_acf_path(result.workshop_path)],
                    )
                else:
                    local_outdated, local_unknown = [], []
                workshop_outdated, workshop_unknown = workshop_outdated_ids(
                    workshop_targets,
                    steam_client_acf_path(result.workshop_path),
                    remote_times,
                )

                def ask_yes_no(title: str, prompt: str) -> bool:
                    accepted = threading.Event()
                    prompt_done = threading.Event()

                    def ask() -> None:
                        if messagebox.askyesno(title, prompt):
                            accepted.set()
                        prompt_done.set()

                    self.after(0, ask)
                    while not prompt_done.wait(0.1):
                        pass
                    return accepted.is_set()

                updated_local = False
                if local_outdated:
                    preview = "\n".join(
                        f"- {item_id} {result.required[item_id].title}".strip()
                        for item_id in local_outdated[:12]
                    )
                    if len(local_outdated) > 12:
                        preview += f"\n...and {len(local_outdated) - 12} more"
                    prompt = (
                        f"Steam reports {len(local_outdated)} newer SteamCMD mod(s).\n\n"
                        f"{preview}\n\nUpdate these local mods now?"
                    )
                    local_unavailable = set(local_unknown) & unavailable_ids
                    local_unresolved = len(local_unknown) - len(local_unavailable)
                    if local_unavailable:
                        prompt += f"\n\n{len(local_unavailable)} SteamCMD mod(s) are unavailable on Steam."
                    if local_unresolved:
                        prompt += f"\n{local_unresolved} SteamCMD mod(s) could not be compared."
                    if ask_yes_no("Update SteamCMD mods", prompt):
                        run_steamcmd_downloads(
                            result,
                            self.progress,
                            targets=local_outdated,
                            progress_count=self.update_busy_download_progress,
                        )
                        updated_local = True
                    else:
                        self.progress("SteamCMD updates skipped.")

                launched_for_workshop = False
                if workshop_outdated:
                    preview = "\n".join(
                        f"- {item_id} {result.required[item_id].title}".strip()
                        for item_id in workshop_outdated[:12]
                    )
                    if len(workshop_outdated) > 12:
                        preview += f"\n...and {len(workshop_outdated) - 12} more"
                    prompt = (
                        f"Steam reports {len(workshop_outdated)} newer subscribed Workshop mod(s).\n\n"
                        f"{preview}\n\n"
                        "Steam updates existing Workshop items before RimWorld launches. "
                        "Launch RimWorld through Steam now to force those updates?"
                    )
                    workshop_unavailable = set(workshop_unknown) & unavailable_ids
                    workshop_unresolved = len(workshop_unknown) - len(workshop_unavailable)
                    if workshop_unavailable:
                        prompt += f"\n\n{len(workshop_unavailable)} Workshop mod(s) are unavailable on Steam."
                    if workshop_unresolved:
                        prompt += f"\n{workshop_unresolved} Workshop mod(s) could not be compared."
                    if ask_yes_no("Steam Workshop updates", prompt):
                        self.progress("Launching RimWorld through Steam so subscribed Workshop updates are applied...")
                        webbrowser.open(STEAM_RUN_RIMWORLD)
                        launched_for_workshop = True
                    else:
                        self.progress("Steam Workshop update launch skipped.")

                unknown_count = len(local_unknown) + len(workshop_unknown)
                if not local_outdated and not workshop_outdated:
                    checked_count = len(all_targets) - unknown_count
                    message = f"No mod updates found. {checked_count} mod(s) were compared."
                    unavailable_count = len(
                        (set(local_unknown) | set(workshop_unknown)) & unavailable_ids
                    )
                    unresolved_count = unknown_count - unavailable_count
                    if unavailable_count:
                        message += (
                            f" {unavailable_count} installed mod(s) are unavailable, hidden, "
                            "or deleted on Steam."
                        )
                    if unresolved_count:
                        message += (
                            f" {unresolved_count} mod(s) still could not be compared after metadata retries."
                        )
                    self.progress(message)
                    self.after(0, lambda: messagebox.showinfo("No updates", message))
                elif updated_local and not launched_for_workshop:
                    self.progress("SteamCMD update complete. Rechecking local folders...")
                    fresh_result = self.scan_paths_with_required(result.required, self.progress)
                    sort_result = get_or_build_sort_result(fresh_result, self.progress)
                    self.current_result = fresh_result
                    self.current_sort_result = sort_result
                    self.after(0, lambda: self.render_result(fresh_result, sort_result))
            except (RuntimeError, OSError, urllib.error.URLError) as exc:
                self.progress(f"Update failed: {exc}")
                error = str(exc)
                self.after(0, lambda: messagebox.showerror("Update failed", error))
            finally:
                if old_env is None:
                    os.environ.pop("STEAMCMD", None)
                else:
                    os.environ["STEAMCMD"] = old_env

        self.run_busy_worker("Checking mod updates...", worker)

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
                run_steamcmd_downloads(
                    result,
                    self.progress,
                    progress_count=self.update_busy_download_progress,
                )
                self.progress("Download complete. Rechecking local folders against the current pack snapshot...")
                fresh_result = self.scan_paths_with_required(result.required, self.progress)
                sort_result = get_or_build_sort_result(fresh_result, self.progress)
                if self.auto_activate_after_download.get():
                    if fresh_result.missing_ids:
                        self.progress(f"Auto-activate skipped: {len(fresh_result.missing_ids)} mods are still missing.")
                    else:
                        if fresh_result.unregistered_ids:
                            self.progress(
                                f"Auto-activate skipped: {len(fresh_result.unregistered_ids)} mods still need SteamCMD local download."
                            )
                        else:
                            write_mods_config(fresh_result, self.progress, sort_result)
                self.current_result = fresh_result
                self.current_sort_result = sort_result
                self.after(0, lambda: self.render_result(fresh_result, sort_result))
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
                sort_result = (
                    self.current_sort_result
                    if result is self.current_result and self.current_sort_result is not None
                    else get_or_build_sort_result(result, self.progress)
                )
                path = write_mods_config(result, self.progress, sort_result)
                self.after(0, lambda: self.render_result(result, sort_result))
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
