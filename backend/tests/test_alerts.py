from app.models import Alert

from test_dashboard_messages_internal import _create_plot, _institutional_headers, _register_farmer


def test_alerts_are_created_from_advisories_and_can_transition(client, db_session):
    farmer_id = _register_farmer(client, "9000066666", district="Nashik")
    plot_id = _create_plot(client, farmer_id, "Alert plot")
    assert client.post(f"/ingest/{plot_id}?use_mock=true").status_code == 202
    advisory = client.post(f"/advisories/generate/{plot_id}")
    assert advisory.status_code == 201
    headers = _institutional_headers(client, district="Nashik")

    response = client.get("/institutional/alerts?district=Nashik", headers=headers)
    assert response.status_code == 200
    alert = response.json()[0]
    assert alert["plot_id"] == plot_id
    assert alert["status"] == "GENERATED"

    updated = client.patch(
        f"/institutional/alerts/{alert['alert_id']}",
        headers=headers,
        json={"status": "ACKNOWLEDGED", "resolution_notes": "Field officer notified"},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "ACKNOWLEDGED"
    assert updated.json()["resolution_notes"] == "Field officer notified"
    assert db_session.query(Alert).count() == 1


def test_alerts_respect_assigned_geography(client):
    farmer_id = _register_farmer(client, "9000055555", district="Pune")
    plot_id = _create_plot(client, farmer_id, "Scoped alert")
    assert client.post(f"/ingest/{plot_id}?use_mock=true").status_code == 202
    assert client.post(f"/advisories/generate/{plot_id}").status_code == 201
    headers = _institutional_headers(client, district="Nashik")
    assert client.get("/institutional/alerts", headers=headers).json() == []
