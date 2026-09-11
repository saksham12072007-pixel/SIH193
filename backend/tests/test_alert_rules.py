from test_dashboard_messages_internal import _institutional_headers


def test_alert_rule_lifecycle(client):
    headers = _institutional_headers(client, district="Nashik")

    unauthorized = client.get("/institutional/alert-rules")
    assert unauthorized.status_code in (401, 403)

    created = client.post(
        "/institutional/alert-rules",
        headers=headers,
        json={
            "name": "Low NIR Nashik",
            "metric": "NIR",
            "operator": "<",
            "value": 40,
            "severity": "URGENT",
            "district": "Nashik",
            "crop": "rice",
        },
    )
    assert created.status_code == 201
    rule = created.json()
    assert rule["enabled"] is True

    listing = client.get("/institutional/alert-rules", headers=headers)
    assert listing.status_code == 200
    assert any(r["rule_id"] == rule["rule_id"] for r in listing.json())

    toggled = client.patch(
        f"/institutional/alert-rules/{rule['rule_id']}",
        headers=headers,
        json={"enabled": False},
    )
    assert toggled.status_code == 200
    assert toggled.json()["enabled"] is False


def test_alert_rule_rejects_out_of_scope_district(client):
    headers = _institutional_headers(client, district="Nashik")
    response = client.post(
        "/institutional/alert-rules",
        headers=headers,
        json={
            "name": "Pune rule",
            "metric": "NDVI",
            "operator": "<",
            "value": 0.3,
            "severity": "HIGH",
            "district": "Pune",
        },
    )
    assert response.status_code == 403
