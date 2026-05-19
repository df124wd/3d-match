import os
import logging
from datetime import datetime

from fastapi import APIRouter, Request

from api.models.database import KbModel3d, KbModel3dPointCloud, KbProgrammingProjectFile
from api.schemas.requests import IngestRequest
from api.schemas.responses import ApiResponse, IngestData, PointCloudInfo
from api.services.feature_extraction import process_model
from api.services.stp_converter import is_step_file, is_stl_file, step_to_stl

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/models/ingest")
def ingest_model(req: IngestRequest, request: Request):
    session_factory = request.app.state.db_session_factory
    faiss_manager = request.app.state.faiss_manager
    settings = request.app.state.settings

    logger.info("Ingest request: file=%s, creator=%s", req.file_path, req.creator)

    with session_factory() as session:
        # Validate file exists and format
        file_path = req.file_path
        if not os.path.exists(file_path):
            logger.warning("File not found: %s", file_path)
            return ApiResponse(code=40001, message=f"File not found: {file_path}")

        if not (is_stl_file(file_path) or is_step_file(file_path)):
            logger.warning("Unsupported format: %s", file_path)
            return ApiResponse(code=40003, message="Unsupported file format, only STL/STP/STEP accepted")

        file_name = os.path.basename(file_path)
        file_ext = os.path.splitext(file_name)[1].lstrip(".")
        file_size_bytes = os.path.getsize(file_path)

        # Step 1: Create kb_model_3d record
        now = datetime.now()
        model = KbModel3d(
            model_name=file_name,
            creator=req.creator,
            create_time=now,
        )
        session.add(model)
        session.flush()
        model_id = model.id
        logger.info("Created kb_model_3d: id=%d, model_name=%s", model_id, file_name)

        # Step 2: Create kb_programming_project_file record (project_id=NULL, Java assigns later)
        project_file = KbProgrammingProjectFile(
            project_id=None,
            file_name=file_name,
            file_type="FILE",
            physical_path=file_path,
            file_size=file_size_bytes,
            file_ext=file_ext,
            creator=req.creator,
            create_time=now,
        )
        session.add(project_file)
        logger.info("Created kb_programming_project_file: project_id=NULL, file=%s", file_name)

        # Step 3: Convert STP to STL if needed
        stl_path = file_path
        converted = False
        if is_step_file(file_path):
            try:
                stl_path = step_to_stl(file_path)
                converted = True
                logger.info("Converted STP -> STL: %s -> %s", file_path, stl_path)
            except Exception as e:
                session.rollback()
                logger.error("STEP conversion failed: %s", e)
                return ApiResponse(code=50003, message=f"STEP conversion failed: {str(e)}")

        try:
            # Step 4: Process point cloud + extract features
            logger.info("Processing point cloud: %s", stl_path)
            result = process_model(
                stl_path,
                settings.pointcloud_dir,
                settings.sample_points,
                settings.feature_dim,
            )
            logger.info(
                "Feature extraction done: points=%d, method=%s, pcd=%s",
                result.pc_point_count, result.sampling_method, result.pcd_file_path,
            )

            # Step 5: Add or update FAISS (same file overwrites existing vector)
            faiss_manager.add_or_update(file_path, model_id, result.feature_vector)
            logger.info("FAISS updated: model_id=%d, total_vectors=%d", model_id, faiss_manager.vector_count())

            # Step 6: Write kb_model_3d_point_cloud
            pc_record = KbModel3dPointCloud(
                model_id=model_id,
                file_path=result.pcd_file_path,
                file_format="PCD",
                point_count=str(result.pc_point_count),
                sampling_precision=result.sampling_method,
                file_size=_format_file_size(result.pc_file_size_bytes),
                description=req.description or "",
                vector_db_status=1,
                vector_db_time=now,
                creator=req.creator,
                create_time=now,
            )
            session.add(pc_record)

            session.commit()
            logger.info("Ingest complete: model_id=%d", model_id)

            return ApiResponse(data=IngestData(
                model_id=model_id,
                pointcloud=PointCloudInfo(
                    file_path=result.pcd_file_path,
                    file_format="PCD",
                    point_count=str(result.pc_point_count),
                    sampling_precision=result.sampling_method,
                    file_size=_format_file_size(result.pc_file_size_bytes),
                    description=req.description,
                ),
                vector_db_status=1,
                vector_db_time=now,
            ))

        except Exception as e:
            session.rollback()
            logger.error("Ingestion failed for model_id=%d, file=%s: %s", model_id, file_path, e, exc_info=True)
            return ApiResponse(code=50001, message=f"Processing failed: {str(e)}")

        finally:
            if converted and os.path.exists(stl_path):
                os.remove(stl_path)


def _format_file_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
