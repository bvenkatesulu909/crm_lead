"""Owner setup can insert + commit data that the restricted app connection sees."""

import uuid

from sqlalchemy import select

from app.modules.identity.models import Tenant


def test_owner_commits_data_visible_to_app(committed_owner_data, db_session, clean_committed_data):
    tenant_id = uuid.uuid4()
    committed_owner_data.add(
        Tenant(
            id=tenant_id, name="Bootstrap GmbH", slug=f"boot-{tenant_id.hex[:8]}", status="active"
        )
    )
    committed_owner_data.commit()

    seen = db_session.scalar(select(Tenant).where(Tenant.id == tenant_id))
    assert seen is not None and seen.name == "Bootstrap GmbH"
