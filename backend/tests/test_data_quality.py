from test_dashboard_messages_internal import _admin_headers, _create_plot, _institutional_headers, _register_farmer


def test_data_quality_requires_admin(client, db_session):
    farmer_id = _register_farmer(client, "9000033333", district="Nashik")
    _create_plot(client, farmer_id, "Quality plot")

    unauthorized = client.get("/institutional/data-quality")
    assert unauthorized.status_code in (401, 403)

    viewer_headers = _institutional_headers(client, district="Nashik")
    forbidden = client.get("/institutional/data-quality", headers=viewer_headers)
    assert forbidden.status_code == 403

    admin_headers = _admin_headers(db_session)
    response = client.get("/institutional/data-quality", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["totalFarmers"] >= 1
    assert data["totalPlots"] >= 1
    assert 0.0 <= data["farmerRecords"] <= 100.0
    assert data["missingRecords"] >= 0
