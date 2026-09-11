def test_health_endpoint(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["service"] == "crop-advisory-backend"


def test_ready_endpoint_reports_database_check(client) -> None:
    response = client.get("/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["checks"]["database"] == "ok"
    assert response.headers["x-request-id"]


def test_farmer_registration_requires_consent(client) -> None:
    payload = {
        "phone_number": "+919876543210",
        "name": "Test Farmer",
        "preferred_language": "hi",
        "consent_given": False,
    }
    response = client.post("/farmers/register", json=payload)
    assert response.status_code == 400


def test_command_parser_unknown_command(client) -> None:
    response = client.post("/commands/parse", json={"farmer_phone": "+919876543210", "command": "BOGUS", "payload": {}})
    assert response.status_code == 400
    data = response.json()
    assert data["error"]["code"] == "http_400"
    assert data["detail"] == "Unknown command: BOGUS"
    assert response.headers["x-request-id"]


def test_request_validation_is_structured(client) -> None:
    response = client.post("/sms/inbound", json={"farmer_phone": "+919876543210"})
    assert response.status_code == 422
    data = response.json()
    assert data["error"]["code"] == "request_validation_error"
    assert data["detail"] == "Request validation failed"
    assert data["error"]["details"]
    assert response.headers["x-request-id"]


def test_health_ready_alias(client) -> None:
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["checks"]["database"] == "ok"


def test_plot_validation_rejects_partial_coordinates(client) -> None:
    response = client.post(
        "/plots/create",
        json={"farmer_id": "missing", "crop_type": "cotton", "latitude": 20.1},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_validation_error"
