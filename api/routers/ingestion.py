import os
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Request, UploadFile, File, Form

from api.models.database import KbModel3d, KbModel3dPointCloud, KbProgrammingProjectFile
from api.schemas.responses import ApiResponse, PointCloudInfo, BatchIngestData, BatchIngestItem
from api.services.feature_extraction import process_model
from api.services.stp_converter import is_step_file, step_to_stl

logger = logging.getLogger(__name__)
router = APIRouter()

ALLOWED_EXTENSIONS = {".stl", ".stp", ".step"}
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
CHUNK_SIZE = 8192


def _sanitize_filename(filename: str) -> str:
    """Remove null bytes, path separators, and directory traversal attempts."""
    clean = filename.replace("\x00", "").replace("/", "_").replace("\\", "_")
    clean = os.path.basename(clean)
    if not clean or clean == "." or clean == "..":
        return "unnamed"
    return clean


async def _read_with_size_limit(upload_file: UploadFile, max_size: int) -> tuple[bytes | None, str | None]:
    """Read file content in chunks, returning (content, error) tuple."""
    total_size = 0
    chunks: list[bytes] = []
    while True:
        chunk = await upload_file.read(CHUNK_SIZE)
        if not chunk:
            break
        total_size += len(chunk)
        if total_size > max_size:
            await upload_file.close()
            return None, f"File too large (max {max_size // 1024 // 1024}MB)"
        chunks.append(chunk)
    return b"".join(chunks), None


@router.post("/models/ingest")
async def ingest_model(
    request: Request,
    files: list[UploadFile] = File(..., description="3D model files (STL/STP/STEP)"),
    creator: str = Form(..., max_length=64, description="Creator user ID or name"),
    description: str = Form(None, max_length=500, description="Point cloud description"),
):
    settings = request.app.state.settings
    session_factory = request.app.state.db_session_factory
    faiss_manager = request.app.state.faiss_manager
    oss_storage = getattr(request.app.state, "oss_storage", None)

    os.makedirs(settings.upload_dir, exist_ok=True)

    results: list[BatchIngestItem] = []

    for upload_file in files:
        try:
            item = await _process_single_file(
                upload_file=upload_file,
                creator=creator,
                description=description,
                settings=settings,
                session_factory=session_factory,
                faiss_manager=faiss_manager,
                oss_storage=oss_storage,
            )
        except Exception as e:
            fname = _sanitize_filename(upload_file.filename or "unknown")
            logger.critical("Unexpected error processing %s: %s", fname, e, exc_info=True)
            item = BatchIngestItem(filename=fname, error="Internal server error")
        results.append(item)

    success_count = sum(1 for r in results if r.error is None)
    failed_count = len(results) - success_count

    logger.info("Batch ingest done: total=%d, success=%d, failed=%d", len(results), success_count, failed_count)

    return ApiResponse(data=BatchIngestData(
        total=len(results),
        success=success_count,
        failed=failed_count,
        results=results,
    ))


async def _process_single_file(
    upload_file: UploadFile,
    creator: str,
    description: str | None,
    settings,
    session_factory,
    faiss_manager,
    oss_storage,
) -> BatchIngestItem:
    """Process a single uploaded file: validate, save, upload OSS, extract features, index."""

    raw_name = upload_file.filename or ""
    safe_name = _sanitize_filename(raw_name)
    file_ext = os.path.splitext(safe_name)[1].lower()

    if file_ext not in ALLOWED_EXTENSIONS:
        logger.info("Rejected unsupported format: %s", raw_name)
        return BatchIngestItem(filename=safe_name, error=f"Unsupported format: {file_ext}")

    content, size_error = await _read_with_size_limit(upload_file, MAX_FILE_SIZE)
    if size_error:
        logger.info("Rejected file too large: %s", safe_name)
        return BatchIngestItem(filename=safe_name, error=size_error)

    file_size_bytes = len(content)

    # Save locally with UUID prefix to avoid collision
    unique_name = f"{uuid.uuid4().hex[:8]}_{safe_name}"
    local_path = os.path.join(settings.upload_dir, unique_name)
    with open(local_path, "wb") as f:
        f.write(content)
    ext = file_ext.lstrip(".")

    logger.info("Ingest request: file=%s (%d bytes), creator=%s", safe_name, file_size_bytes, creator)

    # Upload to OSS
    oss_url = None
    if oss_storage is not None:
        try:
            now_str = datetime.now().strftime("%Y/%m/%d")
            object_key = f"uploads/3d/{creator}/{now_str}/{uuid.uuid4().hex}{file_ext}"
            oss_url = await oss_storage.upload_file(local_path, object_key)
            logger.info("OSS upload success: %s -> %s", safe_name, oss_url)
        except Exception as e:
            logger.error("OSS upload failed for %s: %s", safe_name, e, exc_info=True)

    with session_factory() as session:
        try:
            now = datetime.now()

            # Step 1: Create kb_model_3d record
            model = KbModel3d(
                model_name=safe_name,
                creator=creator,
                create_time=now,
            )
            session.add(model)
            session.flush()
            model_id = model.id
            logger.info("Created kb_model_3d: id=%d, model_name=%s", model_id, safe_name)

            # Step 2: Create kb_programming_project_file — store OSS URL if available
            project_file = KbProgrammingProjectFile(
                project_id=None,
                file_name=safe_name,
                file_type="FILE",
                physical_path=oss_url or local_path,
                file_size=file_size_bytes,
                file_ext=ext,
                creator=creator,
                create_time=now,
            )
            session.add(project_file)
            logger.info("Created kb_programming_project_file: file=%s, path=%s", safe_name, oss_url or local_path)

            # Step 3: Convert STP to STL if needed
            stl_path = local_path
            converted = False
            if is_step_file(local_path):
                try:
                    stl_path = step_to_stl(local_path)
                    converted = True
                    logger.info("Converted STP -> STL: %s -> %s", local_path, stl_path)
                except Exception as e:
                    session.rollback()
                    logger.error("STEP conversion failed: %s", e)
                    _cleanup_file(local_path)
                    return BatchIngestItem(filename=safe_name, error=f"STEP conversion failed: {str(e)}")

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
                    "Feature extraction done: points=%d, method=%s",
                    result.pc_point_count, result.sampling_method,
                )

                # Step 5: Add or update FAISS (dedup by creator + filename)
                dedup_key = f"{creator}_{safe_name}"
                faiss_manager.add_or_update(dedup_key, model_id, result.feature_vector)
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

                return BatchIngestItem(
                    filename=safe_name,
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
                    oss_url=oss_url,
                )

            except Exception as e:
                session.rollback()
                logger.error("Ingestion failed for file=%s: %s", safe_name, e, exc_info=True)
                return BatchIngestItem(filename=safe_name, error=f"Processing failed: {str(e)}")

            finally:
                if converted and os.path.exists(stl_path):
                    os.remove(stl_path)

        except Exception as e:
            session.rollback()
            logger.error("DB operation failed for file=%s: %s", safe_name, e, exc_info=True)
            return BatchIngestItem(filename=safe_name, error=f"Database error: {str(e)}")


def _cleanup_file(path: str) -> None:
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def _format_file_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
