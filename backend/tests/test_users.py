import pytest

from tests.conftest import API, admin_tokens, headers, login  # noqa: F401


def test_customer_cannot_list_users(client, customer_tokens):
    assert client.get(f"{API}/users", headers=headers(customer_tokens)).status_code == 403


def test_agent_cannot_create_staff(client, agent_tokens):
    response = client.post(
        f"{API}/users",
        json={"email": "x@test.io", "password": "passw0rd!", "full_name": "X", "role": "agent"},
        headers=headers(agent_tokens),
    )
    assert response.status_code == 403


def test_admin_creates_agent(client, admin_tokens):
    response = client.post(
        f"{API}/users",
        json={"email": "new.agent@test.io", "password": "passw0rd!", "full_name": "New Agent", "role": "agent"},
        headers=headers(admin_tokens),
    )
    assert response.status_code == 201
    assert response.json()["role"] == "agent"
    assert response.json()["is_active"] is True


def test_staff_create_rejects_customer_role(client, admin_tokens):
    response = client.post(
        f"{API}/users",
        json={"email": "c@test.io", "password": "passw0rd!", "full_name": "C", "role": "customer"},
        headers=headers(admin_tokens),
    )
    assert response.status_code == 422


def test_admin_lists_and_filters_users(client, admin_tokens, agent_tokens, customer_tokens):
    response = client.get(f"{API}/users?role=agent", headers=headers(admin_tokens))
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    assert all(u["role"] == "agent" for u in body["items"])

    search = client.get(f"{API}/users?q=agent@test.io", headers=headers(admin_tokens))
    assert search.json()["total"] == 1


def test_cannot_change_own_role(client, admin_tokens):
    me = client.get(f"{API}/users/me", headers=headers(admin_tokens)).json()
    response = client.patch(f"{API}/users/{me['id']}/role", json={"role": "agent"}, headers=headers(admin_tokens))
    assert response.status_code == 409


def test_last_admin_is_protected(client, admin_tokens):
    """There is no explicit 'last admin' branch: the self-guard is the invariant carrier.
    The actor must be an active Admin and can never be the target, so the final admin
    can never be demoted or deactivated."""
    me = client.get(f"{API}/users/me", headers=headers(admin_tokens)).json()

    demote_self = client.patch(f"{API}/users/{me['id']}/role", json={"role": "agent"}, headers=headers(admin_tokens))
    assert demote_self.status_code == 409

    # A second admin can be demoted normally while another admin remains.
    second = client.post(
        f"{API}/users",
        json={"email": "admin2@test.io", "password": "passw0rd!", "full_name": "Admin Two", "role": "admin"},
        headers=headers(admin_tokens),
    ).json()
    demote_second = client.patch(f"{API}/users/{second['id']}/role", json={"role": "agent"}, headers=headers(admin_tokens))
    assert demote_second.status_code == 200


def test_cannot_deactivate_self(client, admin_tokens):
    me = client.get(f"{API}/users/me", headers=headers(admin_tokens)).json()
    response = client.patch(f"{API}/users/{me['id']}/status", json={"is_active": False}, headers=headers(admin_tokens))
    assert response.status_code == 409


def test_deactivate_and_reactivate_agent(client, admin_tokens, agent_tokens):
    agent_id = client.get(f"{API}/users/me", headers=headers(agent_tokens)).json()["id"]

    deactivate = client.patch(f"{API}/users/{agent_id}/status", json={"is_active": False}, headers=headers(admin_tokens))
    assert deactivate.status_code == 200
    assert deactivate.json()["is_active"] is False

    # sessions are killed on deactivation (revoked refresh token)
    refresh = client.post(f"{API}/auth/refresh", json={"refresh_token": agent_tokens["refresh_token"]})
    assert refresh.status_code == 401

    reactivate = client.patch(f"{API}/users/{agent_id}/status", json={"is_active": True}, headers=headers(admin_tokens))
    assert reactivate.status_code == 200
    assert client.post(f"{API}/auth/login", json={"email": "agent@test.io", "password": "agentpass1"}).status_code == 200
