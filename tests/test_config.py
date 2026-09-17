"""Settings, loaded the way a new installation loads them.

Every other test in this suite constructs `Settings(_env_file=None)`, which is correct
for those tests -- they are pinning one setting's behaviour and do not want a developer's
local file bleeding in. But it means nothing here had ever loaded `.env.example`, and the
one thing a configuration example has to do is start the app.

It did not. `.env.example` carries PORT, docker-compose needs it (`"${PORT:-8000}:8000"`
reads it from this same file), and pydantic-settings defaults BaseSettings to
extra="forbid" -- so the documented `cp .env.example .env` raised ValidationError at
import. A developer .env written before the PORT line was added is what hid it.
"""
from pathlib import Path

import pytest

from src.config import Settings

ROOT = Path(__file__).parent.parent


def test_the_documented_env_file_actually_starts():
    """`cp .env.example .env` has to produce a config that loads.

    This is the whole point of the file, and it is the assertion that was missing: the
    example is documentation that executes, so nothing but executing it checks whether
    it is true. Reading `.env.example` directly rather than copying it to `.env` keeps
    the test hermetic -- it cannot be answered by the developer's own file.
    """
    example = ROOT / ".env.example"
    assert example.exists(), "the documented starting point is missing"

    settings = Settings(_env_file=example)

    # The key that broke it, and the reason it is in the file at all.
    assert settings.port == 8000


def test_every_key_in_the_example_is_a_real_setting():
    """The failure generalises, so the guard should too.

    PORT was one undeclared key; the next one added to the example would fail exactly
    the same way and be just as invisible, because extra="forbid" is inherited rather
    than written down. Comparing the file's keys against the model's fields names the
    offending key directly instead of leaving a ValidationError to be decoded.
    """
    example = ROOT / ".env.example"
    keys = set()
    for line in example.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        keys.add(line.split("=", 1)[0].strip().lower())

    undeclared = sorted(keys - set(Settings.model_fields))
    assert not undeclared, (
        f"{undeclared} appear in .env.example but are not fields on Settings. "
        "pydantic-settings forbids extra keys, so the documented setup will not start. "
        "Declare the field, rather than loosening extra to 'ignore' -- that would also "
        "silence a typo in every other setting."
    )


def test_unknown_settings_are_still_rejected():
    """Fixed by declaring the field, not by loosening validation.

    The cheap fix for the crash above is extra="ignore", which also means a misspelled
    SCRAPE_INTERVAL_HOURS silently becomes the default and the scraper runs on a
    schedule nobody chose. This pins that we did not take it.
    """
    with pytest.raises(Exception) as caught:
        Settings(_env_file=None, definitely_not_a_setting="x")

    assert "extra" in str(caught.value).lower() or "not permitted" in str(caught.value).lower()
