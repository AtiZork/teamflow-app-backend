from sqlmodel import SQLModel, create_engine, Session
from typing import Generator
from dotenv import load_dotenv
import os
import logging

# ============================================================
# ✅ Load environment variables
# ============================================================
load_dotenv()
logger = logging.getLogger(__name__)

# ============================================================
# ✅ Database URL setup (PostgreSQL preferred)
# ============================================================
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    # Fallback for local dev (sqlite)
    DATABASE_URL = "sqlite:///./teamflow.db"
    logger.warning("⚠️ DATABASE_URL not found — using local SQLite database.")
else:
    logger.info(f"✅ Using database from environment: {DATABASE_URL}")

# ============================================================
# ✅ Create SQLModel engine
# ============================================================
# For PostgreSQL, pool_pre_ping avoids stale connections
engine = create_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True
)

# ============================================================
# ✅ Create tables (called at startup)
# ============================================================
def create_db_and_tables() -> None:
    """
    Create all database tables based on SQLModel models.
    This runs automatically at app startup.
    """
    try:
        SQLModel.metadata.create_all(engine)
        logger.info("✅ All database tables created successfully.")
    except Exception as e:
        logger.error(f"❌ Failed to create tables: {e}")
        raise

# ============================================================
# ✅ Dependency: FastAPI session generator
# ============================================================
def get_session() -> Generator[Session, None, None]:
    """
    Provides a SQLModel Session to FastAPI dependencies.
    Closes automatically after request completes.
    """
    with Session(engine) as session:
        yield session











# from sqlmodel import SQLModel, create_engine, Session
# from typing import Generator
# import logging

# # ============================================================
# # ✅ Logging setup
# # ============================================================
# logger = logging.getLogger(__name__)

# # ============================================================
# # ✅ SQLite Database configuration
# # ============================================================
# DATABASE_URL = "sqlite:///./teamflow.db"

# # Required for SQLite with FastAPI (thread safety)
# engine = create_engine(
#     DATABASE_URL,
#     echo=False,
#     connect_args={"check_same_thread": False},
# )

# logger.info("✅ Using SQLite database: teamflow.db")

# # ============================================================
# # ✅ Create tables (called at startup)
# # ============================================================
# def create_db_and_tables() -> None:
#     """
#     Create all database tables based on SQLModel models.
#     """
#     try:
#         SQLModel.metadata.create_all(engine)
#         logger.info("✅ All database tables created successfully.")
#     except Exception as e:
#         logger.error(f"❌ Failed to create tables: {e}")
#         raise

# # ============================================================
# # ✅ FastAPI dependency: database session
# # ============================================================
# def get_session() -> Generator[Session, None, None]:
#     """
#     Provides a SQLModel Session to FastAPI dependencies.
#     Automatically closes after request.
#     """
#     with Session(engine) as session:
#         yield session
