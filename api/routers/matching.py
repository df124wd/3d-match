import os
import logging
import asyncio
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Request, UploadFile, File, Form

from api.models.database import KbModel3d, KbProjectMold
from api.schemas.responses import ApiResponse, MatchData, MatchItem
from api.services.feature_extraction import stl_to_uniform_point_cloud, compute_esf_feature
from api.services.stp_converter import is_step_file, step_to_stl

logger = logging.getLogger(__name__)
router = APIRouter()
_executor = ThreadPoolExecutor(max_workers=2)

ALLOWED_EXTENSIONS = {".stl", ".stp", ".step"}
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB


@router.post("/models/match")
async def match_model(
    request: Request,
    file: UploadFile = File(..., description="Query 3D model file (STL/STP/STEP)"),
    top_k: int = Form(5, ge=1, le=50, description="Number of results"),
):
    faiss_manager = request.app.state.faiss_manager
    session_factory = request.app.state.db_session_factory
    settings = request.app.state.settings

    # Validate file extension
    safe_name = os.path.basename(file.filename or "")
    file_ext = os.path.splitext(safe_name)[1].lower()
    if file_ext not in ALLOWED_EXTENSIONS:
        logger.warning("Unsupported format: %s", safe_name)
        return ApiResponse(code=40003, message=f"Unsupported file format: {file_ext}")

    logger.info("Match request: file=%s, top_k=%d", safe_name, top_k)

    if faiss_manager.vector_count() == 0:
        logger.warning("FAISS index is empty")
        return ApiResponse(code=50002, message="FAISS index is empty, please ingest models first")

    # Read and validate file size
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        logger.warning("File too large: %d bytes", len(content))
        return ApiResponse(code=40004, message=f"File too large (max {MAX_FILE_SIZE // 1024 // 1024}MB)")

    # Save to temp with safe filename
    tmp_dir = tempfile.mkdtemp()
    tmp_path = os.path.join(tmp_dir, safe_name)
    with open(tmp_path, "wb") as f:
        f.write(content)
    logger.info("Saved query file to temp: %s", tmp_path)

    # Convert STP if needed
    stl_path = tmp_path
    converted = False
    if is_step_file(tmp_path):
        try:
            stl_path = step_to_stl(tmp_path)
            converted = True
            logger.info("Converted STP -> STL: %s -> %s", tmp_path, stl_path)
        except Exception as e:
            logger.error("STEP conversion failed: %s", e)
            _cleanup(tmp_dir)
            return ApiResponse(code=50003, message=f"STEP conversion failed: {str(e)}")

    try:
        # Run CPU-heavy feature extraction in thread pool
        loop = asyncio.get_event_loop()
        logger.info("Extracting features: %s", stl_path)

        point_cloud, _ = await loop.run_in_executor(
            _executor, stl_to_uniform_point_cloud, stl_path, settings.sample_points,
        )
        query_feature = await loop.run_in_executor(
            _executor, compute_esf_feature, point_cloud, settings.feature_dim,
        )
        logger.info("Feature extraction done for match query")

        # FAISS search
        raw_results = faiss_manager.search(query_feature, top_k)
        logger.info("FAISS search returned %d results", len(raw_results))

        # Enrich with database info
        matches = []
        with session_factory() as session:
            for rank, (model_id, distance) in enumerate(raw_results, start=1):
                model = session.query(KbModel3d).filter(
                    KbModel3d.id == model_id, KbModel3d.deleted == 0,
                ).first()

                model_name = model.model_name if model else None
                part_name = model.part_name if model else None
                project_id = model.project_id if model else None
                project_name = None

                if project_id:
                    project = session.query(KbProjectMold).filter(
                        KbProjectMold.id == project_id, KbProjectMold.deleted == 0,
                    ).first()
                    project_name = project.project_name if project else None

                max_dist = max(d for _, d in raw_results) if raw_results else 1.0
                similarity = 1.0 - (distance / max_dist) if max_dist > 0 else 0.0

                matches.append(MatchItem(
                    rank=rank,
                    model_id=model_id,
                    model_name=model_name,
                    part_name=part_name,
                    project_id=project_id,
                    project_name=project_name,
                    distance=round(distance, 6),
                    similarity=round(similarity, 4),
                ))

        logger.info(
            "Match complete: query=%s, top_match=model_id:%d dist:%.4f",
            safe_name,
            matches[0].model_id if matches else 0,
            matches[0].distance if matches else 0,
        )

        return ApiResponse(data=MatchData(
            query_filename=safe_name,
            top_k=top_k,
            matches=matches,
        ))

    except Exception as e:
        logger.error("Match failed: %s", e, exc_info=True)
        return ApiResponse(code=50001, message=f"Match failed: {str(e)}")

    finally:
        if converted and os.path.exists(stl_path):
            os.remove(stl_path)
        _cleanup(tmp_dir)


def _cleanup(tmp_dir: str) -> None:
    try:
        shutil.rmtree(tmp_dir)
    except OSError as e:
        logger.warning("Failed to cleanup temp dir %s: %s", tmp_dir, e)
