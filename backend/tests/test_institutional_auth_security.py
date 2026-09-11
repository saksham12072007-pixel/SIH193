from test_dashboard_messages_internal import _admin_headers, _institutional_headers


def test_signup_cannot_self_elevate_role(client):
    response = client.post(
        "/institutional/signup",
        json={
            "email": "wannabe-admin@example.com",
            "password": "StrongPass123",
            "role": "admin",
        },
    )
    assert response.status_code == 201
    assert response.json()["role"] == "field_officer"


def test_users_endpoint_requires_admin(client, db_session):
    viewer_headers = _institutional_headers(client, district="Pune")

    forbidden = client.post(
        "/institutional/users",
        headers=viewer_headers,
        json={"email": "new-admin@example.com", "password": "StrongPass123", "role": "admin"},
    )
    assert forbidden.status_code == 403

    unauthorized = client.get("/institutional/users")
    assert unauthorized.status_code in (401, 403)

    admin_headers = _admin_headers(db_session)
    created = client.post(
        "/institutional/users",
        headers=admin_headers,
        json={"email": "new-admin@example.com", "password": "StrongPass123", "role": "district_officer"},
    )
    assert created.status_code == 201
    assert created.json()["role"] == "district_officer"

    listing = client.get("/institutional/users", headers=admin_headers)
    assert listing.status_code == 200
    emails = [user["email"] for user in listing.json()]
    assert "new-admin@example.com" in emails
