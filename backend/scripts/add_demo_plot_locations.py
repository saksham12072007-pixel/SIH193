"""Give demo plots WKT locations so the institutional map endpoint returns markers.

The base seed script (seed_demo_data.py) does not set `location_point`, which
makes /institutional/plots/map skip every plot. This script fills coordinates
for demo plots that are missing them. It is idempotent and only touches rows
prefixed with `demo-`.
"""

from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.database import SessionLocal  # noqa: E402
from app.models import Plot  # noqa: E402

DEMO_PREFIX = "demo-"
# Yavatmal, Maharashtra city centroid with a safe jitter window (~5 km).
BASE_LATITUDE = 20.3888
BASE_LONGITUDE = 78.1304


def seed() -> None:
    random.seed(42)  # deterministic jitter so reruns are stable
    session = SessionLocal()
    try:
        plots = (
            session.query(Plot)
            .filter(Plot.plot_id.like(f"{DEMO_PREFIX}%"))
            .all()
        )
        updated = 0
        for index, plot in enumerate(plots):
            if plot.location_point:
                continue
            latitude = BASE_LATITUDE + random.uniform(-0.045, 0.045)
            longitude = BASE_LONGITUDE + random.uniform(-0.045, 0.045)
            plot.location_point = f"POINT ({longitude:.6f} {latitude:.6f})"
            plot.location_precision = "synthetic_centroid_jitter"
            updated += 1
        session.commit()
        print(f"Assigned WKT locations to {updated} of {len(plots)} demo plots.")
    finally:
        session.close()


if __name__ == "__main__":
    seed()
