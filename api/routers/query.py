import logging

from fastapi import APIRouter, Request

from api.models.database import KbModel3dPointCloud
from api.schemas.responses import ApiResponse, QueryData, PointCloudInfo

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/models/{model_id}/pointcloud")
def get_pointcloud(model_id: int, request: Request):
    logger.info("Query pointcloud: model_id=%d", model_id)
    session_factory = request.app.state.db_session_factory

    with session_factory() as session:
        record = session.query(KbModel3dPointCloud).filter(
            KbModel3dPointCloud.model_id == model_id,
        ).first()

        if not record:
            logger.warning("Point cloud not found: model_id=%d", model_id)
            return ApiResponse(code=40001, message=f"Point cloud for model {model_id} not found")

        pointcloud = None
        if record.file_path:
            pointcloud = PointCloudInfo(
                file_path=record.file_path,
                file_format=record.file_format or "",
                point_count=record.point_count or "",
                sampling_precision=record.sampling_precision or "",
                file_size=record.file_size or "",
                description=record.description,
            )

        logger.info(
            "Query result: model_id=%d, vector_db_status=%d, has_file=%s",
            model_id, record.vector_db_status, pointcloud is not None,
        )

        return ApiResponse(data=QueryData(
            model_id=model_id,
            pointcloud=pointcloud,
            vector_db_status=record.vector_db_status,
            vector_db_time=record.vector_db_time,
        ))
