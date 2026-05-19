import open3d as o3d
import numpy as np
import os

# ===================== 全局配置 =====================
INPUT_STL_PATH = "./input.stl"  # 待分解的STL文件路径
OUTPUT_DIR = "./stl_parts"  # 分解后部件的保存目录
MIN_FACES_PER_PART = 50  # 最小部件面片数（过滤噪声）

# 自动创建输出目录
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

# 初始化全局变量
connectivity_parts = []


# ===================== 核心工具函数 =====================
def load_and_preprocess_stl(stl_path):
    """加载STL模型并预处理（仅用基础API）"""
    # 1. 加载STL网格
    mesh = o3d.io.read_triangle_mesh(stl_path)
    if not mesh.has_triangles():
        raise ValueError("无效的STL文件（非三角网格）")

    # 2. 预处理：仅用全版本支持的方法
    mesh.remove_duplicated_vertices()
    mesh.remove_degenerate_triangles()
    mesh.remove_unreferenced_vertices()
    mesh.compute_vertex_normals()
    mesh.compute_triangle_normals()
    return mesh


def decompose_by_connectivity_legacy(mesh):
    """连通性分解（旧版Open3D终极兼容版）"""
    global connectivity_parts
    connectivity_parts = []

    # 提取连通域ID
    cluster_result = mesh.cluster_connected_triangles()
    if isinstance(cluster_result, tuple):
        component_ids = np.array(cluster_result[0])
    else:
        component_ids = np.array(cluster_result)

    # 获取唯一连通域ID
    unique_component_ids = np.unique(component_ids)
    print(f"🔍 检测到 {len(unique_component_ids)} 个连通域")

    # 遍历每个连通域
    for comp_id in unique_component_ids:
        triangle_indices = np.where(component_ids == comp_id)[0]
        if len(triangle_indices) < MIN_FACES_PER_PART:
            print(f"⚠️  跳过过小部件（ID:{comp_id}）：仅{len(triangle_indices)}个三角面")
            continue

        # 手动构建子网格（完全不依赖select_by_index）
        try:
            vertices = np.asarray(mesh.vertices)
            triangles = np.asarray(mesh.triangles)
            part_triangles = triangles[triangle_indices]

            # 去重顶点并重新映射索引
            unique_vertices = np.unique(part_triangles.flatten())
            vertex_map = {v: i for i, v in enumerate(unique_vertices)}
            new_triangles = []
            for tri in part_triangles:
                new_tri = [vertex_map[v] for v in tri]
                new_triangles.append(new_tri)

            # 构建新网格
            part_mesh = o3d.geometry.TriangleMesh()
            part_mesh.vertices = o3d.utility.Vector3dVector(vertices[unique_vertices])
            part_mesh.triangles = o3d.utility.Vector3iVector(new_triangles)
            part_mesh.compute_vertex_normals()  # 确保法向量完整

            if len(part_mesh.triangles) > 0:
                connectivity_parts.append((f"connected_part_{comp_id}", part_mesh))
                print(f"✅ 提取部件（ID:{comp_id}）：三角面数={len(part_mesh.triangles)}")
        except Exception as e:
            print(f"⚠️  构建部件（ID:{comp_id}）失败：{str(e)}")
            continue

    return connectivity_parts


