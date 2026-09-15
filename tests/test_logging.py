import logging


def _reset_root_logging():
    root = logging.getLogger()
    for h in list(root.handlers):
        if getattr(h, "_firmware_tracker", False):
            root.removeHandler(h)


def test_configure_logging_is_idempotent():
    """The lifespan runs again on every reload, and a second handler doubles output."""
    from src.config import Settings
    from src.logging_config import configure_logging

    _reset_root_logging()
    try:
        settings = Settings(_env_file=None)
        configure_logging(settings)
        configure_logging(settings)
        configure_logging(settings)

        ours = [h for h in logging.getLogger().handlers if getattr(h, "_firmware_tracker", False)]
        assert len(ours) == 1
    finally:
        _reset_root_logging()


def test_configure_logging_falls_back_to_info_on_a_bad_level():
    """A typo in LOG_LEVEL should not stop the app starting."""
    from src.config import Settings
    from src.logging_config import configure_logging

    _reset_root_logging()
    try:
        configure_logging(Settings(_env_file=None, log_level="LOUD"))
        assert logging.getLogger().level == logging.INFO

        _reset_root_logging()
        configure_logging(Settings(_env_file=None, log_level="warning"))
        assert logging.getLogger().level == logging.WARNING
    finally:
        _reset_root_logging()


def test_configure_logging_leaves_uvicorn_error_propagating():
    """uvicorn.error has no handler and depends on propagating up to `uvicorn`.

    Setting propagate=False on it looks like the obvious way to stop duplicate
    output, and instead sends its records nowhere -- silently losing "Application
    startup complete" and every startup error. Verified by breaking it once.
    """
    from src.config import Settings
    from src.logging_config import configure_logging

    _reset_root_logging()
    try:
        configure_logging(Settings(_env_file=None))
        assert logging.getLogger("uvicorn.error").propagate is True
    finally:
        _reset_root_logging()


def test_scrape_logs_a_line_per_manufacturer(caplog):
    """A scheduled run has to be reviewable afterwards, not just totalled."""
    import src.scrapers.service as service_module

    with caplog.at_level(logging.INFO, logger="src.scrapers.service"):
        service_module.logger.info(
            "%s scraped in %.1fs: %d new versions, %d notifications, "
            "%d without firmware, %d failed, %d unchecked",
            "Eventide", 12.3, 743, 0, 27, 0, 0,
        )

    assert "Eventide scraped in 12.3s" in caplog.text
    assert "743 new versions" in caplog.text


def _access_record(path: str) -> logging.LogRecord:
    """Build a record shaped the way uvicorn logs access lines."""
    return logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:1", "GET", path, "1.1", 200),
        exc_info=None,
    )


def test_health_check_access_lines_are_dropped():
    """A container health check polls /health every 30s: 2,880 lines a day of nothing."""
    from src.logging_config import _DropHealthCheckAccess

    drop = _DropHealthCheckAccess()

    assert drop.filter(_access_record("/health")) is False
    assert drop.filter(_access_record("/health/ready")) is False
    # A query string must not smuggle it past the check.
    assert drop.filter(_access_record("/health?debug=1")) is False


def test_health_filter_keeps_everything_else():
    """Matching on the path argument, not the message, so near-misses survive.

    A substring test against the formatted line would also drop /api/health-report
    and any request whose query string merely mentioned /health.
    """
    from src.logging_config import _DropHealthCheckAccess

    drop = _DropHealthCheckAccess()

    for path in ("/", "/catalog", "/healthy", "/api/health-report", "/devices/1?ref=/health"):
        assert drop.filter(_access_record(path)) is True, path

    # A record that is not shaped like an access line passes through untouched.
    plain = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, "hello", None, None)
    assert drop.filter(plain) is True


