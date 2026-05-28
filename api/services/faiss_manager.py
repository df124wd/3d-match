import os
import logging
import threading
from typing import Dict, List, Tuple

import faiss
import numpy as np

logger = logging.getLogger(__name__)


class FaissManager:
    """FAISS 索引管理器。

    数据源: _entries 字典 {文件路径: (model_id, 向量)}
    FAISS 索引: 每次 _entries 变更后从字典重建，纯粹是搜索用的缓存。
    """

    def __init__(self, index_dir: str, dim: int = 64):
        self._lock = threading.Lock()
        self._dim = dim
        self._index_dir = index_dir
        self._index: faiss.IndexFlatL2 = faiss.IndexFlatL2(dim)
        # 有序列表，和 FAISS 内部向量顺序一一对应
        self._ordered_keys: List[str] = []
        # 文件路径 -> (model_id, 64维向量)
        self._entries: Dict[str, Tuple[int, np.ndarray]] = {}
        self._data_path = os.path.join(index_dir, "vectors.npy")

    def load(self) -> None:
        os.makedirs(self._index_dir, exist_ok=True)
        with self._lock:
            if os.path.exists(self._data_path):
                data = np.load(self._data_path, allow_pickle=True).item()
                self._entries = data.get("entries", {})
                self._rebuild()
                logger.info("FAISS index loaded: %d vectors", self._index.ntotal)
            else:
                logger.info("Created new FAISS index (dim=%d)", self._dim)

    def save(self) -> None:
        with self._lock:
            self._persist()

    def add_or_update(self, file_path: str, model_id: int, vector: np.ndarray) -> None:
        """同一文件只保留一条向量，已存在则覆盖。key 直接使用传入的 file_path 参数。"""
        key = file_path
        vec = np.ascontiguousarray(vector.reshape(self._dim).astype(np.float32))
        with self._lock:
            is_update = key in self._entries
            self._entries[key] = (model_id, vec)
            self._rebuild()
            self._persist()

            if is_update:
                logger.info("Updated FAISS: file=%s, model_id=%d", file_path, model_id)
            else:
                logger.info("Added model %d to FAISS (file=%s)", model_id, file_path)

    def search(self, query_vector: np.ndarray, top_k: int = 5) -> List[Tuple[int, float]]:
        query = np.ascontiguousarray(query_vector.reshape(1, self._dim).astype(np.float32))
        with self._lock:
            if self._index.ntotal == 0:
                return []
            k = min(top_k, self._index.ntotal)
            distances, indices = self._index.search(query, k)

        results = []
        for dist, idx in zip(distances[0], indices[0]):
            key = self._ordered_keys[int(idx)]
            model_id = self._entries[key][0]
            results.append((model_id, float(dist)))
        return results

    def vector_count(self) -> int:
        return self._index.ntotal

    def has_file(self, file_path: str) -> bool:
        return file_path in self._entries

    def _rebuild(self) -> None:
        """从 _entries 字典重建 FAISS 索引。"""
        self._index = faiss.IndexFlatL2(self._dim)
        self._ordered_keys = list(self._entries.keys())
        if not self._ordered_keys:
            return
        vectors = np.array([vec for _, vec in self._entries.values()], dtype=np.float32)
        self._index.add(vectors)

    def _persist(self) -> None:
        os.makedirs(self._index_dir, exist_ok=True)
        np.save(self._data_path, {"entries": self._entries})
