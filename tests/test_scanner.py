from pathlib import Path


def _scanner():
    """Load the standalone scanner script as a module."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "scripts" / "scan_installed_plugins.py"
    spec = importlib.util.spec_from_file_location("scan_installed_plugins", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reverse_dns_bundle_ids_yield_the_vendor():
    scanner = _scanner()

    assert scanner.extract_manufacturer("com.izotope.ozone11") == "izotope"
    assert scanner.extract_manufacturer("ch.toguaudioline.talreverb4") == "toguaudioline"
    assert scanner.extract_manufacturer("com.uaudio.something") == "uaudio"


def test_non_reverse_dns_ids_fall_back_to_the_copyright():
    """Native Instruments' older plugins have no reverse-DNS id at all.

    The bundle id is effectively the filename, so the old parser reported the product
    name as the manufacturer: "Absynth 5", "FM8" and "Kontakt 5" all appeared as
    vendors, and NI's plugin count read as 26 when it is closer to 47.
    """
    scanner = _scanner()
    plist = {"CFBundleGetInfoString": "5.3.4 (R59), Copyright © 2021 Native Instruments GmbH"}

    assert scanner.extract_manufacturer("Absynth 5.MusicDevice.component", plist) == "native-instruments"
    assert scanner.extract_manufacturer("FM8.vst3", plist) == "native-instruments"


def test_copyright_vendor_matches_the_reverse_dns_spelling():
    """Both routes must produce one key, or a single vendor splits in two."""
    scanner = _scanner()

    from_id = scanner.extract_manufacturer("com.native-instruments.kontakt")
    from_copyright = scanner.extract_manufacturer(
        "Kontakt 5.Synth16.vst",
        {"NSHumanReadableCopyright": "Copyright © 2020 Native Instruments GmbH"},
    )
    assert from_id == from_copyright == "native-instruments"


def test_legal_suffixes_are_stripped():
    """"Foo Inc." and "Foo GmbH" are the same vendor as "Foo"."""
    scanner = _scanner()

    for copyright_line, expected in (
        ("Copyright © 2024 Acme Audio GmbH", "acme-audio"),
        ("Copyright (c) 2023 Acme Audio Inc.", "acme-audio"),
        ("Copyright © 2022 Acme Audio Ltd", "acme-audio"),
    ):
        assert scanner.extract_manufacturer("Thing.vst3", {"CFBundleGetInfoString": copyright_line}) == expected


def test_unidentifiable_plugins_report_unknown():
    """Better to admit ignorance than to report a product name as a vendor."""
    scanner = _scanner()

    assert scanner.extract_manufacturer("Mystery.vst3", {}) == "unknown"
    assert scanner.extract_manufacturer("", {}) == "unknown"
    # A copyright with no vendor name must not yield a year.
    assert scanner.extract_manufacturer("X.vst3", {"CFBundleGetInfoString": "Copyright © 2024"}) == "unknown"


def _scanned(name, version="1.0.0", vendor="izotope"):
    """A scanned plugin, as the scanner builds one from a bundle's plist."""
    return _scanner().PluginInfo(
        name=name, version=version, bundle_id=f"com.{vendor}.plugin",
        manufacturer=vendor, format="VST3", path="/Library/Audio/Plug-Ins/VST3/x.vst3",
    )


def _catalogue_models(*rows):
    """Device models with their manufacturer attached: (slug, vendor name, model name)."""
    from types import SimpleNamespace

    return [
        SimpleNamespace(id=i, name=model, manufacturer=SimpleNamespace(slug=slug, name=vendor))
        for i, (slug, vendor, model) in enumerate(rows, start=1)
    ]


def test_scanner_matches_a_plugin_only_to_its_own_vendors_products():
    """iZotope's RX 11 De-reverb once matched Empress's Reverb pedal and asked for 6.50."""
    scanner = _scanner()
    models = _catalogue_models(
        ("empress", "Empress Effects", "Reverb"),
        ("izotope", "iZotope", "RX 11"),
        ("gforce", "GForce Software", "M-Tron Pro IV"),
    )

    assert scanner._match_plugin_to_model(_scanned("RX 11 De-reverb"), models).name == "RX 11"
    # The bundle id says "gforcesoftware"; the tracker's slug is "gforce". The display name agrees.
    matched = scanner._match_plugin_to_model(_scanned("M-Tron Pro IV", vendor="gforcesoftware"), models)
    assert (matched.manufacturer.slug, matched.name) == ("gforce", "M-Tron Pro IV")


def test_scanner_matches_part_of_a_name_only_on_whole_words():
    scanner = _scanner()
    models = _catalogue_models(("izotope", "iZotope", "RX 1"))

    assert scanner._match_plugin_to_model(_scanned("RX 11 Voice De-noise"), models) is None
    assert scanner._match_plugin_to_model(_scanned("RX 1 Denoiser"), models).name == "RX 1"


def test_scanner_matches_a_vendor_the_tracker_lacks_by_exact_name_only():
    scanner = _scanner()
    models = _catalogue_models(("empress", "Empress Effects", "Reverb"))

    assert scanner._match_plugin_to_model(_scanned("Reverb Pro", vendor="waves"), models) is None


def test_scanner_compares_versions_as_numbers():
    """Installed 1.0.2 against the tracker's 1.0.1 is ahead, not an update."""
    scanner = _scanner()

    assert scanner._update_status("1.0.2", "1.0.1") == "ahead"
    assert scanner._update_status("1.9", "1.10") == "update"
    assert scanner._update_status("5.3.4 (R59)", "5.3.4") == "current"
    assert scanner._update_status("1.0", "1.0.0") == "current"
    assert scanner._update_status("7.0.20", "7.1.40") == "update"
