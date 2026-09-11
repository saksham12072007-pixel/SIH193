def test_farmer_deletion_anonymizes_related_data(client):
    farmer_response = client.post(
        "/farmers/register",
        json={
            "phone_number": "9876500000",
            "name": "Delete Me",
            "preferred_language": "en",
            "state": "Maharashtra",
            "district": "Nashik",
            "consent_given": True,
            "registration_channel": "sms",
        },
    )
    assert farmer_response.status_code == 201
    farmer_id = farmer_response.json()["farmer_id"]

    plot_response = client.post(
        "/plots/create",
        json={
            "farmer_id": farmer_id,
            "plot_nickname": "Sensitive Plot",
            "latitude": 19.076,
            "longitude": 72.8777,
            "crop_type": "rice",
            "plot_size_declared": 1.0,
            "sowing_date": "2024-06-15",
        },
    )
    assert plot_response.status_code == 201

    unauthorized_delete = client.delete(f"/farmers/{farmer_id}")
    assert unauthorized_delete.status_code == 403

    session_response = client.post(
        "/farmers/session",
        json={"phone_number": "9876500000", "origin_channel": "sms"},
    )
    assert session_response.status_code == 200
    session_token = session_response.json()["session_token"]

    delete_response = client.delete(f"/farmers/{farmer_id}?session_token={session_token}")
    assert delete_response.status_code == 200
    delete_data = delete_response.json()
    assert delete_data["status"] == "anonymized"
    assert delete_data["plots_redacted"] == 1

    farmer_lookup = client.get(f"/farmers/{farmer_id}")
    assert farmer_lookup.status_code == 200
    farmer_data = farmer_lookup.json()
    assert farmer_data["status"] == "deactivated"
    assert farmer_data["phone_number"].startswith("ANON")

    old_phone_lookup = client.get("/farmers/by-phone/9876500000")
    assert old_phone_lookup.status_code == 404


def test_sms_send_caps_after_daily_limit(client):
    farmer_response = client.post(
        "/farmers/register",
        json={
            "phone_number": "9876500001",
            "name": "Quota Farmer",
            "preferred_language": "en",
            "consent_given": True,
            "registration_channel": "sms",
        },
    )
    assert farmer_response.status_code == 201

    for index in range(5):
        response = client.post(
            "/sms/send",
            json={
                "farmer_phone": "9876500001",
                "message_body": f"Test message {index}",
            },
        )
        assert response.status_code == 200

    capped_response = client.post(
        "/sms/send",
        json={
            "farmer_phone": "9876500001",
            "message_body": "Should be blocked",
        },
    )
    assert capped_response.status_code == 429
    assert "Daily SMS limit" in capped_response.json()["detail"]


def test_farmer_and_plot_reads_are_masked_without_owner_session(client):
    farmer_response = client.post(
        "/farmers/register",
        json={
            "phone_number": "9876500002",
            "name": "Masked Farmer",
            "preferred_language": "en",
            "state": "Maharashtra",
            "district": "Nashik",
            "consent_given": True,
            "registration_channel": "sms",
        },
    )
    assert farmer_response.status_code == 201
    farmer_id = farmer_response.json()["farmer_id"]

    plot_response = client.post(
        "/plots/create",
        json={
            "farmer_id": farmer_id,
            "plot_nickname": "Masked Plot",
            "latitude": 19.076,
            "longitude": 72.8777,
            "crop_type": "rice",
            "plot_size_declared": 1.0,
            "sowing_date": "2024-06-15",
        },
    )
    assert plot_response.status_code == 201
    plot_id = plot_response.json()["plot_id"]

    farmer_public = client.get(f"/farmers/{farmer_id}")
    assert farmer_public.status_code == 200
    farmer_data = farmer_public.json()
    assert farmer_data["phone_number"] == "REDACTED"
    assert farmer_data["name"] is None
    assert farmer_data["state"] is None
    assert farmer_data["district"] is None

    plot_public = client.get(f"/plots/plot/{plot_id}")
    assert plot_public.status_code == 200
    plot_data = plot_public.json()
    assert plot_data["buffer_polygon"] is None
    assert plot_data["village_name"] is None

    session_response = client.post(
        "/farmers/session",
        json={"phone_number": "9876500002", "origin_channel": "sms"},
    )
    assert session_response.status_code == 200
    session_token = session_response.json()["session_token"]

    farmer_owner = client.get(f"/farmers/{farmer_id}?session_token={session_token}")
    assert farmer_owner.status_code == 200
    assert farmer_owner.json()["phone_number"] == "+919876500002"

    plot_owner = client.get(f"/plots/plot/{plot_id}?session_token={session_token}")
    assert plot_owner.status_code == 200
    assert plot_owner.json()["buffer_polygon"] is not None