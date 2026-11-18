"""CRM rules that must hold no matter which screen calls them: stage changes are logged, conversion is all-or-nothing."""
from decimal import Decimal
from sqlalchemy.orm import Session
from app.models import models as m


def log(db: Session, lead: m.Lead, user: dict, kind: str, *, text: str | None = None, frm: str | None = None, to: str | None = None) -> m.LeadActivity:
    a = m.LeadActivity(lead_id=lead.id, kind=kind, text=text, from_stage=frm, to_stage=to, user_id=user.get("sub"), user_name=user.get("name"))
    db.add(a); return a


def find_client_by_phone(db: Session, phone_norm: str | None) -> m.Client | None:
    if not phone_norm: return None
    return db.query(m.Client).filter_by(phone_norm=phone_norm).order_by(m.Client.created_at).first()


def create_project(db: Session, *, project_number: str, name: str, client_id: str, budget: Decimal | None) -> m.Project:
    p = m.Project(project_number=project_number, name=name, client_id=client_id, budget=budget, status="SURVEY")
    db.add(p); db.flush(); return p


class ConvertError(Exception):
    def __init__(self, status: int, detail: str): super().__init__(detail); self.status, self.detail = status, detail


def convert_lead(db: Session, lead: m.Lead, user: dict, *, project_number: str, project_name: str | None, budget: Decimal | None) -> dict:
    """Lead -> client (reused if the same phone already exists) + project, in ONE transaction.
    Nothing is committed here; the caller commits once, and any exception means the caller rolls back, so a half-converted lead can't exist."""
    if lead.project_id: raise ConvertError(409, "This lead was already converted")
    if lead.stage == "LOST": raise ConvertError(409, "A lost lead can't be converted. Move it back to an open stage first.")
    if db.query(m.Project).filter_by(project_number=project_number).first(): raise ConvertError(409, f"Project number {project_number} already exists")
    client = find_client_by_phone(db, lead.phone_norm)
    reused = client is not None
    if not client:
        client = m.Client(name=lead.name, phone=lead.phone, phone_norm=lead.phone_norm, email=lead.email, city=lead.city)
        db.add(client); db.flush()
    project = create_project(db, project_number=project_number, name=project_name or f"{lead.name} — {lead.requirement or 'Interior'}"[:120],
                             client_id=client.id, budget=budget if budget is not None else lead.budget)
    from app.services import access
    db.flush()
    for uid in dict.fromkeys([user.get("sub"), lead.assigned_to]): access.add_member(db, project.id, uid, user)   # converter + lead owner join the team
    before = lead.stage
    lead.client_id, lead.project_id, lead.stage = client.id, project.id, "WON"
    log(db, lead, user, "CONVERTED", frm=before, to="WON",
        text=f"Converted: {'existing' if reused else 'new'} client {client.name}, project {project.project_number}")
    return {"client_id": client.id, "client_reused": reused, "project_id": project.id, "project_number": project.project_number}
