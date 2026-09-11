from test_dashboard_messages_internal import _create_plot, _institutional_headers, _register_farmer


def test_operations_status_traces_pipeline(client):
    farmer_id = _register_farmer(client, "9000044444", district="Nashik")
    plot_id = _create_plot(client, farmer_id, "Operations plot")
    assert client.post(f"/ingest/{plot_id}?use_mock=true").status_code == 202
    assert client.post(f"/advisories/generate/{plot_id}").status_code == 201
    headers = _institutional_headers(client, district="Nashik")

    response = client.get("/institutional/operations/status?district=Nashik", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["plots"]["active"] == 1
    assert body["plots"]["ingested_last_24h"] == 1
    assert body["plots"]["by_source"]["sentinel1"] >= 0
    assert body["plots"]["by_source"]["sentinel2"] >= 0
    assert body["plots"]["by_source"]["weather"] >= 0
    # Ingestion auto-chains a prediction (live-update wiring), and
    # /advisories/generate runs its own Stage1->Stage2 pipeline too --
    # so this plot legitimately accrues 2 predictions.
    assert body["processing"]["predictions_total"] == 2
    assert body["processing"]["advisories_total"] == 1
    assert body["delivery"]["total_messages"] >= 0


def test_operations_status_requires_authentication(client):
    response = client.get("/institutional/operations/status")
    assert response.status_code == 401
