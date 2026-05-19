from sqlalchemy import Column, BigInteger, String, DateTime, Text, Integer, SmallInteger
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class KbModel3d(Base):
    __tablename__ = "kb_model_3d"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    project_id = Column(BigInteger, nullable=True)
    model_name = Column(String(200), nullable=True)
    part_name = Column(String(100), nullable=True)
    thumbnail_url = Column(String(500), default="")
    preview_url = Column(String(500), default="")
    create_time = Column(DateTime, nullable=False)
    creator = Column(String(64), default="")
    update_time = Column(DateTime, nullable=True)
    updater = Column(String(64), default="")
    deleted = Column(SmallInteger, nullable=False, default=0)


class KbModel3dPointCloud(Base):
    __tablename__ = "kb_model_3d_point_cloud"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    model_id = Column(BigInteger, nullable=True, unique=True)
    file_path = Column(String(1000), nullable=True)
    file_format = Column(String(50), default="")
    point_count = Column(String(50), default="")
    sampling_precision = Column(String(50), default="")
    file_size = Column(String(50), default="")
    description = Column(Text, nullable=True)
    vector_db_status = Column(SmallInteger, nullable=False, default=0)
    vector_db_time = Column(DateTime, nullable=True)
    create_time = Column(DateTime, nullable=False)
    creator = Column(String(64), default="")
    update_time = Column(DateTime, nullable=True)
    updater = Column(String(64), default="")
    deleted = Column(SmallInteger, nullable=False, default=0)


class KbProjectMold(Base):
    __tablename__ = "kb_project_mold"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    project_name = Column(String(200), nullable=False)
    project_summary = Column(String(1000), default="")
    mold_category = Column(String(100), nullable=True)
    project_keywords = Column(String(500), default="")
    folder_path = Column(String(1000), nullable=True)
    model_count = Column(Integer, default=0)
    search_count = Column(Integer, default=0)
    reference_count = Column(Integer, default=0)
    create_time = Column(DateTime, nullable=False)
    creator = Column(String(64), default="")
    update_time = Column(DateTime, nullable=True)
    updater = Column(String(64), default="")
    deleted = Column(SmallInteger, nullable=False, default=0)
    folder_id = Column(BigInteger, nullable=True)


class KbProgrammingProjectFile(Base):
    __tablename__ = "kb_programming_project_file"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    project_id = Column(BigInteger, nullable=True)
    file_name = Column(String(200), nullable=True)
    file_type = Column(String(20), nullable=True)
    physical_path = Column(String(1000), nullable=True)
    file_size = Column(BigInteger, default=0)
    file_ext = Column(String(50), default="")
    create_time = Column(DateTime, nullable=False)
    creator = Column(String(64), default="")
    update_time = Column(DateTime, nullable=True)
    updater = Column(String(64), default="")
    deleted = Column(SmallInteger, nullable=False, default=0)
