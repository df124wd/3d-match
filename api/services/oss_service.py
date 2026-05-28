import logging
from urllib.parse import quote
from pathlib import Path

import alibabacloud_oss_v2 as oss
import alibabacloud_oss_v2.aio as oss_aio

logger = logging.getLogger(__name__)


class OssStorage:
    """Thin wrapper over Alibaba Cloud OSS v2 async SDK."""

    def __init__(self, bucket: str, region: str, access_key_id: str, access_key_secret: str):
        self.bucket = bucket
        self.region = region
        self._access_key_id = access_key_id
        self._access_key_secret = access_key_secret
        self.client: oss_aio.AsyncClient | None = None

    def public_url(self, key: str) -> str:
        encoded_key = quote(key, safe="/")
        return f"https://{self.bucket}.oss-{self.region}.aliyuncs.com/{encoded_key}"

    async def _ensure_client(self) -> oss_aio.AsyncClient:
        if self.client is None:
            cfg = oss.config.load_default()
            cfg.credentials_provider = oss.credentials.StaticCredentialsProvider(
                access_key_id=self._access_key_id,
                access_key_secret=self._access_key_secret,
            )
            cfg.region = self.region
            self.client = oss_aio.AsyncClient(cfg)
            logger.info("OSS client initialized: bucket=%s, region=%s", self.bucket, self.region)
        return self.client

    async def upload_file(self, local_path: str | Path, object_key: str) -> str:
        """Upload a local file to OSS and return the public URL."""
        client = await self._ensure_client()
        path = Path(local_path)
        with open(path, "rb") as f:
            await client.put_object(
                oss.PutObjectRequest(
                    bucket=self.bucket,
                    key=object_key,
                    body=f.read(),
                )
            )
        url = self.public_url(object_key)
        logger.info("Uploaded to OSS: %s -> %s", path.name, url)
        return url

    async def delete_file(self, object_key: str) -> bool:
        """Delete an object from OSS by its key (not full URL)."""
        client = await self._ensure_client()
        result = await client.delete_object(
            oss.DeleteObjectRequest(bucket=self.bucket, key=object_key)
        )
        success = result.status_code == 204
        if success:
            logger.info("Deleted from OSS: %s", object_key)
        else:
            logger.warning("Failed to delete from OSS: %s (status=%d)", object_key, result.status_code)
        return success

    async def close(self) -> None:
        if self.client:
            await self.client.close()
            self.client = None
            logger.info("OSS client closed")
