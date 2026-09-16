import pytest


def test_password_hashing_round_trip():
    """scrypt hashes verify, and a malformed stored value denies rather than raises."""
    from src.auth.security import hash_password, verify_password

    stored = hash_password("correct horse")
    assert stored.startswith("scrypt$")
    assert verify_password("correct horse", stored) is True
    assert verify_password("Correct Horse", stored) is False
    # A broken value in .env must deny access, not crash every request.
    assert verify_password("anything", "not-a-hash") is False
    assert verify_password("anything", "") is False


def test_session_tokens_reject_tampering_and_expiry():
    from src.auth.security import generate_secret_key, issue_token, read_token

    secret = generate_secret_key()
    token = issue_token(secret, 3600)

    assert read_token(token, secret)["sub"] == "owner"
    assert read_token(token, generate_secret_key()) is None      # signed with another key
    assert read_token(token[:-2] + "xy", secret) is None          # signature altered
    assert read_token(issue_token(secret, -1), secret) is None    # already expired
    assert read_token("", secret) is None
    assert read_token("no-dot", secret) is None


@pytest.mark.asyncio
async def test_auth_disabled_leaves_everything_open(client):
    """Default install keeps working with no configuration."""
    assert (await client.get("/")).status_code == 200
    assert (await client.get("/api/manufacturers")).status_code == 200


@pytest.mark.asyncio
async def test_api_requires_authentication_when_enabled(auth_enabled, client):
    response = await client.get("/api/manufacturers")

    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"


@pytest.mark.asyncio
async def test_the_login_page_says_whose_installation_this_is(auth_enabled, client):
    """Anyone who lands here and is not the owner has found someone else's install.

    A bare password prompt tells them nothing and offers them nothing. The page names
    what this is and points at the repository, so "what is this and how do I get one"
    is answered on the page rather than left to whoever shared the link.
    """
    import re

    page = (await client.get("/login", headers={"accept": "text/html"})).text
    card = re.search(r'<form class="login-card".*?</form>', page, re.S)
    assert card, "no login card rendered"

    assert "self-hosted" in card.group(0)
    assert "https://github.com/gmoynihan88/firmware_tracker" in card.group(0)
    # Scoped to the card deliberately. base.html's nav links /catalog on every page, so
    # asserting against the whole document would pass whatever the card contained -- and
    # the first version of this test did exactly that, and failed for that reason.
    assert 'href="/catalog"' not in card.group(0)


@pytest.mark.asyncio
async def test_browser_is_redirected_to_the_login_page(auth_enabled, client):
    """A browser should land on the form; curl should get a status code."""
    response = await client.get("/", headers={"accept": "text/html"})

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


@pytest.mark.asyncio
async def test_login_sets_a_session_that_grants_access(auth_enabled, client):
    bad = await client.post("/login", data={"password": "wrong"})
    assert bad.status_code == 401
    assert "Incorrect password" in bad.text

    good = await client.post("/login", data={"password": "correct horse"})
    assert good.status_code == 303
    assert good.headers["location"] == "/"

    from src.auth.middleware import SESSION_COOKIE
    assert SESSION_COOKIE in good.cookies

    # The client keeps the cookie, so the API is now reachable.
    assert (await client.get("/api/manufacturers")).status_code == 200

    await client.get("/logout")
    assert (await client.get("/api/manufacturers")).status_code == 401


@pytest.mark.asyncio
async def test_api_key_works_for_programmatic_callers(auth_enabled, client):
    assert (await client.get("/api/manufacturers", headers={"x-api-key": "test-api-key"})).status_code == 200
    assert (await client.get("/api/manufacturers", headers={"x-api-key": "wrong"})).status_code == 401


@pytest.mark.asyncio
async def test_api_key_is_ignored_when_none_is_configured(auth_enabled, client):
    """An unset API key must not mean "any key works", or "no key works either"."""
    auth_enabled.api_key = ""
    assert (await client.get("/api/manufacturers", headers={"x-api-key": ""})).status_code == 401
    assert (await client.get("/api/manufacturers", headers={"x-api-key": "anything"})).status_code == 401


def test_auth_stays_off_if_only_half_configured():
    """A password with no secret key cannot sign sessions, so it must not half-enable."""
    from src.auth.middleware import auth_is_enabled
    from src.config import Settings

    assert auth_is_enabled(Settings(_env_file=None, auth_password_hash="scrypt$a$b", secret_key="")) is False
    assert auth_is_enabled(Settings(_env_file=None, auth_password_hash="", secret_key="k")) is False
    assert auth_is_enabled(Settings(_env_file=None, auth_password_hash="scrypt$a$b", secret_key="k")) is True


