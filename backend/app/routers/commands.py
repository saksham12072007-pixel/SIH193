from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.core.auth import verify_farmer_session_token
from app.models import Advisory, Plot
from app.routers.farmers import get_farmer_by_phone, normalize_phone_number
from app.schemas.command import CommandRequest, CommandResponse
from app.utils.time import utc_now

router = APIRouter(prefix="/commands", tags=["commands"])

SENSITIVE_COMMANDS = {"MY PLOTS", "STATUS", "PAUSE", "RESUME", "LANG", "HISTORY"}


def parse_command_args(command: str) -> tuple[str, str | None]:
    """Parse command and optional argument."""
    parts = command.strip().split()
    if not parts:
        return "", None

    head = parts[0].upper()
    second = parts[1].upper() if len(parts) > 1 else ""

    if len(parts) >= 2 and head == "MY" and second == "PLOTS":
        return "MY PLOTS", " ".join(parts[2:]) if len(parts) > 2 else None
    elif len(parts) >= 2 and head == "HISTORY":
        return "HISTORY", " ".join(parts[1:])
    else:
        return head, " ".join(parts[1:]) if len(parts) > 1 else None


def _authorize_command(request: CommandRequest, farmer_id: str) -> None:
    cmd, _ = parse_command_args(request.command)
    if cmd == "HELP":
        return
    if request.trusted_origin:
        return
    if not request.session_token:
        raise HTTPException(status_code=401, detail="Session token required for sensitive farmer commands")
    payload = verify_farmer_session_token(request.session_token)
    request_phone = normalize_phone_number(request.farmer_phone)
    if payload.get("farmer_id") != farmer_id or payload.get("phone_number") != request_phone:
        raise HTTPException(status_code=403, detail="Session token does not match the farmer")


@router.post("/parse", response_model=CommandResponse)
def parse_command(request: CommandRequest, db: Session = Depends(get_db)) -> CommandResponse:
    cmd, arg = parse_command_args(request.command)

    if cmd == "HELP":
        return CommandResponse(
            ok=True,
            message="Available commands: MY PLOTS, STATUS <plot-id>, PAUSE <plot-id>, RESUME <plot-id>, LANG <code>, HISTORY <plot-id>",
            data={},
        )

    if cmd not in SENSITIVE_COMMANDS:
        raise HTTPException(status_code=400, detail=f"Unknown command: {cmd}")

    # Every remaining command is farmer-scoped: resolve the farmer (404 for an
    # unknown phone) and authorize the sensitive operation before doing work.
    farmer = get_farmer_by_phone(db, request.farmer_phone)
    if farmer is None:
        raise HTTPException(status_code=404, detail="Farmer not found")
    _authorize_command(request, farmer.farmer_id)

    if cmd == "MY PLOTS":
        plots = db.query(Plot).filter(Plot.farmer_id == farmer.farmer_id).all()
        plot_list = [
            {
                "plot_id": p.plot_id,
                "nickname": p.plot_nickname,
                "crop": p.crop_type,
                "status": p.status,
            }
            for p in plots
        ]
        return CommandResponse(
            ok=True,
            message=f"You have {len(plots)} registered plot(s).",
            data={"plots": plot_list},
        )

    if cmd == "STATUS":
        if not arg:
            raise HTTPException(status_code=400, detail="STATUS requires a plot ID")
        plot = db.query(Plot).filter(Plot.plot_id == arg, Plot.farmer_id == farmer.farmer_id).first()
        if not plot:
            raise HTTPException(status_code=404, detail="Plot not found")
        return CommandResponse(
            ok=True,
            message=f"Plot {plot.plot_nickname}: status={plot.status}",
            data={"plot_id": plot.plot_id, "status": plot.status},
        )

    if cmd == "PAUSE":
        if not arg:
            raise HTTPException(status_code=400, detail="PAUSE requires a plot ID")
        plot = db.query(Plot).filter(Plot.plot_id == arg, Plot.farmer_id == farmer.farmer_id).first()
        if not plot:
            raise HTTPException(status_code=404, detail="Plot not found")
        if plot.status == "paused":
            return CommandResponse(ok=True, message=f"Plot {plot.plot_nickname} is already paused.", data={})
        plot.status = "paused"
        plot.updated_at = utc_now()
        db.commit()
        return CommandResponse(
            ok=True,
            message=f"Advisories paused for plot {plot.plot_nickname}.",
            data={"plot_id": plot.plot_id},
        )

    if cmd == "RESUME":
        if not arg:
            raise HTTPException(status_code=400, detail="RESUME requires a plot ID")
        plot = db.query(Plot).filter(Plot.plot_id == arg, Plot.farmer_id == farmer.farmer_id).first()
        if not plot:
            raise HTTPException(status_code=404, detail="Plot not found")
        if plot.status == "active":
            return CommandResponse(ok=True, message=f"Plot {plot.plot_nickname} is already active.", data={})
        plot.status = "active"
        plot.updated_at = utc_now()
        db.commit()
        return CommandResponse(
            ok=True,
            message=f"Advisories resumed for plot {plot.plot_nickname}.",
            data={"plot_id": plot.plot_id},
        )

    if cmd == "LANG":
        if not arg:
            raise HTTPException(status_code=400, detail="LANG requires a language code")
        farmer.preferred_language = arg.lower()
        farmer.updated_at = utc_now()
        db.commit()
        return CommandResponse(
            ok=True,
            message=f"Language preference updated to {arg}.",
            data={"language": arg},
        )

    if cmd == "HISTORY":
        if not arg:
            # If no arg given, use first plot if farmer has only one
            plots = db.query(Plot).filter(Plot.farmer_id == farmer.farmer_id).all()
            if len(plots) == 1:
                plot_id = plots[0].plot_id
            elif len(plots) == 0:
                raise HTTPException(status_code=404, detail="Farmer has no plots")
            else:
                raise HTTPException(status_code=400, detail="HISTORY requires a plot ID or farmer has multiple plots")
        else:
            plot_id = arg
        plot = db.query(Plot).filter(Plot.plot_id == plot_id, Plot.farmer_id == farmer.farmer_id).first()
        if not plot:
            raise HTTPException(status_code=404, detail="Plot not found")

        advisories = (
            db.query(Advisory)
            .filter(Advisory.plot_id == plot_id)
            .order_by(Advisory.created_at.desc())
            .limit(3)
            .all()
        )
        advisory_items = [
            {"advisory_class": advisory.advisory_class, "date": advisory.created_at.date().isoformat()}
            for advisory in advisories
        ]
        return CommandResponse(
            ok=True,
            message=f"Advisory history for {plot.plot_nickname}: (last 3 advisories)",
            data={"plot_id": plot_id, "advisories": advisory_items},
        )

    raise HTTPException(status_code=400, detail=f"Unknown command: {cmd}")
