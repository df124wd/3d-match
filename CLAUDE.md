# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

3D Model Similarity Retrieval System (3D模型相似度检索系统) — an industrial tool for matching STL files (mold/injection-molding components) using 64-dimensional geometric features and FAISS similarity search.

## Commands

### Install dependencies
```bash
pip install open3d numpy scipy faiss-cpu tqdm scikit-learn trimesh
```

### Run the main application (interactive CLI)
```bash
python main.py
```
Menu options: (1) build FAISS index from `./stl/` directory, (2) match a query STL against the index, (3) exit.

### Run STL part decomposition
```bash
python TrimeshPart.py
```
Decomposes `./input.stl` into connected components, saves parts to `./stl_parts/`.

### Run FAISS demo
```bash
python test.py
```

## Architecture

### Data pipeline (main.py)
```
STL file → Open3D mesh → uniform point cloud (15k points) → 64D feature vector → FAISS L2 index
```

1. **stl_to_uniform_point_cloud()** — Reads STL via Open3D, centers/normalizes the mesh, samples using Poisson disk (falls back to uniform random), pads to `SAMPLE_POINTS` if needed.
2. **compute_esf_feature()** — Extracts a 64D feature vector from point cloud: axis statistics (21d), center distances (8d), covariance/spatial (8d), kNN distances (10d), zero-padded to 64. L2-normalized.
3. **build_faiss_index()** — Batch-processes all `.stl` files in `./stl/`, stores features in `faiss.IndexFlatL2` (brute-force), saves index + filename mapping to `./faiss_index/`.
4. **match_similar_models()** — Loads index, extracts features from query STL, returns top-K matches by L2 distance.

### STL decomposition (TrimeshPart.py)
- **decompose_by_connectivity_legacy()** — Clusters triangles by connected components using `mesh.cluster_connected_triangles()`, rebuilds sub-meshes manually (avoids `select_by_index` for Open3D version compatibility).
- **decompose_by_normal_features()** — Falls back to K-Means clustering on triangle normals via scikit-learn.
- Both methods filter parts below `MIN_FACES_PER_PART` (50 faces).

### Key directories
| Directory | Purpose |
|-----------|---------|
| `./stl/` | Reference STL library (indexed for matching) |
| `./pointcloud/` | Generated `.npy` point cloud files |
| `./faiss_index/` | `stl_esf_index.faiss` + `feature_to_file.npy` mapping |
| `./stl_parts/` | Decomposed STL parts output |

### Configurable constants (main.py top)
- `STL_DIR`, `POINTCLOUD_DIR`, `INDEX_DIR` — directory paths
- `SAMPLE_POINTS` (15000) — point cloud sampling density
- `ESF_DIM` (64) — feature vector dimension (fixed)

## Key Design Decisions

- **Open3D multi-version compatibility**: Code avoids newer APIs (e.g., `mesh.center()`, `select_by_index`) and uses only universally supported methods. Mesh sub-extraction is done by manually rebuilding vertices/triangles.
- **FAISS IndexFlatL2**: Brute-force search chosen for accuracy on small datasets. No quantization or partitioning.
- **Feature vector is custom geometric stats** (not a true ESF descriptor despite naming): axis stats, distance stats, covariance, kNN distances — padded/trimmed to 64 dimensions.
- **Chinese-language UI**: User-facing strings are in Chinese. Maintain this convention.
