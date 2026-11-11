from datetime import date

from pydantic import BaseModel

from phoebe.db import Database

PERSONA_ID = "alex-rivera"


class Persona(BaseModel):
    id: str
    name: str
    team_id: str
    team_name: str
    department_id: str
    department_name: str
    start_date: date
    manager: str | None
    buddy: str | None


def get_persona(db: Database) -> Persona:
    """The demo persona. Uses seed group names (no session needed)."""
    rows = db.fetch(
        """
        select p.id, p.name, p.team_id, t.name as team_name,
               d.id as department_id, d.name as department_name,
               p.start_date, p.manager, p.buddy
        from people p
        join groups t on t.id = p.team_id
        join groups d on d.id = t.parent_id
        where p.id = :id
        """,
        {"id": PERSONA_ID},
    )
    if not rows:
        raise LookupError(f"persona {PERSONA_ID} not found")
    return Persona(**rows[0])
