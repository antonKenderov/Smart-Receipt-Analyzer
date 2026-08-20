import logging
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db.models import Base

logger = logging.getLogger(__name__)

_EXPECTED_DRIVER = "postgresql+psycopg"


@lru_cache
def get_engine() -> Engine:
    url = get_settings().database_url

    if not url.startswith(_EXPECTED_DRIVER):
        logger.warning(
            "DATABASE_URL uses %r; this project pins psycopg 3, so the URL "
            "should start with %r",
            url.split("://", 1)[0],
            _EXPECTED_DRIVER,
        )

    engine = create_engine(
        url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
    )
    logger.debug("Database engine created")
    return engine


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(
        bind=get_engine(),
        expire_on_commit=False,
    )


@contextmanager
def session_scope() -> Iterator[Session]:
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    session = get_sessionmaker()()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    Base.metadata.create_all(bind=get_engine())
    logger.info("Database schema ensured: %s", ", ".join(Base.metadata.tables))
