from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # MySQL
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = ""
    mysql_database: str = "3dmatch"
    mysql_pool_size: int = 5

    # FAISS
    faiss_index_dir: str = "./faiss_index"
    feature_dim: int = 64

    # Point cloud
    sample_points: int = 15000
    pointcloud_dir: str = "./pointcloud"

    # STP conversion
    step_converter: str = "pythonocc"

    model_config = {"env_file": ".env", "env_prefix": "APP_"}
