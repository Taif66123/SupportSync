from tests.conftest import API, admin_tokens, headers, login, register  # noqa: F401


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_register_login_me_flow(client):
    tokens = register(client, "flow@test.io", full_name="Flow")
    assert tokens["token_type"] == "bearer"
    assert tokens["expires_in"] > 0

    me = client.get(f"{API}/users/me", headers=headers(tokens))
    assert me.status_code == 200
    assert me.json()["email"] == "flow@test.io"
    assert me.json()["role"] == "customer"


def test_register_duplicate_email_conflict(client, customer_tokens):
    response = client.post(
        f"{API}/auth/register",
        json={"email": "customer@test.io", "password": "passw0rd!", "full_name": "Dup"},
    )
    assert response.status_code == 409


def test_login_wrong_password_unauthorized(client, customer_tokens):
    response = client.post(f"{API}/auth/login", json={"email": "customer@test.io", "password": "wrong-pass"})
    assert response.status_code == 401


def test_refresh_rotation_rejects_reuse(client, customer_tokens):
    old_refresh = customer_tokens["refresh_token"]

    rotated = client.post(f"{API}/auth/refresh", json={"refresh_token": old_refresh})
    assert rotated.status_code == 200

    # The rotated token is now dead — reuse is rejected.
    reuse = client.post(f"{API}/auth/refresh", json={"refresh_token": old_refresh})
    assert reuse.status_code == 401

    # ... and the new token still works.
    again = client.post(f"{API}/auth/refresh", json={"refresh_token": rotated.json()["refresh_token"]})
    assert again.status_code == 200


def test_logout_revokes_refresh_token(client, customer_tokens):
    logout = client.post(f"{API}/auth/logout", json={"refresh_token": customer_tokens["refresh_token"]})
    assert logout.status_code == 204

    after = client.post(f"{API}/auth/refresh", json={"refresh_token": customer_tokens["refresh_token"]})
    assert after.status_code == 401


def test_deactivated_user_cannot_login_or_refresh(client, admin_tokens):
    tokens = register(client, "gone@test.io")
    user_id = client.get(f"{API}/users/me", headers=headers(tokens)).json()["id"]

    deactivate = client.patch(f"{API}/users/{user_id}/status", json={"is_active": False}, headers=headers(admin_tokens))
    assert deactivate.status_code == 200

    assert client.post(f"{API}/auth/login", json={"email": "gone@test.io", "password": "passw0rd!"}).status_code == 401
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401


def test_missing_token_unauthorized(client):
    assert client.get(f"{API}/users/me").status_code == 401
