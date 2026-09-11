"""Tests for Phase 2: Enhanced Farmer Registry and Ingestion."""


def test_farmer_registration_with_valid_phone(client):
    """Test farmer registration with valid Indian phone number."""
    response = client.post(
        "/farmers/register",
        json={
            "phone_number": "9876543210",
            "name": "Rajesh Kumar",
            "preferred_language": "hi",
            "state": "Maharashtra",
            "district": "Nashik",
            "consent_given": True,
            "registration_channel": "sms",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["phone_number"] == "+919876543210"
    assert data["status"] == "active"


def test_duplicate_registration_updates_existing(client):
    """Test that registering with same phone updates existing farmer."""
    client.post(
        "/farmers/register",
        json={
            "phone_number": "9876543212",
            "name": "Original Name",
            "preferred_language": "en",
            "state": "Karnataka",
            "district": "Bangalore",
            "consent_given": True,
            "registration_channel": "sms",
        },
    )

    response = client.post(
        "/farmers/register",
        json={
            "phone_number": "9876543212",
            "name": "Updated Name",
            "preferred_language": "hi",
            "state": "Karnataka",
            "district": "Bangalore",
            "consent_given": True,
            "registration_channel": "web",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Updated Name"
    assert data["preferred_language"] == "hi"


def test_farmer_lookup_by_phone(client):
    """Test looking up farmer by phone number."""
    client.post(
        "/farmers/register",
        json={
            "phone_number": "9876543213",
            "name": "Lookup Test",
            "consent_given": True,
            "registration_channel": "sms",
        },
    )

    response = client.get("/farmers/by-phone/9876543213")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Lookup Test"


def test_plot_creation_with_gps(client):
    """Test plot creation with GPS coordinates."""
    farmer_response = client.post(
        "/farmers/register",
        json={
            "phone_number": "8765432100",
            "name": "Plot Test Farmer",
            "consent_given": True,
            "registration_channel": "sms",
        },
    )
    farmer_id = farmer_response.json()["farmer_id"]

    response = client.post(
        "/plots/create",
        json={
            "farmer_id": farmer_id,
            "plot_nickname": "North Field",
            "latitude": 19.0760,
            "longitude": 72.8777,
            "crop_type": "rice",
            "plot_size_declared": 1.0,
            "sowing_date": "2024-06-15",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["crop_type"] == "rice"
    assert data["location_precision"] == "gps"
    assert data["buffer_polygon"] is not None


def test_plot_creation_with_village_fallback(client):
    """Test plot creation with village fallback."""
    farmer_response = client.post(
        "/farmers/register",
        json={
            "phone_number": "8765432101",
            "name": "Plot Test Farmer 2",
            "consent_given": True,
            "registration_channel": "sms",
        },
    )
    farmer_id = farmer_response.json()["farmer_id"]

    response = client.post(
        "/plots/create",
        json={
            "farmer_id": farmer_id,
            "plot_nickname": "Village Plot",
            "village_name": "Nashik",
            "crop_type": "wheat",
            "plot_size_declared": 2.5,
            "sowing_date": "2024-10-01",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["location_precision"] == "village_fallback"
    assert data["village_name"] == "Nashik"


def test_invalid_location_outside_india(client):
    """Test that plots outside India are rejected."""
    farmer_response = client.post(
        "/farmers/register",
        json={
            "phone_number": "8765432103",
            "name": "Plot Test Farmer 3",
            "consent_given": True,
            "registration_channel": "sms",
        },
    )
    farmer_id = farmer_response.json()["farmer_id"]

    response = client.post(
        "/plots/create",
        json={
            "farmer_id": farmer_id,
            "plot_nickname": "Invalid",
            "latitude": -33.9249,
            "longitude": 18.4241,
            "crop_type": "rice",
            "plot_size_declared": 1.0,
            "sowing_date": "2024-06-15",
        },
    )
    assert response.status_code == 400
    assert "India" in response.json()["detail"]


def test_plot_creation_rejects_unsupported_crop(client):
    farmer_response = client.post(
        "/farmers/register",
        json={
            "phone_number": "8765432104",
            "name": "Crop Validation Farmer",
            "consent_given": True,
            "registration_channel": "sms",
        },
    )
    farmer_id = farmer_response.json()["farmer_id"]

    response = client.post(
        "/plots/create",
        json={
            "farmer_id": farmer_id,
            "plot_nickname": "Invalid Crop Plot",
            "latitude": 19.0760,
            "longitude": 72.8777,
            "crop_type": "banana",
            "plot_size_declared": 1.0,
            "sowing_date": "2024-06-15",
        },
    )
    assert response.status_code == 400
    assert "Unsupported crop type" in response.json()["detail"]


def test_my_plots_command(client):
    """Test MY PLOTS command."""
    farmer_response = client.post(
        "/farmers/register",
        json={
            "phone_number": "8765432106",
            "name": "Command Test Farmer",
            "consent_given": True,
            "registration_channel": "sms",
        },
    )
    farmer_id = farmer_response.json()["farmer_id"]
    farmer_phone = "8765432106"

    client.post(
        "/plots/create",
        json={
            "farmer_id": farmer_id,
            "plot_nickname": "Test Plot",
            "latitude": 19.0760,
            "longitude": 72.8777,
            "crop_type": "rice",
            "plot_size_declared": 1.0,
            "sowing_date": "2024-06-15",
        },
    )

    session_response = client.post(
        "/farmers/session",
        json={"phone_number": farmer_phone, "origin_channel": "sms"},
    )
    assert session_response.status_code == 200
    session_token = session_response.json()["session_token"]

    response = client.post(
        "/commands/parse",
        json={"farmer_phone": farmer_phone, "command": "MY PLOTS", "session_token": session_token},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert len(data["data"]["plots"]) == 1


def test_pause_resume_command(client):
    """Test PAUSE and RESUME commands."""
    farmer_response = client.post(
        "/farmers/register",
        json={
            "phone_number": "8765432108",
            "name": "Pause Resume Test Farmer",
            "consent_given": True,
            "registration_channel": "sms",
        },
    )
    farmer_id = farmer_response.json()["farmer_id"]
    farmer_phone = "8765432108"

    plot_response = client.post(
        "/plots/create",
        json={
            "farmer_id": farmer_id,
            "plot_nickname": "Test Plot",
            "latitude": 19.0760,
            "longitude": 72.8777,
            "crop_type": "rice",
            "plot_size_declared": 1.0,
            "sowing_date": "2024-06-15",
        },
    )
    plot_id = plot_response.json()["plot_id"]

    session_response = client.post(
        "/farmers/session",
        json={"phone_number": farmer_phone, "origin_channel": "sms"},
    )
    assert session_response.status_code == 200
    session_token = session_response.json()["session_token"]

    pause_response = client.post(
        "/commands/parse",
        json={"farmer_phone": farmer_phone, "command": f"PAUSE {plot_id}", "session_token": session_token},
    )
    assert pause_response.status_code == 200
    assert "paused" in pause_response.json()["message"].lower()

    resume_response = client.post(
        "/commands/parse",
        json={"farmer_phone": farmer_phone, "command": f"RESUME {plot_id}", "session_token": session_token},
    )
    assert resume_response.status_code == 200
    assert "resumed" in resume_response.json()["message"].lower()


def test_satellite_data_ingestion(client):
    """Test satellite data ingestion trigger and retrieval."""
    farmer_response = client.post(
        "/farmers/register",
        json={
            "phone_number": "8765432112",
            "name": "Ingestion Test Farmer",
            "consent_given": True,
            "registration_channel": "sms",
        },
    )
    farmer_id = farmer_response.json()["farmer_id"]

    plot_response = client.post(
        "/plots/create",
        json={
            "farmer_id": farmer_id,
            "plot_nickname": "Ingestion Plot",
            "latitude": 19.0760,
            "longitude": 72.8777,
            "crop_type": "rice",
            "plot_size_declared": 1.0,
            "sowing_date": "2024-06-15",
        },
    )
    plot_id = plot_response.json()["plot_id"]

    # Trigger ingestion
    trigger_response = client.post(f"/ingest/{plot_id}?use_mock=true")
    assert trigger_response.status_code == 202
    data = trigger_response.json()
    assert data["status"] == "ingestion_triggered"
    assert data["records_ingested"] > 0

    # Retrieve latest data
    latest_response = client.get(f"/ingest/latest/{plot_id}")
    assert latest_response.status_code == 200
    latest_data = latest_response.json()
    assert latest_data["plot_id"] == plot_id
    assert "ndvi" in latest_data


def test_history_command_returns_last_three_advisories(client):
    farmer_response = client.post(
        "/farmers/register",
        json={
            "phone_number": "8765432114",
            "name": "History Farmer",
            "consent_given": True,
            "registration_channel": "sms",
        },
    )
    farmer_id = farmer_response.json()["farmer_id"]
    farmer_phone = "8765432114"

    plot_response = client.post(
        "/plots/create",
        json={
            "farmer_id": farmer_id,
            "plot_nickname": "History Plot",
            "latitude": 19.0760,
            "longitude": 72.8777,
            "crop_type": "rice",
            "plot_size_declared": 1.0,
            "sowing_date": "2024-06-15",
        },
    )
    plot_id = plot_response.json()["plot_id"]

    session_response = client.post(
        "/farmers/session",
        json={"phone_number": farmer_phone, "origin_channel": "sms"},
    )
    assert session_response.status_code == 200
    session_token = session_response.json()["session_token"]

    for _ in range(4):
        assert client.post(f"/ingest/{plot_id}?use_mock=true").status_code == 202
        assert client.post(f"/advisories/generate/{plot_id}").status_code == 201

    response = client.post(
        "/commands/parse",
        json={"farmer_phone": farmer_phone, "command": f"HISTORY {plot_id}", "session_token": session_token},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert len(data["data"]["advisories"]) == 3
