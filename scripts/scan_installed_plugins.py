#!/usr/bin/env python3
"""Scan macOS for installed audio plugins (VST/VST3/AU/CLAP) and report versions.

Usage:
    python scripts/scan_installed_plugins.py              # all plugins
    python scripts/scan_installed_plugins.py --synths      # synths/instruments only
    python scripts/scan_installed_plugins.py --json        # JSON output
    python scripts/scan_installed_plugins.py --compare     # compare with firmware tracker DB
    python scripts/scan_installed_plugins.py --add         # add matched plugins to My Devices
"""
import argparse
import json
import plistlib
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

PLUGIN_DIRS = [
    (Path("/Library/Audio/Plug-Ins/VST3/"), "VST3"),
    (Path("/Library/Audio/Plug-Ins/VST/"), "VST"),
    (Path("/Library/Audio/Plug-Ins/Components/"), "AU"),
    (Path("/Library/Audio/Plug-Ins/CLAP/"), "CLAP"),
    (Path.home() / "Library/Audio/Plug-Ins/VST3/", "VST3"),
    (Path.home() / "Library/Audio/Plug-Ins/VST/", "VST"),
    (Path.home() / "Library/Audio/Plug-Ins/Components/", "AU"),
    (Path.home() / "Library/Audio/Plug-Ins/CLAP/", "CLAP"),
]

# AU component types that are instruments/synths (from AudioUnit API)
# 'aumu' = music device (instrument), 'aumi' = music effect, 'aumf' = MIDI processor
AU_INSTRUMENT_TYPES = {"aumu"}

# Heuristic keywords for instrument/synth detection from plugin names
SYNTH_KEYWORDS = {
    "synth", "synthesizer", "sampler", "drum", "piano", "organ", "keys",
    "instrument", "kontakt", "battery", "massive", "serum", "reaktor",
    "fm8", "absynth", "omnisphere", "diva", "repro", "zebra", "hive",
    "vital", "pigments", "analog lab", "halion", "groove agent",
    "tal-u-no", "tal-j-8", "tal-mod", "tal-dac", "tal-drum",
    "tal-bassline", "tal-sampler", "komplete kontrol", "maschine",
    "m-tron", "mariana", "hammond", "pianoteq",
}

EFFECT_KEYWORDS = {
    "eq", "compressor", "reverb", "delay", "chorus", "phaser", "flanger",
    "limiter", "gate", "de-esser", "saturator", "distortion", "filter",
    "analyzer", "meter", "loudness", "ozone", "neutron", "nectar",
    "rx ", "insight", "relay", "tonal balance", "audiolens",
    "guitar rig", "amplitube", "bias",
    "flair", "choral", "bite", "dirt", "driver", "freak", "enhanced eq",
    "raum", "replika", "phasis", "supercharger",
    "solid bus comp", "solid dynamics", "solid eq", "transient master",
    "vc 160", "vc 2a", "vc 76", "vari comp", "passive eq",
    "rc 24", "rc 48",
}


@dataclass
class PluginInfo:
    name: str
    version: str
    bundle_id: str
    manufacturer: str
    format: str
    path: str
    is_instrument: bool | None = None

    @property
    def display_manufacturer(self) -> str:
        return MANUFACTURER_NAMES.get(self.manufacturer, self.manufacturer)


MANUFACTURER_NAMES = {
    "native-instruments": "Native Instruments",
    "ikmultimedia": "IK Multimedia",
    "izotope": "iZotope",
    "modartt": "Modartt",
    "moogmusic": "Moog",
    "steinberg": "Steinberg",
    "uaudio": "Universal Audio",
    "gforcesoftware": "GForce Software",
    "ch": "TAL Software",
}


def extract_manufacturer(bundle_id: str) -> str:
    parts = bundle_id.split(".")
    if len(parts) >= 2:
        prefix = parts[0]
        vendor = parts[1]
        if prefix in ("com", "net", "org", "io"):
            return vendor
        return prefix
    return "unknown"


