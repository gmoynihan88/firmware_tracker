"""Seed My Devices with an example set of hardware and plugins.

Runs the relevant scrapers to populate the catalog, then adds each entry below
to My Devices. Edit EXAMPLE_DEVICES to match the gear you actually own, or use
`scripts/scan_installed_plugins.py --add` to import installed plugins instead.

Usage:
    python scripts/seed_example_devices.py
"""
import asyncio
import sys
sys.path.insert(0, '.')

from src.database import async_session_maker, init_db
from src.devices import service as device_service
from src.devices.schemas import MyDeviceCreate
from src.scrapers import service as scraper_service


# Example devices — edit this list to match your own gear.
# "manufacturer" must be a scraper slug (see GET /api/firmware/scrapers).
EXAMPLE_DEVICES = [
    # Hardware
    {"manufacturer": "elektron", "model": "Digitakt", "nickname": None},
    {"manufacturer": "boss", "model": "DD-500", "nickname": None},
    {"manufacturer": "strymon", "model": "BigSky", "nickname": None},
    {"manufacturer": "focusrite", "model": "Scarlett 2i2", "nickname": None},
    # VST Plugins
    {"manufacturer": "modartt", "model": "Pianoteq", "nickname": None},
    {"manufacturer": "nativeinstruments", "model": "Kontakt", "nickname": None},
]


async def main():
    await init_db()

    async with async_session_maker() as db:
        # First, run all scrapers to import devices
        scrapers_to_run = list(set(d["manufacturer"] for d in EXAMPLE_DEVICES))
        print(f"Importing devices from {len(scrapers_to_run)} manufacturers...")

        for scraper_type in scrapers_to_run:
            print(f"  Scraping {scraper_type}...", end=" ", flush=True)
            try:
                result = await scraper_service.scrape_manufacturer(db, scraper_type)
                if result.get("success"):
                    devices_synced = result.get("devices_synced", {})
                    print(f"OK ({devices_synced.get('total', 0)} devices)")
                else:
                    print(f"FAILED: {result.get('error', 'Unknown error')}")
            except Exception as e:
                print(f"ERROR: {e}")

        # Now add each device to My Devices
        print(f"\nAdding {len(EXAMPLE_DEVICES)} devices to My Devices...")

        added_count = 0
        for device_info in EXAMPLE_DEVICES:
            # Find the device model
            device_models = await device_service.get_device_models(db)

            # Look for matching model
            matching_model = None
            for model in device_models:
                model_name_lower = model.name.lower()
                search_name_lower = device_info["model"].lower()
                manufacturer_slug = model.manufacturer.slug.lower() if model.manufacturer.slug else model.manufacturer.name.lower()

                if (search_name_lower in model_name_lower or model_name_lower in search_name_lower) and \
                   device_info["manufacturer"].lower() in manufacturer_slug:
                    matching_model = model
                    break

            if matching_model:
                # Check if already added
                my_devices = await device_service.get_my_devices(db)
                already_added = any(d.device_model_id == matching_model.id for d in my_devices)

                if not already_added:
                    await device_service.create_my_device(
                        db,
                        MyDeviceCreate(
                            device_model_id=matching_model.id,
                            nickname=device_info["nickname"],
                            notify_on_update=True,
                        )
                    )
                    print(f"  Added: {matching_model.manufacturer.name} {matching_model.name}")
                    added_count += 1
                else:
                    print(f"  Already exists: {matching_model.manufacturer.name} {matching_model.name}")
            else:
                print(f"  NOT FOUND: {device_info['manufacturer']} {device_info['model']}")

        print(f"\nDone! Added {added_count} devices to My Devices.")


if __name__ == "__main__":
    asyncio.run(main())
