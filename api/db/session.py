import logging

from sqlalchemy import create_engine
from sqlalchemy.engine.url import URL
from sqlalchemy.orm import sessionmaker, Session
from api.config import Settings

logger = logging.getLogger(__name__)


def create_engine_and_session(settings: Settings):
    url = URL.create(
        drivername="mysql+pymysql",
        username=settings.mysql_user,
        password=settings.mysql_password,
        host=settings.mysql_host,
        port=settings.mysql_port,
        database=settings.mysql_database,
        query={"charset": "utf8mb4"},
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