def test_login_throttle_counts_failures_in_a_sliding_window():
    from src.auth.throttle import LoginThrottle

    now = [1000.0]
    throttle = LoginThrottle(max_attempts=3, window_seconds=300, clock=lambda: now[0])

    for _ in range(2):
        throttle.record_failure("10.0.0.1")
    assert throttle.retry_after("10.0.0.1") is None

    throttle.record_failure("10.0.0.1")
    assert throttle.retry_after("10.0.0.1") == 300
    # Another address is unaffected.
    assert throttle.retry_after("10.0.0.2") is None

    # Part-way through the window the wait shrinks, and the oldest failure ageing out
    # is what lets the next attempt through.
    now[0] += 120
    assert throttle.retry_after("10.0.0.1") == 180
    now[0] += 181
    assert throttle.retry_after("10.0.0.1") is None


def test_login_throttle_forgets_a_client_that_gets_in_and_caps_what_it_keeps():
    from src.auth.throttle import LoginThrottle

    throttle = LoginThrottle(max_attempts=1, window_seconds=300, max_clients=2)

    throttle.record_failure("10.0.0.1")
    assert throttle.retry_after("10.0.0.1") == 300
    throttle.clear("10.0.0.1")
    assert throttle.retry_after("10.0.0.1") is None

    # A stream of addresses must not grow the map without bound: the oldest goes.
    for address in ("a", "b", "c"):
        throttle.record_failure(address)
    assert throttle.retry_after("a") is None
    assert throttle.retry_after("c") == 300


@pytest.mark.asyncio
async def test_login_answers_429_once_the_attempts_run_out(auth_enabled, client):
    """A public /login needs a limit; five wrong passwords is the default."""
    from src.auth.throttle import reset_login_throttle

    reset_login_throttle()
    try:
        for _ in range(auth_enabled.login_max_attempts):
            assert (await client.post("/login", data={"password": "wrong"})).status_code == 401

        blocked = await client.post("/login", data={"password": "wrong"})
        assert blocked.status_code == 429
        assert int(blocked.headers["retry-after"]) > 0
        assert "Too many attempts" in blocked.text

        # The right password does not get past the limit either, or guessing would
        # only have to be lucky on the attempt after the lockout.
        assert (await client.post("/login", data={"password": "correct horse"})).status_code == 429
    finally:
        reset_login_throttle()


@pytest.mark.asyncio
async def test_login_throttle_is_per_client_and_cleared_by_a_correct_password(auth_enabled):
    from httpx import ASGITransport, AsyncClient

    from src.auth.throttle import reset_login_throttle
    from src.main import app

    def _client(address):
        return AsyncClient(
            transport=ASGITransport(app=app, client=(address, 5000)), base_url="http://test"
        )

    reset_login_throttle()
    try:
        async with _client("10.0.0.1") as guesser, _client("10.0.0.2") as innocent:
            for _ in range(auth_enabled.login_max_attempts):
                await guesser.post("/login", data={"password": "wrong"})
            assert (await guesser.post("/login", data={"password": "wrong"})).status_code == 429

            # Someone else's login is not affected by the guesser's address.
            assert (await innocent.post("/login", data={"password": "wrong"})).status_code == 401
            assert (await innocent.post("/login", data={"password": "correct horse"})).status_code == 303
            # ... and getting in clears what that address had against it.
            for _ in range(auth_enabled.login_max_attempts):
                assert (await innocent.post("/login", data={"password": "wrong"})).status_code == 401
    finally:
        reset_login_throttle()


@pytest.mark.asyncio
async def test_session_cookie_is_marked_secure_when_configured(auth_enabled, client):
    """Behind CloudFront the app sees http, so the scheme alone drops the flag."""
    from src.auth.throttle import reset_login_throttle

    reset_login_throttle()
    before = auth_enabled.session_cookie_secure
    try:
        auth_enabled.session_cookie_secure = False
        plain = await client.post("/login", data={"password": "correct horse"})
        assert "secure" not in plain.headers["set-cookie"].lower()

        auth_enabled.session_cookie_secure = True
        secured = await client.post("/login", data={"password": "correct horse"})
        assert "; Secure" in secured.headers["set-cookie"]

        # Logging out has to clear the same cookie, attributes included.
        cleared = await client.get("/logout")
        assert "; Secure" in cleared.headers["set-cookie"]
    finally:
        auth_enabled.session_cookie_secure = before
        reset_login_throttle()
