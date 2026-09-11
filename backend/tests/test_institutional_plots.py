from datetime import date

from app.models import PlotFeatures, SatelliteData
from app.services.ingestion_providers import GeeOpenMeteoProvider

from test_dashboard_messages_internal import _create_plot, _institutional_headers, _register_farmer


def test_institutional_map_and_plot_history(client, db_session):
    farmer_id = _register_farmer(client, "9000088888", district="Nashik")
    plot_id = _create_plot(client, farmer_id, "Mapped plot")
    db_session.add(
        PlotFeatures(
            plot_id=plot_id,
            obs_date=date.today(),
            ndvi=0.61,
            rainfall_7d=12.5,
        )
    )
    db_session.add(
        SatelliteData(
            satellite_id="nir-test-1",
            plot_id=plot_id,
            data_source="nir_api",
            data_type="nir",
            value="0.72",
            observation_date=date.today(),
            cloud_masked=False,
            ingestion_status="success",
        )
    )
    db_session.commit()
    headers = _institutional_headers(client, district="Nashik")

    markers = client.get("/institutional/plots/map?district=Nashik", headers=headers)
    assert markers.status_code == 200
    assert markers.json()[0]["plot_id"] == plot_id
    assert markers.json()[0]["latitude"] == 19.076
    assert markers.json()[0]["nir"] == 0.72

    history = client.get(f"/institutional/plots/{plot_id}/history", headers=headers)
    assert history.status_code == 200
    assert history.json()["series"][0]["ndvi"] == 0.61
    assert history.json()["series"][0]["rainfall_7d"] == 12.5


def test_institutional_history_rejects_other_district(client):
    farmer_id = _register_farmer(client, "9000077777", district="Pune")
    plot_id = _create_plot(client, farmer_id, "Private plot")
    headers = _institutional_headers(client, district="Nashik")
    response = client.get(f"/institutional/plots/{plot_id}/history", headers=headers)
    assert response.status_code == 403


def test_live_ingestion_accepts_stored_wkt_coordinates():
    assert GeeOpenMeteoProvider._parse_location("POINT (72.8777 19.076)") == (19.076, 72.8777)
