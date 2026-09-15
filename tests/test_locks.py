from pathlib import Path

from src.main import app


def _lock_pins(filename):
    """Canonical name -> pinned version, for every requirement in a pip-compile lock."""
    import re
    from pathlib import Path

    from packaging.utils import canonicalize_name

    text = (Path(__file__).resolve().parent.parent / filename).read_text()
    pins = {}
    for line in text.splitlines():
        matched = re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;\\]+)", line)
        if matched:
            pins[canonicalize_name(matched.group(1))] = matched.group(2)
    return pins


def _pyproject_requirements(*extras):
    import tomllib
    from pathlib import Path

    from packaging.requirements import Requirement

    pyproject = (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text()
    project = tomllib.loads(pyproject)["project"]
    declared = list(project["dependencies"])
    for extra in extras:
        declared += project["optional-dependencies"][extra]
    return [Requirement(r) for r in declared]


def test_lock_files_satisfy_pyproject():
    """The locks are what installs; pyproject.toml is what the app says it needs.

    They are kept separately because Dependabot only regenerates a pip-compile lock
    from .in files, never from pyproject.toml. This keeps them honest: a dependency
    added to pyproject but never locked, or a floor raised past the locked version,
    fails here -- not at runtime in the container.
    """
    from packaging.utils import canonicalize_name

    for lock, extras in (
        ("requirements.txt", ("browser",)),
        ("requirements-dev.txt", ("browser", "dev")),
    ):
        pins = _lock_pins(lock)
        for requirement in _pyproject_requirements(*extras):
            name = canonicalize_name(requirement.name)
            assert name in pins, f"{requirement.name} is in pyproject.toml but not locked in {lock}"
            assert requirement.specifier.contains(pins[name], prereleases=True), (
                f"{lock} pins {requirement.name}=={pins[name]}, outside pyproject's "
                f"{requirement.specifier}"
            )


def test_the_two_locks_agree_on_every_shared_package():
    """requirements.txt ships in the image; requirements-dev.txt is what CI tests.

    A package pinned differently in the two would mean CI passing on a version the
    image does not run.
    """
    app, dev = _lock_pins("requirements.txt"), _lock_pins("requirements-dev.txt")

    differing = {n: (app[n], dev[n]) for n in app.keys() & dev.keys() if app[n] != dev[n]}
    assert differing == {}
    assert app.keys() <= dev.keys(), sorted(app.keys() - dev.keys())
