from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import notify, services
from app.auth import current_user, require_agent
from app.db import get_db
from app.models import utcnow
from app.sla import Calendar
from app.models import (
    AGENTS,
    AGENTS_DEFAULT_ME,
    CATEGORIES,
    PRIORITIES,
    SLA_HOURS,
    STATUSES,
    Ticket,
)
from app.models import User as UserModel
from app.schemas import (
    EventCreate,
    TicketCreate,
    TicketDetail,
    TicketPatch,
    TicketSummary,
)

router = APIRouter(prefix="/api")


@router.get("/meta")
def meta(me: UserModel = Depends(require_agent)):
    return {
        "agents": AGENTS,
        "categories": CATEGORIES,
        "priorities": [
            {"id": p, "hours": SLA_HOURS[p]} for p in PRIORITIES
        ],
        "statuses": STATUSES,
        "me": me.display_name,
    }


@router.get("/users/lookup")
def lookup_users(q: str = "", me: UserModel = Depends(require_agent),
                 db: Session = Depends(get_db)):
    """Existing accounts an agent can file a ticket for."""
    stmt = select(UserModel).where(UserModel.is_active)
    if q.strip():
        like = f"%{q.lower().strip()}%"
        stmt = stmt.where(
            func.lower(UserModel.display_name).like(like)
            | func.lower(UserModel.email).like(like)
            | func.lower(UserModel.org).like(like)
        )
    rows = db.scalars(stmt.order_by(UserModel.display_name).limit(20)).all()
    return [
        {"email": u.email, "display_name": u.display_name,
         "org": u.org, "role": u.effective_role}
        for u in rows
    ]


@router.get("/portal/meta")
def portal_meta(me: UserModel = Depends(current_user)):
    return {
        "categories": CATEGORIES,
        "priorities": [{"id": p, "hours": SLA_HOURS[p]} for p in PRIORITIES],
    }


@router.get("/tickets", response_model=list[TicketSummary])
def list_tickets(
    me: UserModel = Depends(require_agent),
    view: str = Query("all", pattern="^(all|mine|unassigned|breach|done)$"),
    track: str | None = Query(None, pattern="^(saas|it)$"),
    q: str | None = None,
    db: Session = Depends(get_db),
):
    return services.list_tickets(db, view, track, q)


@router.post("/tickets", response_model=TicketDetail, status_code=201)
def create_ticket(
    payload: TicketCreate,
    me: UserModel = Depends(current_user),
    db: Session = Depends(get_db),
):
    if payload.category not in CATEGORIES[payload.track]:
        raise HTTPException(422, f"'{payload.category}' is not a {payload.track} topic")
    fields = payload.model_dump()
    on_behalf = fields.pop("requester_email", None)

    subject_user = me
    if on_behalf and on_behalf.lower().strip() != me.email:
        if not me.is_staff:
            raise HTTPException(403, "You can only file tickets for yourself")
        subject_user = db.scalar(
            select(UserModel).where(
                func.lower(UserModel.email) == on_behalf.lower().strip(),
                UserModel.is_active,
            )
        )
        if subject_user is None:
            raise HTTPException(422, "No active account with that address")

    fields.update(
        requester=subject_user.display_name,
        email=subject_user.email,
        org=subject_user.org,
    )
    t = Ticket(ref=services.next_ref(db), **fields)
    t.due_at = Calendar(db).deadline(utcnow(), t.priority)
    db.add(t)
    db.flush()
    notify.on_new_ticket(db, t)
    db.commit()
    db.refresh(t)
    return t


@router.get("/tickets/{ref}", response_model=TicketDetail)
def get_ticket(ref: str, me: UserModel = Depends(require_agent), db: Session = Depends(get_db)):
    t = services.get_or_404(db, ref)
    if not t:
        raise HTTPException(404, f"No ticket {ref}")
    return t


@router.patch("/tickets/{ref}", response_model=TicketDetail)
def patch_ticket(ref: str, payload: TicketPatch, me: UserModel = Depends(require_agent), db: Session = Depends(get_db)):
    t = services.get_or_404(db, ref)
    if not t:
        raise HTTPException(404, f"No ticket {ref}")
    changes = payload.model_dump()
    services.apply_patch(db, t, me.display_name, **changes)
    db.flush()
    notify.on_patch(db, t, changes, me.display_name)
    db.commit()
    db.refresh(t)
    return t


@router.post("/tickets/{ref}/events", response_model=TicketDetail, status_code=201)
def add_event(ref: str, payload: EventCreate, me: UserModel = Depends(require_agent), db: Session = Depends(get_db)):
    t = services.get_or_404(db, ref)
    if not t:
        raise HTTPException(404, f"No ticket {ref}")
    ev = services.add_event(db, t, me.display_name, payload.kind, payload.body)
    db.flush()
    notify.on_event(db, t, ev)
    db.commit()
    db.refresh(t)
    return t


# --- portal: no internal notes ever cross this line ---


@router.get("/portal/tickets", response_model=list[TicketDetail])
def portal_tickets(me: UserModel = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Ticket).where(Ticket.email == me.email).order_by(Ticket.created_at.desc())
    ).all()
    out = []
    for t in rows:
        d = TicketDetail.model_validate(t)
        d.events = [e for e in d.events if e.kind == "comment"]
        out.append(d)
    return out


@router.post("/portal/tickets/{ref}/events", response_model=TicketDetail, status_code=201)
def portal_reply(ref: str, payload: EventCreate, me: UserModel = Depends(current_user), db: Session = Depends(get_db)):
    t = services.get_or_404(db, ref)
    if not t or t.email != me.email:
        raise HTTPException(404, f"No ticket {ref} for that address")
    ev = services.add_event(db, t, me.display_name, "comment", payload.body)
    db.flush()
    notify.on_event(db, t, ev)
    db.commit()
    db.refresh(t)
    d = TicketDetail.model_validate(t)
    d.events = [e for e in d.events if e.kind == "comment"]
    return d


@router.get("/counts")
def counts(me: UserModel = Depends(require_agent), db: Session = Depends(get_db)):
    return {"views": services.counts(db), "tracks": services.track_counts(db)}


@router.delete("/tickets/{ref}/events/{event_id}", response_model=TicketDetail)
def delete_event(ref: str, event_id: int, me: UserModel = Depends(require_agent), db: Session = Depends(get_db)):
    t = services.get_or_404(db, ref)
    if not t:
        raise HTTPException(404, f"No ticket {ref}")
    ev, problem = services.delete_event(db, t, event_id, me.display_name)
    if problem:
        raise HTTPException(404 if ev is None and "No such" in problem else 403, problem)
    db.commit()
    db.refresh(t)
    return t


@router.delete("/portal/tickets/{ref}/events/{event_id}", response_model=TicketDetail)
def portal_delete_event(ref: str, event_id: int, me: UserModel = Depends(current_user), db: Session = Depends(get_db)):
    t = services.get_or_404(db, ref)
    if not t or t.email != me.email:
        raise HTTPException(404, f"No ticket {ref} for that address")
    ev, problem = services.delete_event(db, t, event_id, me.display_name, as_requester=True)
    if problem:
        raise HTTPException(404 if ev is None and "No such" in problem else 403, problem)
    db.commit()
    db.refresh(t)
    d = TicketDetail.model_validate(t)
    d.events = [e for e in d.events if e.kind == "comment"]
    return d
