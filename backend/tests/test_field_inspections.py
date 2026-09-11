from test_dashboard_messages_internal import _create_plot, _institutional_headers, _register_farmer


def test_field_inspection_lifecycle(client):
    farmer_id = _register_farmer(client, "9000044444", district="Nashik")
    plot_id = _create_plot(client, farmer_id, "Inspection plot")
    headers = _institutional_headers(client, district="Nashik")

    unauthorized = client.post("/institutional/inspections", json={
        "plot_id": plot_id,
        "issue_type": "Water Stress",
        "observed_condition": "Wilting leaves observed",
        "severity": "URGENT",
    })
    assert unauthorized.status_code in (401, 403)

    created = client.post(
        "/institutional/inspections",
        headers=headers,
        json={
            "plot_id": plot_id,
            "issue_type": "Water Stress",
            "observed_condition": "Wilting leaves observed",
            "severity": "URGENT",
            "gps_lat": 19.076,
            "gps_lng": 72.8777,
            "gps_accuracy_m": 4.5,
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["plot_id"] == plot_id
    assert body["status"] == "PENDING"
    assert body["farmer_name"]

    listing = client.get(f"/institutional/inspections?plot_id={plot_id}", headers=headers)
    assert listing.status_code == 200
    assert len(listing.json()) == 1


def test_field_inspection_rejects_out_of_scope_plot(client):
    farmer_id = _register_farmer(client, "9000022222", district="Pune")
    plot_id = _create_plot(client, farmer_id, "Private plot")
    headers = _institutional_headers(client, district="Nashik")

    response = client.post(
        "/institutional/inspections",
        headers=headers,
        json={
            "plot_id": plot_id,
            "issue_type": "Pest Infestation",
            "observed_condition": "Aphids on stem",
            "severity": "MODERATE",
        },
    )
    assert response.status_code == 403
