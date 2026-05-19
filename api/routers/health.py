from sqlalchemy import text
from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
def health_check(request: Request):
    faiss_manager = request.app.state.faiss_manager
    mysql_ok = False
    try:
        session_factory = request.app.state.db_session_factory
        with session_factory() as session:
            session.execute(text("SELECT 1"))
        mysql_ok = True
    except Exception:
        pass

    return {
        "code": 0,
        "message": "success",
        "data": {
            "status": "healthy" if (faiss_manager and mysql_ok) else "degraded",
            "faiss_loaded": faiss_manager is not None,
            "faiss_vector_count": faiss_manager.vector_count() if faiss_manager else 0,
            "mysql_connected": mysql_ok,
        },
    }
