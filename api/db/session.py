import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from api.config import Settings

logger = logging.getLogger(__name__)


def create_engine_and_session(settings: Settings):
    url = (
        f"mysql+pymysql://{settings.mysql_user}:{settings.mysql_password}"
        f"@{settings.mysql_host}:{settings.mysql_port}/{settings.mysql_database}"
        f"?charset=utf8mb4"
    )
    engine = create_engine(
        url,
        pool_size=settings.mysql_pool_size,
        pool_recycle=3600,
        pool_pre_ping=True,
        echo=settings.debug,
    )
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    return engine, session_factory
