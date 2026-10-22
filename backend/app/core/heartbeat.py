"""Worker heartbeat table (R6): proves the background process is alive, for alerts."""

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from app.core.models import Base


class ServiceHeartbeat(Base):
    __tablename__ = "service_heartbeats"

    name: Mapped[str] = mapped_column(String(50), primary_key=True)
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


def record_heartbeat(session_factory: sessionmaker[Session], name: str = "worker") -> None:
    """Upsert the heartbeat in its own short transaction; failures must not kill the worker loop."""
    with session_factory() as session, session.begin():
        session.execute(
            insert(ServiceHeartbeat)
            .values(name=name, last_seen=func.now())
            .on_conflict_do_update(
                index_elements=[ServiceHeartbeat.name],
                set_={"last_seen": func.now()},
            )
        )
