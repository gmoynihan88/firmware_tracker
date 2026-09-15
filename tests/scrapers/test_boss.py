def test_boss_picks_the_system_program_over_the_editor_and_drivers():
    """A Boss page offers a System Program, a Tone Studio editor, drivers and Chromium.

    SY-300 has eleven version-bearing links and not one is firmware -- all editor and
    driver builds -- so the right answer there is nothing at all.
    """
    from src.scrapers.plugins.boss import BossScraper

    firmware_page = """
      <a href="/x/">BOSS TONE STUDIO for KATANA Mk II Ver.2.1.0 for Windows</a>
      <a href="/y/">KATANA Mk II System Program (Ver.2.00)</a>
      <a href="/z/">KATANA Driver Ver.1.0.1 for macOS Sonoma 14.x later</a>
      <a href="/c/">Source code of CEF(Chromium Embedded Framework) Version 3.3683.1920</a>
    """
    version, url = BossScraper()._system_program_link(firmware_page)
    assert version == "2.00"
    assert url.endswith("/y/")

    editor_only = """
      <a href="/x/">BOSS TONE STUDIO for SY-300 Ver.1.1.1 for Windows</a>
      <a href="/z/">SY-300 Driver Ver.1.0.2 for Windows 10/11</a>
    """
    assert BossScraper()._system_program_link(editor_only) is None
