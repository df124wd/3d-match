import os
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Request, UploadFile, File, Form

from api.models.database import KbModel3d, KbModel3dPointCloud, KbProgrammingProjectFile
from api.schemas.responses import ApiResponse, IngestData, PointCloudInfo
from api.services.feature_extraction import process_model
from api.services.stp_converter import is_step_file, step_to_stl

logger = logging.getLogger(__name__)
router = APIRouter()

ALLOWED_EXTENSIONS = {".stl", ".stp", ".step"}
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB


@router.post("/models/ingest")
async def ingest_model(
    request: Request,
    file: UploadFile = File(..., description="3D model file (STL/STP/STEP)"),
    creator: str = Form(..., max_length=64, description="Creator user ID or name"),
    description: str = Form(None, max_length=500, description="Point cloud description"),
):
    settings = request.app.state.settings
    session_factory = request.app.state.db_session_factory
    faiss_manager = request.app.state.faiss_manager

    # Validate file extension
    raw_name = file.filename or ""
    safe_name = os.path.basename(raw_name)
    file_ext = os.path.splitext(safe_name)[1].lower()
    if file_ext not in ALLOWED_EXTENSIONS:
        logger.warning("Unsupported format: %s", raw_name)
        return ApiResponse(code=40003, message=f"Unsupported file format: {file_ext}, only STL/STP/STEP accepted")

    # Read and validate file size
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        logger.warning("File too large: %d bytes", len(content))
        return ApiResponse(code=40004, message=f"File too large (max {MAX_FILE_SIZE // 1024 // 1024}MB)")
    file_size_bytes = len(content)

    # Save with unique name to avoid collision
    os.makedirs(settings.upload_dir, exist_ok=True)
    unique_name = f"{uuid.uuid4().hex[:8]}_{safe_name}"
    file_path = os.path.join(settings.upload_dir, unique_name)
    with open(file_path, "wb") as f:
        f.write(content)
    ext = file_ext.lstrip(".")

    logger.info("Ingest request: file=%s (%d bytes), creator=%s", safe_name, file_size_bytes, creator)

    with session_factory() as session:
        # Step 1: Create kb_model_3d record
        now = datetime.now()
        model = KbModel3d(
            model_name=safe_name,
            creator=creator,
            create_time=now,
        )
        session.add(model)
        session.flush()
        model_id = model.id
        logger.info("Created kb_model_3d: id=%d, model_name=%s", model_id, safe_name)

        # Step 2: Create kb_programming_project_file record (project_id=NULL, Java assigns later)
        project_file = KbProgrammingProjectFile(
            project_id=None,
            file_name=safe_name,
            file_type="FILE",
            physical_path=file_path,
            file_size=file_size_bytes,
            file_ext=ext,
            creator=creator,
            create_time=now,
        )
        session.add(project_file)
        logger.info("Created kb_programming_project_file: project_id=NULL, file=%s", safe_name)

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

            # Step 5: Add or update FAISS (dedup by original filename, not UUID path)
            faiss_manager.add_or_update(safe_name, model_id, result.feature_vector)
            logger.info("FAISS updated: model_id=%d, total_vectors=%d", model_id, faiss_manager.vector_count())

            # Step 6: Write kb_model_3d_point_cloud
            pc_record = KbModel3dPointCloud(
                model_id=model_id,
                file_path=result.pcd_file_path,
                file_format="PCD",
                point_count=str(result.pc_point_count),
                sampling_precision=result.sampling_method,
                file_size=_format_file_size(result.pc_file_size_bytes),
                description=description or "",
                vector_db_status=1,
                vector_db_time=now,
                creator=creator,
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
                    description=description,
                ),
                vector_db_status=1,
                vector_db_time=now,
            ))

        except Exception as e:
            session.rollback()
            logger.error("Ingestion failed for model_id=%d, file=%s: %s", model_id, safe_name, e, exc_info=True)
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