def test_health_filter_is_not_stacked_and_can_be_turned_off():
    from src.config import Settings
    from src.logging_config import configure_logging, _DropHealthCheckAccess

    access = logging.getLogger("uvicorn.access")
    _reset_root_logging()
    for f in [f for f in access.filters if isinstance(f, _DropHealthCheckAccess)]:
        access.removeFilter(f)
    try:
        settings = Settings(_env_file=None, log_health_checks=False)
        configure_logging(settings)
        configure_logging(settings)
        ours = [f for f in access.filters if isinstance(f, _DropHealthCheckAccess)]
        assert len(ours) == 1

        # Turning it on removes the filter rather than leaving a stale one behind.
        configure_logging(Settings(_env_file=None, log_health_checks=True))
        assert not [f for f in access.filters if isinstance(f, _DropHealthCheckAccess)]
    finally:
        _reset_root_logging()
        for f in [f for f in access.filters if isinstance(f, _DropHealthCheckAccess)]:
            access.removeFilter(f)


def _clear_file_handlers():
    root = logging.getLogger()
    for h in list(root.handlers):
        if getattr(h, "_firmware_tracker", False):
            root.removeHandler(h)
            h.close()


def test_log_file_rotates_and_keeps_the_backups(tmp_path):
    """The point of the setting: the file is capped, not merely written."""
    from src.config import Settings
    from src.logging_config import configure_logging

    target = tmp_path / "logs" / "app.log"
    _clear_file_handlers()
    try:
        configure_logging(
            Settings(_env_file=None, log_file=str(target), log_max_bytes=2000, log_backup_count=3)
        )
        log = logging.getLogger("rotation.test")
        for i in range(200):
            log.info("line %03d %s", i, "x" * 60)

        # The parent directory is created rather than requiring it to exist.
        assert target.exists()
        assert sorted(p.name for p in target.parent.iterdir()) == [
            "app.log", "app.log.1", "app.log.2", "app.log.3",
        ]
        # Nothing beyond backup_count survives, and each file respects the cap.
        for path in target.parent.iterdir():
            assert path.stat().st_size <= 2100, path
        assert "line 199" in target.read_text()
    finally:
        _clear_file_handlers()


def test_no_log_file_means_stderr_only(tmp_path):
    """Empty LOG_FILE is the default, and right under Docker and systemd."""
    from src.config import Settings
    from src.logging_config import configure_logging

    _clear_file_handlers()
    try:
        configure_logging(Settings(_env_file=None, log_file=""))
        files = [h for h in logging.getLogger().handlers if getattr(h, "_firmware_tracker_file", False)]
        assert files == []
    finally:
        _clear_file_handlers()


def test_changing_the_log_file_replaces_the_handler(tmp_path):
    """A reload must not leave the old file open or write to both."""
    from src.config import Settings
    from src.logging_config import configure_logging

    first, second = tmp_path / "one.log", tmp_path / "two.log"
    _clear_file_handlers()
    try:
        configure_logging(Settings(_env_file=None, log_file=str(first)))
        configure_logging(Settings(_env_file=None, log_file=str(first)))
        handlers = [h for h in logging.getLogger().handlers if getattr(h, "_firmware_tracker_file", False)]
        assert len(handlers) == 1, "same path must reuse the handler"

        configure_logging(Settings(_env_file=None, log_file=str(second)))
        handlers = [h for h in logging.getLogger().handlers if getattr(h, "_firmware_tracker_file", False)]
        assert len(handlers) == 1
        assert handlers[0].baseFilename == str(second.resolve())

        # Clearing it removes the handler rather than leaving it writing.
        configure_logging(Settings(_env_file=None, log_file=""))
        assert not [h for h in logging.getLogger().handlers if getattr(h, "_firmware_tracker_file", False)]
    finally:
        _clear_file_handlers()


def test_unwritable_log_file_does_not_stop_startup(tmp_path):
    """A bad LOG_FILE must degrade to stderr, not prevent the app booting."""
    from src.config import Settings
    from src.logging_config import configure_logging

    blocker = tmp_path / "not-a-dir"
    blocker.write_text("I am a file")

    _clear_file_handlers()
    try:
        configure_logging(Settings(_env_file=None, log_file=str(blocker / "app.log")))
        # stderr is still attached and no file handler was added.
        assert [h for h in logging.getLogger().handlers if getattr(h, "_firmware_tracker", False)]
        assert not [h for h in logging.getLogger().handlers if getattr(h, "_firmware_tracker_file", False)]
    finally:
        _clear_file_handlers()
