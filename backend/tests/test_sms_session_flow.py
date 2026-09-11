def test_sms_join_onboarding_session_creates_farmer_and_plot(client):
    join = client.post("/sms/inbound", json={"farmer_phone": "9000055555", "message_body": "JOIN"})
    assert join.status_code == 200
    assert join.json()["ok"] is True
    assert "Welcome" in join.json()["message"]

    name_step = client.post("/sms/inbound", json={"farmer_phone": "9000055555", "message_body": "Asha"})
    assert name_step.status_code == 200
    assert "Choose language" in name_step.json()["message"]

    language_step = client.post("/sms/inbound", json={"farmer_phone": "9000055555", "message_body": "1"})
    assert language_step.status_code == 200
    assert "consent" in language_step.json()["message"].lower()

    consent_step = client.post("/sms/inbound", json={"farmer_phone": "9000055555", "message_body": "YES"})
    assert consent_step.status_code == 200
    assert "Share your plot location" in consent_step.json()["message"]

    location_step = client.post("/sms/inbound", json={"farmer_phone": "9000055555", "message_body": "Nashik"})
    assert location_step.status_code == 200
    assert "What crop is growing" in location_step.json()["message"]

    crop_step = client.post("/sms/inbound", json={"farmer_phone": "9000055555", "message_body": "rice"})
    assert crop_step.status_code == 200
    assert "When did you sow" in crop_step.json()["message"]

    done_step = client.post("/sms/inbound", json={"farmer_phone": "9000055555", "message_body": "15/06/2024"})
    assert done_step.status_code == 200
    assert done_step.json()["ok"] is True
    assert "Registration complete" in done_step.json()["message"]

    farmer_lookup = client.get("/farmers/by-phone/9000055555")
    assert farmer_lookup.status_code == 200
    assert farmer_lookup.json()["name"] == "Asha"

    plots_response = client.get(f"/plots/{farmer_lookup.json()['farmer_id']}?session_token={client.post('/farmers/session', json={'phone_number': '9000055555', 'origin_channel': 'sms'}).json()['session_token']}")
    assert plots_response.status_code == 200
    assert len(plots_response.json()) == 1