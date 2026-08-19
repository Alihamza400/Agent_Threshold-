"""Bootstrap: create the default org + admin user from settings.

Run once:  uv run --directory services/api-gateway python -m app.seed
"""

from __future__ import annotations

import logging

from at_shared.config import get_settings
from at_shared.db import SessionLocal, init_db
from at_shared.models import Organization, User
from at_shared.security import hash_password
from at_shared.uuid7 import uuid7
from sqlalchemy import select

log = logging.getLogger(__name__)


def seed() -> None:
    settings = get_settings()
    init_db()

    with SessionLocal() as db:
        org = db.scalar(select(Organization).where(Organization.name == "AgentThreshold"))
        if org is None:
            org = Organization(id=uuid7(), name="AgentThreshold", tier="enterprise")
            db.add(org)
            db.flush()
            log.info("created organization %s", org.id)

        admin = db.scalar(select(User).where(User.email == settings.bootstrap_admin_email))
        if admin is None:
            admin = User(
                id=uuid7(),
                org_id=org.id,
                email=settings.bootstrap_admin_email,
                role="admin",
                password_hash=hash_password(settings.bootstrap_admin_password),
                is_active=True,
            )
            db.add(admin)
            log.info("created admin %s", admin.email)

        db.commit()
        log.info("seed complete")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    seed()
