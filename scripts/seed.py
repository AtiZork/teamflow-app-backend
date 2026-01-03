# scripts/seed.py

import os
import sys
import argparse
from datetime import datetime, timezone, UTC

from dotenv import load_dotenv
from sqlmodel import Session, select

# Ensure root path for relative imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import engine
from core.security import hash_password
from models.models import User, UserRole, Organization

# ✅ Load environment variables
load_dotenv()


def seed_dev_data():
    """Seed development database with demo organization and users."""
    print("🌱 Seeding development data...")

    with Session(engine) as session:
        # -----------------------------
        # 🏢 Create Demo Organization
        # -----------------------------
        org = session.exec(
            select(Organization).where(Organization.name == "Demo Organization")
        ).first()

        if not org:
            org = Organization(name="Demo Organization")
            session.add(org)
            session.commit()
            session.refresh(org)
            print("✅ Created Demo Organization")

        # -----------------------------
        # 👑 Admin User
        # -----------------------------
        admin_user = session.exec(
            select(User).where(User.email == "admin@demo.com")
        ).first()

        if not admin_user:
            admin_user = User(
                full_name="Admin User",
                email="admin@demo.com",
                password_hash=hash_password("admin"),
                role=UserRole.ADMIN,
                is_active=True,
                is_invited=False,
                created_at=datetime.now(timezone.utc),
                date_joined=datetime.now(timezone.utc),  
                organization_id=org.id,
            )

            session.add(admin_user)
            session.commit()
            print("✅ Added Admin User")

        # -----------------------------
        # 👥 Member Users
        # -----------------------------
        member_emails = ["member1@demo.com", "member2@demo.com"]
        for email in member_emails:
            existing_user = session.exec(select(User).where(User.email == email)).first()
            if not existing_user:
                member_user = User(
                    full_name=email.split("@")[0].capitalize(),
                    email=email,
                    password_hash=hash_password("member123"),
                    role=UserRole.MEMBER if hasattr(UserRole, "MEMBER") else "member",
                    organization_id=org.id,
                    is_active=True,
                    is_invited=False,
                    created_at=datetime.now(UTC),
                )
                session.add(member_user)

        session.commit()
        print("✅ Added sample member users")
        print("🌱 Development data seeding complete.")


def seed_staging_data():
    """Seed staging database with minimal safe data."""
    print("🌱 Seeding staging data...")

    with Session(engine) as session:
        # -----------------------------
        # 🏢 Staging Org
        # -----------------------------
        org = session.exec(
            select(Organization).where(Organization.name == "Staging Org")
        ).first()

        if not org:
            org = Organization(name="Staging Org")
            session.add(org)
            session.commit()
            session.refresh(org)
            print("✅ Created Staging Org")

        # -----------------------------
        # 👑 Staging Admin
        # -----------------------------
        admin_user = session.exec(
            select(User).where(User.email == "staging-admin@teamflow.com")
        ).first()

        if not admin_user:
            admin_user = User(
                full_name="Staging Admin",
                email="staging-admin@teamflow.com",
                password_hash=hash_password("staging123"),
                role=UserRole.ADMIN if hasattr(UserRole, "ADMIN") else "admin",
                organization_id=org.id,
                is_active=True,
                is_invited=False,
                created_at=datetime.now(UTC),
            )
            session.add(admin_user)
            session.commit()
            print("✅ Added staging admin user")

        print("🌱 Staging data seeding complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed the TeamFlow database.")
    parser.add_argument(
        "--env",
        choices=["dev", "staging"],
        default="dev",
        help="Select environment to seed (dev or staging)",
    )
    args = parser.parse_args()

    if args.env == "dev":
        seed_dev_data()
    elif args.env == "staging":
        seed_staging_data()
