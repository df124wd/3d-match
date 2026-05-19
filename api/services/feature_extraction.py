import os
import logging
from dataclasses import dataclass

import numpy as np
import open3d as o3d

logger = logging.getLogger(__name__)

SAMPLE_POINTS = 15000


@dataclass
class ExtractionResult:
    point_cloud: np.ndarray
    feature_vector: np.ndarray
    npy_file_path: str
    pcd_file_path: str
    pc_point_count: int
    sampling_method: str
    pc_file_size_bytes: int


def stl_to_uniform_point_cloud(stl_path: str, sample_points: int = SAMPLE_POINTS) -> np.ndarray:
    if not os.path.exists(stl_path):
        raise FileNotFoundError(f"STL file not found: {stl_path}")

    mesh = o3d.io.read_triangle_mesh(stl_path)
    if not mesh.has_triangles() or len(mesh.triangles) == 0:
        raise ValueError(f"Invalid STL file (no triangles): {stl_path}")

    mesh.remove_duplicated_vertices()
    mesh.remove_degenerate_triangles()

    center = mesh.get_center()
    mesh.vertices = o3d.utility.Vector3dVector(np.asarray(mesh.vertices) - center)

    max_bound = mesh.get_max_bound()
    min_bound = mesh.get_min_bound()
    max_extent = np.max(max_bound - min_bound)
    if max_extent > 0:
        mesh.vertices = o3d.utility.Vector3dVector(np.asarray(mesh.vertices) / max_extent)

    triangle_count = len(mesh.triangles)
    max_possible_points = min(sample_points, triangle_count * 10)
    if max_possible_points < 100:
        raise ValueError(f"Model too small ({triangle_count} triangles), cannot sample {max_possible_points} points")

    sampling_method = "poisson_disk"
    try:
        pcd = mesh.sample_points_poisson_disk(number_of_points=max_possible_points, init_factor=5)
    except Exception:
        pcd = mesh.sample_points_uniformly(number_of_points=max_possible_points)
        sampling_method = "uniform_random"

    point_cloud = np.asarray(pcd.points, dtype=np.float32)

    if len(point_cloud) < sample_points:
        pad_points = np.random.randn(sample_points - len(point_cloud), 3).astype(np.float32) * 1e-6
        point_cloud = np.vstack([point_cloud, pad_points])

    point_cloud = point_cloud[:sample_points]
    return point_cloud, sampling_method


def compute_esf_feature(point_cloud: np.ndarray, esf_dim: int = 64) -> np.ndarray:
    point_cloud = point_cloud.astype(np.float32)
    num_points = len(point_cloud)
    if num_points < 100:
        raise ValueError(f"Too few points ({num_points}) for feature extraction")

    feats = []

    # Axis statistics: 3 axes x 7 stats = 21 dims
    for axis in range(3):
        axis_data = point_cloud[:, axis]
        feats.extend([
            np.mean(axis_data), np.std(axis_data),
            np.max(axis_data), np.min(axis_data),
            np.percentile(axis_data, 25), np.percentile(axis_data, 50),
            np.percentile(axis_data, 75),
        ])

    # Center distance statistics: 8 dims
    center = np.mean(point_cloud, axis=0)
    distances = np.linalg.norm(point_cloud - center, axis=1)
    feats.extend([
        np.mean(distances), np.std(distances),
        np.max(distances), np.min(distances),
        np.percentile(distances, 25), np.percentile(distances, 50),
        np.percentile(distances, 75), np.median(distances),
    ])

    # Covariance/spatial: 8 dims
    cov_mat = np.cov(point_cloud.T)
    feats.extend([
        cov_mat[0, 0], cov_mat[1, 1], cov_mat[2, 2],
        cov_mat[0, 1], cov_mat[0, 2], cov_mat[1, 2],
        np.mean(np.abs(point_cloud - center) ** 3) / (np.std(point_cloud) ** 3 + 1e-8),
        np.percentile(point_cloud, 90) - np.percentile(point_cloud, 10),
    ])

    # kNN distance statistics: 10 dims
    k = min(10, num_points - 1)
    from scipy.spatial import cKDTree
    tree = cKDTree(point_cloud)
    dists, _ = tree.query(point_cloud, k=k + 1)
    knn_dists = dists[:, 1:]
    feats.extend([
        np.mean(knn_dists), np.std(knn_dists),
        np.max(knn_dists), np.min(knn_dists),
        np.percentile(knn_dists, 25), np.percentile(knn_dists, 50),
        np.percentile(knn_dists, 75), np.median(knn_dists),
        np.sum(knn_dists) / num_points, np.var(knn_dists),
    ])

    # Pad/trim to fixed dimension
    feats = np.array(feats, dtype=np.float32)
    if len(feats) < esf_dim:
        feats = np.pad(feats, (0, esf_dim - len(feats)), mode='constant')
    elif len(feats) > esf_dim:
        feats = feats[:esf_dim]

    # L2 normalize
    feats = feats.reshape(1, -1)
    norm = np.linalg.norm(feats, axis=1, keepdims=True)
    norm[norm == 0] = 1e-8
    normalized_feats = feats / norm

    return normalized_feats


def process_model(
    file_path: str,
    output_dir: str,
    sample_points: int = SAMPLE_POINTS,
    esf_dim: int = 64,
) -> ExtractionResult:
    """End-to-end: read 3D file -> point cloud + feature vector."""
    os.makedirs(output_dir, exist_ok=True)

    point_cloud, sampling_method = stl_to_uniform_point_cloud(file_path, sample_points)
    feature_vector = compute_esf_feature(point_cloud, esf_dim)

    base_name = os.path.splitext(os.path.basename(file_path))[0]

    # Save .npy for internal use (feature extraction pipeline)
    npy_path = os.path.join(output_dir, f"{base_name}_pointcloud.npy")
    np.save(npy_path, point_cloud)

    # Save .pcd for Java platform consumption
    pcd_path = os.path.join(output_dir, f"{base_name}_pointcloud.pcd")
    _save_as_pcd(point_cloud, pcd_path)

    pc_file_size = os.path.getsize(pcd_path)

    logger.info(
        "Processed %s: %d points, %dD feature, saved .npy + .pcd",
        file_path, len(point_cloud), esf_dim,
    )

    return ExtractionResult(
        point_cloud=point_cloud,
        feature_vector=feature_vector,
        npy_file_path=npy_path,
        pcd_file_path=pcd_path,
        pc_point_count=len(point_cloud),
        sampling_method=sampling_method,
        pc_file_size_bytes=pc_file_size,
    )


def _save_as_pcd(point_cloud: np.ndarray, output_path: str) -> None:
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(point_cloud.astype(np.float64))
    o3d.io.write_point_cloud(output_path, pcd)