def decompose_by_normal_features(mesh, num_clusters=3):
    """法向量特征分解（旧版兼容）"""
    global connectivity_parts
    connectivity_parts = []

    # 提取三角面法向量
    triangle_normals = np.asarray(mesh.triangle_normals)
    triangle_normals = triangle_normals / np.linalg.norm(triangle_normals, axis=1, keepdims=True)
    triangle_normals = triangle_normals[~np.isnan(triangle_normals).any(axis=1)]

    if len(triangle_normals) == 0:
        print("⚠️  无有效法向量数据，特征分解失败")
        return []

    # K-Means聚类
    try:
        from sklearn.cluster import KMeans
        kmeans = KMeans(n_clusters=num_clusters, random_state=42)
        cluster_labels = kmeans.fit_predict(triangle_normals)
    except ImportError:
        print("❌ 缺少scikit-learn，请执行：pip install scikit-learn")
        return []

    # 提取聚类部件
    unique_labels = np.unique(cluster_labels)
    for label in unique_labels:
        triangle_indices = np.where(cluster_labels == label)[0]
        if len(triangle_indices) < MIN_FACES_PER_PART:
            continue

        # 手动构建子网格
        try:
            vertices = np.asarray(mesh.vertices)
            triangles = np.asarray(mesh.triangles)
            part_triangles = triangles[triangle_indices]

            unique_vertices = np.unique(part_triangles.flatten())
            vertex_map = {v: i for i, v in enumerate(unique_vertices)}
            new_triangles = [[vertex_map[v] for v in tri] for tri in part_triangles]

            part_mesh = o3d.geometry.TriangleMesh()
            part_mesh.vertices = o3d.utility.Vector3dVector(vertices[unique_vertices])
            part_mesh.triangles = o3d.utility.Vector3iVector(new_triangles)
            part_mesh.compute_vertex_normals()

            if len(part_mesh.triangles) > 0:
                connectivity_parts.append((f"normal_feature_part_{label}", part_mesh))
        except Exception as e:
            print(f"⚠️  构建特征部件（ID:{label}）失败：{str(e)}")
            continue

    return connectivity_parts


def save_parts(parts):
    """保存部件（移除ASCII参数，仅导出二进制STL）"""
    if not parts:
        print("⚠️  无有效部件可保存")
        return

    saved_count = 0
    for idx, (part_name, part_mesh) in enumerate(parts):
        if len(part_mesh.triangles) < MIN_FACES_PER_PART:
            continue

        # 关键修复：移除write_ascii参数，使用默认二进制格式（旧版支持）
        save_path = os.path.join(OUTPUT_DIR, f"{part_name}_{idx}.stl")
        try:
            # 仅保留必要参数，兼容所有版本
            o3d.io.write_triangle_mesh(save_path, part_mesh)
            print(f"✅ 保存部件：{save_path}（三角面数：{len(part_mesh.triangles)}）")
            saved_count += 1
        except Exception as e:
            print(f"❌ 保存部件失败 {save_path}：{str(e)}")
            continue

    print(f"📊 共保存 {saved_count} 个有效部件（过滤{len(parts) - saved_count}个小部件）")


def visualize_parts(parts):
    """可视化（无第三方依赖）"""
    if not parts:
        print("⚠️  无部件可可视化")
        return

    try:
        vis_meshes = []
        # 基础颜色列表
        colors = [[1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 1, 0], [1, 0, 1], [0, 1, 1]]
        for idx, (_, part_mesh) in enumerate(parts):
            part_mesh.paint_uniform_color(colors[idx % len(colors)])
            vis_meshes.append(part_mesh)
        o3d.visualization.draw_geometries(vis_meshes, window_name="分解后的几何部件")
    except Exception as e:
        print(f"⚠️  可视化失败：{str(e)}")


# ===================== 主程序 =====================
if __name__ == "__main__":
    # 1. 加载模型
    print("===== 加载并预处理STL模型 =====")
    try:
        mesh = load_and_preprocess_stl(INPUT_STL_PATH)
        print(f"✅ 模型加载成功：顶点数={len(mesh.vertices)}，三角面数={len(mesh.triangles)}")
    except Exception as e:
        print(f"❌ 模型加载失败：{str(e)}")
        exit(1)

    # 2. 连通性分解
    print("\n===== 策略1：基于连通性分解 =====")
    try:
        connectivity_parts = decompose_by_connectivity_legacy(mesh)
        save_parts(connectivity_parts)
    except Exception as e:
        print(f"❌ 连通性分解失败：{str(e)}")
        # 降级到法向量特征分解
        print("\n🔄 尝试降级到法向量特征分解...")
        try:
            connectivity_parts = decompose_by_normal_features(mesh, num_clusters=3)
            save_parts(connectivity_parts)
        except Exception as e2:
            print(f"❌ 特征分解也失败：{str(e2)}")

    # 3. 可视化
    print("\n===== 可视化结果 =====")
    visualize_parts(connectivity_parts)

    print(f"\n📌 处理完成！部件保存目录：{OUTPUT_DIR}")