def classify_instrument(name: str, bundle_id: str) -> bool | None:
    """Guess whether a plugin is an instrument vs effect. Returns None if unsure."""
    name_lower = name.lower()
    bid_lower = bundle_id.lower()

    # Check name against effect keywords first (more specific)
    for kw in EFFECT_KEYWORDS:
        if kw in name_lower:
            return False
    # Then name against synth keywords
    for kw in SYNTH_KEYWORDS:
        if kw in name_lower:
            return True
    # Fall back to bundle ID
    for kw in EFFECT_KEYWORDS:
        if kw in bid_lower:
            return False
    for kw in SYNTH_KEYWORDS:
        if kw in bid_lower:
            return True
    return None


def get_au_types() -> dict[str, str]:
    """Use auval to get AU component types (aumu=instrument, aufx=effect)."""
    types = {}
    try:
        result = subprocess.run(
            ["auval", "-a"],
            capture_output=True, text=True, timeout=30,
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            # Lines look like: "aumu TAL8 TAL-  -  TAL Software: TAL-J-8"
            parts = line.split()
            if len(parts) >= 2 and len(parts[0]) == 4:
                comp_type = parts[0]
                # Extract the name after the last " - " or ": "
                if ": " in line:
                    plugin_name = line.split(": ", 1)[-1].strip()
                    types[plugin_name.lower()] = comp_type
        return types
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return {}


def scan_plugins() -> list[PluginInfo]:
    plugins = []
    seen = set()

    for base_dir, fmt in PLUGIN_DIRS:
        if not base_dir.exists():
            continue
        for bundle in sorted(base_dir.iterdir()):
            plist_path = bundle / "Contents" / "Info.plist"
            if not plist_path.exists():
                continue

            try:
                with open(plist_path, "rb") as f:
                    plist = plistlib.load(f)
            except Exception:
                continue

            name = plist.get("CFBundleName", bundle.stem)
            version = plist.get(
                "CFBundleShortVersionString",
                plist.get("CFBundleVersion", "unknown"),
            )
            bundle_id = plist.get("CFBundleIdentifier", "")
            manufacturer = extract_manufacturer(bundle_id)
            is_instrument = classify_instrument(name, bundle_id)

            key = (name, fmt)
            if key in seen:
                continue
            seen.add(key)

            plugins.append(PluginInfo(
                name=name,
                version=version,
                bundle_id=bundle_id,
                manufacturer=manufacturer,
                format=fmt,
                path=str(bundle),
                is_instrument=is_instrument,
            ))

    return plugins


def deduplicate_across_formats(plugins: list[PluginInfo]) -> list[PluginInfo]:
    """Keep one entry per plugin name, preferring VST3 > AU > CLAP > VST."""
    format_priority = {"VST3": 0, "AU": 1, "CLAP": 2, "VST": 3}
    best: dict[str, PluginInfo] = {}

    for p in plugins:
        existing = best.get(p.name)
        if existing is None or format_priority.get(p.format, 9) < format_priority.get(existing.format, 9):
            best[p.name] = p

    return sorted(best.values(), key=lambda p: (p.display_manufacturer, p.name))


def print_table(plugins: list[PluginInfo]) -> None:
    if not plugins:
        print("No plugins found.")
        return

    # Group by manufacturer
    by_mfr: dict[str, list[PluginInfo]] = {}
    for p in plugins:
        mfr = p.display_manufacturer
        by_mfr.setdefault(mfr, []).append(p)

    total = len(plugins)
    synths = sum(1 for p in plugins if p.is_instrument is True)
    effects = sum(1 for p in plugins if p.is_instrument is False)
    unknown = sum(1 for p in plugins if p.is_instrument is None)

    print(f"\n{'=' * 70}")
    print(f"  Installed Audio Plugins — {total} unique")
    print(f"  ({synths} instruments, {effects} effects, {unknown} unclassified)")
    print(f"{'=' * 70}\n")

    for mfr in sorted(by_mfr):
        items = by_mfr[mfr]
        print(f"  {mfr} ({len(items)})")
        print(f"  {'─' * 50}")
        for p in sorted(items, key=lambda x: x.name):
            tag = ""
            if p.is_instrument is True:
                tag = " [synth]"
            elif p.is_instrument is False:
                tag = " [effect]"
            fmts = p.format
            print(f"    {p.name:<35} v{p.version:<12} {fmts}{tag}")
        print()

    print(f"{'=' * 70}")


def _normalize_version(v: str) -> str:
    """Strip build metadata suffixes for comparison: '5.3.4 (R59)' → '5.3.4', '1.4.6+3' → '1.4.6'."""
    import re
    return re.match(r"[\d.]+", v).group() if re.match(r"[\d.]+", v) else v


def compare_with_db(plugins: list[PluginInfo]) -> None:
    """Compare installed versions with firmware tracker database."""
    import asyncio
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    async def _compare():
        from src.database import async_session_maker, init_db
        from src.devices import service as device_service

        await init_db()
        async with async_session_maker() as db:
            device_models = await device_service.get_device_models(db)
            if not device_models:
                print("\nNo devices in firmware tracker database. Run some scrapers first.")
                return

            print(f"\n{'=' * 70}")
            print("  Comparing installed plugins vs. firmware tracker")
            print(f"{'=' * 70}\n")

            matched = 0
            up_to_date = 0
            outdated = []

            for p in plugins:
                dm = _match_plugin_to_model(p, device_models)
                if not dm:
                    continue

                matched += 1
                from src.devices import service as ds
                latest = await ds.get_latest_firmware(db, dm.id)
                if not latest:
                    continue

                installed_norm = _normalize_version(p.version)
                latest_norm = _normalize_version(latest.version)
                if installed_norm == latest_norm:
                    up_to_date += 1
                    print(f"  ✓ {p.name:<30} v{p.version} (up to date)")
                else:
                    outdated.append((p, latest))
                    print(f"  ✗ {p.name:<30} v{p.version} → v{latest.version} available")

            if not matched:
                print("  No installed plugins matched devices in the tracker.")
                print("  Run scrapers to populate the database first.")
            else:
                print(f"\n  {matched} matched, {up_to_date} up to date, {len(outdated)} with updates available")
            print(f"\n{'=' * 70}")

    asyncio.run(_compare())


# Map plist CFBundleName → scraper product name for plugins whose
# installed name doesn't match the human-readable DB name
PLIST_NAME_ALIASES = {
    "uaudio_ampex_atr-102_tape": "Ampex ATR-102 Tape",
    "uaudio_distressor": "Distressor",
    "uaudio_dream_amp": "Dream Amp",
    "uaudio_galaxy_tape_echo": "Galaxy Tape Echo",
    "uaudio_lion_amp": "Lion Amp",
    "uaudio_polymax": "Polymax",
    "uaudio_ruby_amp": "Ruby Amp",
    "uaudio_sound_city_studios": "Sound City Studios",
    "uaudio_verve": "Verve",
    "uaudio_waterfall_rotary_speaker": "Waterfall Rotary Speaker",
}


def _extract_major_version(version: str) -> str | None:
    """Extract leading major version number: '6.8.0 (R0)' → '6'."""
    import re
    m = re.match(r"(\d+)\.", version)
    return m.group(1) if m else None


def _match_plugin_to_model(plugin: PluginInfo, device_models) -> object | None:
    """Find a DB device model matching a scanned plugin."""
    import re

    alias = PLIST_NAME_ALIASES.get(plugin.name)
    names_to_try = [plugin.name.lower()]
    if alias:
        names_to_try.insert(0, alias.lower())

    for name_lower in names_to_try:
        # 1. Exact match
        for dm in device_models:
            if name_lower == dm.name.lower():
                return dm

        # 2. If installed name has no version number, try "{name} {major}"
        #    e.g. "Kontakt" v6.8.0 → try "Kontakt 6"
        major = _extract_major_version(plugin.version)
        if major and not re.search(r"\d", name_lower):
            versioned = f"{name_lower} {major}"
            for dm in device_models:
                if versioned == dm.name.lower():
                    return dm

        # 3. Substring match — collect all candidates, pick closest
        candidates = []
        for dm in device_models:
            dm_lower = dm.name.lower()
            if name_lower in dm_lower or dm_lower in name_lower:
                candidates.append(dm)

        if not candidates:
            continue
        if len(candidates) == 1:
            return candidates[0]

        # Prefer smallest name-length difference (most specific match)
        candidates.sort(key=lambda dm: abs(len(dm.name) - len(plugin.name)))
        return candidates[0]

    return None


def add_to_my_devices(plugins: list[PluginInfo]) -> None:
    """Add scanned plugins to My Devices in the firmware tracker DB."""
    import asyncio
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    async def _add():
        from src.database import async_session_maker, init_db
        from src.devices import service as device_service
        from src.devices.schemas import MyDeviceCreate

        await init_db()
        async with async_session_maker() as db:
            device_models = await device_service.get_device_models(db)
            if not device_models:
                print("\nNo devices in firmware tracker database. Run some scrapers first.")
                return

            my_devices = await device_service.get_my_devices(db)
            tracked_model_ids = {d.device_model_id for d in my_devices}

            print(f"\n{'=' * 70}")
            print("  Adding installed plugins to My Devices")
            print(f"{'=' * 70}\n")

            added = 0
            skipped = 0
            not_found = 0

            for p in plugins:
                dm = _match_plugin_to_model(p, device_models)

                if not dm:
                    not_found += 1
                    print(f"  ?  {p.name:<30} (not in database — run its scraper first)")
                    continue

                if dm.id in tracked_model_ids:
                    skipped += 1
                    print(f"  -  {p.name:<30} already tracked")
                    continue

                await device_service.create_my_device(
                    db,
                    MyDeviceCreate(
                        device_model_id=dm.id,
                        current_firmware_version=p.version,
                        notify_on_update=True,
                    ),
                )
                tracked_model_ids.add(dm.id)
                added += 1
                print(f"  +  {p.name:<30} v{p.version} → added (as {dm.manufacturer.name} / {dm.name})")

            print(f"\n  {added} added, {skipped} already tracked, {not_found} not in database")
            print(f"{'=' * 70}\n")

    asyncio.run(_add())


def main():
    parser = argparse.ArgumentParser(
        description="Scan macOS for installed audio plugins and report versions.",
    )
    parser.add_argument(
        "--synths", action="store_true",
        help="Show only instruments/synthesizers (heuristic filter)",
    )
    parser.add_argument(
        "--effects", action="store_true",
        help="Show only effects",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output as JSON",
    )
    parser.add_argument(
        "--all-formats", action="store_true",
        help="Show every format variant (default: deduplicate, prefer VST3)",
    )
    parser.add_argument(
        "--compare", action="store_true",
        help="Compare installed versions with firmware tracker database",
    )
    parser.add_argument(
        "--add", action="store_true",
        help="Add matched plugins to My Devices (sets installed version)",
    )
    args = parser.parse_args()

    plugins = scan_plugins()

    if not args.all_formats:
        plugins = deduplicate_across_formats(plugins)

    if args.synths:
        plugins = [p for p in plugins if p.is_instrument is True]
    elif args.effects:
        plugins = [p for p in plugins if p.is_instrument is False]

    if args.json:
        data = [asdict(p) for p in plugins]
        print(json.dumps(data, indent=2))
    elif args.compare:
        compare_with_db(plugins)
    elif args.add:
        add_to_my_devices(plugins)
    else:
        print_table(plugins)


if __name__ == "__main__":
    main()
