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
