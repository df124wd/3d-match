import os
import numpy as np
import open3d as o3d
import faiss
from tqdm import tqdm
import sys

# ===================== 全局配置（可根据需求调整） =====================
# 目录配置
STL_DIR = "./stl"  # 原始STL文件目录
POINTCLOUD_DIR = "./pointcloud"  # 点云保存目录
INDEX_DIR = "./faiss_index"  # FAISS索引保存目录
# 采样与特征参数
SAMPLE_POINTS = 15000  # 均匀采样点数量
ESF_DIM = 64  # ESF特征维度（固定64维）
# FAISS索引文件路径
INDEX_FILE = os.path.join(INDEX_DIR, "stl_esf_index.faiss")
FEATURE_MAP_FILE = os.path.join(INDEX_DIR, "feature_to_file.npy")

# 自动创建所需目录
for dir in [STL_DIR, POINTCLOUD_DIR, INDEX_DIR]:
    if not os.path.exists(dir):
        os.makedirs(dir)


# ===================== 工具函数：适配GUI/命令行输入 =====================
def get_input_file_path():
    """
    优先使用tkinter弹窗输入，缺失则降级为命令行输入
    返回：用户输入的文件路径
    """
    try:
        import tkinter as tk
        from tkinter import simpledialog
        root = tk.Tk()
        root.withdraw()  # 隐藏主窗口
        root.attributes('-topmost', True)  # 弹窗置顶
        file_path = simpledialog.askstring(
            title="输入文件路径",
            prompt="请输入待匹配的STL文件完整路径：\n（示例：C:\\stl\\test.stl）"
        )
        root.destroy()
    except ImportError:
        # tkinter缺失，使用命令行输入
        print("\n=== 请输入待匹配的STL文件信息 ===")
        file_path = input("文件完整路径：").strip()
    return file_path if (file_path and file_path.strip()) else None


# ===================== 核心功能1：STL转均匀点云（全版本兼容） =====================
def stl_to_uniform_point_cloud(stl_path, save_pc=True):
    """
    读取STL文件，生成均匀分布的点云数据（兼容所有Open3D版本）
    :param stl_path: STL文件路径
    :param save_pc: 是否保存点云到pointcloud目录
    :return: (N,3) 点云数组（float32）
    """
    # 1. 读取STL模型并验证
    if not os.path.exists(stl_path):
        raise FileNotFoundError(f"STL文件不存在：{stl_path}")
    mesh = o3d.io.read_triangle_mesh(stl_path)
    if not mesh.has_triangles() or len(mesh.triangles) == 0:
        raise ValueError(f"无效的STL文件（非三角网格）：{stl_path}")

    # 2. 模型预处理（低版本兼容写法）
    # 移除重复顶点和退化三角面（全版本支持）
    mesh.remove_duplicated_vertices()
    mesh.remove_degenerate_triangles()

    # 模型居中（替代mesh.center()，兼容低版本）
    center = mesh.get_center()  # 全版本支持
    mesh.vertices = o3d.utility.Vector3dVector(
        np.asarray(mesh.vertices) - center
    )

    # 归一化尺度（消除模型大小影响，全版本支持）
    max_bound = mesh.get_max_bound()
    min_bound = mesh.get_min_bound()
    max_extent = np.max(max_bound - min_bound)
    if max_extent > 0:
        mesh.vertices = o3d.utility.Vector3dVector(
            np.asarray(mesh.vertices) / max_extent
        )

    # 3. 校验采样点数（避免超过模型承载能力）
    triangle_count = len(mesh.triangles)
    max_possible_points = min(SAMPLE_POINTS, triangle_count * 10)  # 三角面数*10为安全上限
    if max_possible_points < 100:
        raise ValueError(f"模型三角面过少（{triangle_count}个），无法采样{max_possible_points}个点")

    # 4. 均匀采样（优先泊松，失败则降级为随机，全版本兼容）
    try:
        # 泊松圆盘采样（无seed，全版本支持）
        pcd = mesh.sample_points_poisson_disk(
            number_of_points=max_possible_points,
            init_factor=5
        )
    except:
        # 降级为均匀随机采样（兜底，全版本支持）
        pcd = mesh.sample_points_uniformly(number_of_points=max_possible_points)

    point_cloud = np.asarray(pcd.points, dtype=np.float32)

    # 5. 确保采样点数达标（不足则补点，不影响特征）
    if len(point_cloud) < SAMPLE_POINTS:
        # 补充微小噪声点，避免特征偏差
        pad_points = np.random.randn(SAMPLE_POINTS - len(point_cloud), 3).astype(np.float32) * 1e-6
        point_cloud = np.vstack([point_cloud, pad_points])

    # 6. 截断到目标点数
    point_cloud = point_cloud[:SAMPLE_POINTS]

    # 7. 保存点云数据
    if save_pc:
        file_name = os.path.splitext(os.path.basename(stl_path))[0]
        pc_save_path = os.path.join(POINTCLOUD_DIR, f"{file_name}_pointcloud.npy")
        np.save(pc_save_path, point_cloud)
        print(f"点云已保存：{pc_save_path}")

    return point_cloud


# ===================== 核心功能2：提取64维ESF特征（无改动） =====================
def compute_esf_feature(point_cloud):
    """
    提取64维ESF（Ensemble of Shape Functions）特征向量并归一化
    :param point_cloud: (N,3) 点云数组
    :return: (1,64) 归一化后的ESF特征向量
    """
    # 1. 基础预处理
    point_cloud = point_cloud.astype(np.float32)
    num_points = len(point_cloud)
    if num_points < 100:  # 点云数量过少，特征无意义
        raise ValueError(f"点云数量过少（{num_points}），无法提取特征")

    # 2. 计算核心几何特征（构造64维向量）
    feats = []

    # 2.1 全局统计特征（18维）：XYZ三轴的均值、标准差、最大/最小、四分位数、中位数
    for axis in range(3):
        axis_data = point_cloud[:, axis]
        feats.extend([
            np.mean(axis_data), np.std(axis_data),
            np.max(axis_data), np.min(axis_data),
            np.percentile(axis_data, 25), np.percentile(axis_data, 50),  # 中位数
            np.percentile(axis_data, 75)
        ])

    # 2.2 中心距离特征（8维）：到中心点的距离统计
    center = np.mean(point_cloud, axis=0)
    distances = np.linalg.norm(point_cloud - center, axis=1)
    feats.extend([
        np.mean(distances), np.std(distances),
        np.max(distances), np.min(distances),
        np.percentile(distances, 25), np.percentile(distances, 50),
        np.percentile(distances, 75), np.median(distances)
    ])

    # 2.3 空间分布特征（16维）：XYZ三轴的方差、协方差、偏度、峰度
    cov_mat = np.cov(point_cloud.T)
    feats.extend([
        cov_mat[0, 0], cov_mat[1, 1], cov_mat[2, 2],  # 方差
        cov_mat[0, 1], cov_mat[0, 2], cov_mat[1, 2],  # 协方差
        np.mean(np.abs(point_cloud - center) ** 3) / (np.std(point_cloud) ** 3 + 1e-8),  # 偏度
        np.percentile(point_cloud, 90) - np.percentile(point_cloud, 10)  # 峰度替代
    ])

    # 2.4 形状分布特征（22维）：填充至64维
    # 近邻点距离统计（10维）
    k = min(10, num_points - 1)
    dist_matrix = np.sqrt(((point_cloud[:, None] - point_cloud[None, :]) ** 2).sum(-1))
    knn_dists = np.sort(dist_matrix, axis=1)[:, 1:k + 1]  # 排除自身
    feats.extend([
        np.mean(knn_dists), np.std(knn_dists),
        np.max(knn_dists), np.min(knn_dists),
        np.percentile(knn_dists, 25), np.percentile(knn_dists, 50),
        np.percentile(knn_dists, 75), np.median(knn_dists),
        np.sum(knn_dists) / num_points, np.var(knn_dists)
    ])

    # 2.5 填充至64维（保证维度固定）
    feats = np.array(feats, dtype=np.float32)
    if len(feats) < ESF_DIM:
        feats = np.pad(feats, (0, ESF_DIM - len(feats)), mode='constant')
    elif len(feats) > ESF_DIM:
        feats = feats[:ESF_DIM]

    # 3. L2归一化（提升相似度计算准确性）
    feats = feats.reshape(1, -1)
    norm = np.linalg.norm(feats, axis=1, keepdims=True)
    norm[norm == 0] = 1e-8  # 避免除零错误
    normalized_feats = feats / norm

    return normalized_feats


# ===================== 核心功能3：构建FAISS L2索引（无改动） =====================
def build_faiss_index():
    """
    批量处理STL文件，提取特征并构建FAISS L2距离索引
    """
    # 1. 遍历STL文件
    stl_files = [f for f in os.listdir(STL_DIR) if f.lower().endswith(".stl")]
    if not stl_files:
        print(f"⚠️  {STL_DIR}目录下未找到STL文件，索引构建终止")
        return

    # 2. 逐个处理文件
    all_features = []
    file_mapping = []  # 特征索引 -> 文件名映射
    print(f"\n=== 开始处理 {len(stl_files)} 个STL文件 ===")

    for file_name in tqdm(stl_files, desc="处理进度"):
        try:
            stl_path = os.path.join(STL_DIR, file_name)
            # 生成点云（使用全版本兼容的函数）
            point_cloud = stl_to_uniform_point_cloud(stl_path)
            # 提取ESF特征
            feature = compute_esf_feature(point_cloud)
            # 收集特征和文件名
            all_features.append(feature)
            file_mapping.append(file_name)
        except Exception as e:
            print(f"\n❌ 处理文件 {file_name} 失败：{str(e)}")
            continue

    # 3. 构建FAISS索引
    if not all_features:
        print("⚠️  无有效特征数据，索引构建失败")
        return

    # 合并特征矩阵
    feature_matrix = np.vstack(all_features).astype(np.float32)
    # 创建L2距离索引（暴力检索，小数据集精度最高）
    index = faiss.IndexFlatL2(ESF_DIM)
    index.add(feature_matrix)

    # 4. 保存索引和映射关系
    faiss.write_index(index, INDEX_FILE)
    np.save(FEATURE_MAP_FILE, np.array(file_mapping))

    print(f"\n✅ 索引构建完成！")
    print(f"   - 索引文件：{INDEX_FILE}")
    print(f"   - 映射文件：{FEATURE_MAP_FILE}")
    print(f"   - 入库模型数量：{index.ntotal}")


# ===================== 核心功能4：模型相似度匹配（无改动） =====================
def match_similar_models(query_stl_path, top_k=5):
    """
    输入新STL文件，与索引库中的模型进行相似度匹配
    :param query_stl_path: 待匹配的STL文件路径
    :param top_k: 返回前K个最相似的模型
    :return: 匹配结果列表 [(排名, 文件名, L2距离), ...]
    """
    # 1. 加载FAISS索引
    if not os.path.exists(INDEX_FILE) or not os.path.exists(FEATURE_MAP_FILE):
        raise FileNotFoundError("FAISS索引未构建，请先执行批量处理！")

    index = faiss.read_index(INDEX_FILE)
    file_mapping = np.load(FEATURE_MAP_FILE)

    # 2. 处理查询文件
    print(f"\n=== 处理查询文件：{os.path.basename(query_stl_path)} ===")
    query_point_cloud = stl_to_uniform_point_cloud(query_stl_path, save_pc=False)
    query_feature = compute_esf_feature(query_point_cloud)

    # 3. 相似度检索（L2距离越小，相似度越高）
    top_k = min(top_k, index.ntotal)
    distances, indices = index.search(query_feature, top_k)

    # 4. 整理结果
    results = []
    print(f"\n=== 相似度匹配结果（Top-{top_k}）===")
    print(f"{'排名':<5} {'文件名':<30} {'L2距离':<10} {'相似度（归一化）':<15}")
    print("-" * 60)

    max_dist = np.max(distances) if np.max(distances) > 0 else 1e-8
    for i, (dist, idx) in enumerate(zip(distances[0], indices[0])):
        file_name = file_mapping[idx]
        # 归一化相似度（0-1，1为完全匹配）
        similarity = 1 - (dist / max_dist)
        results.append((i + 1, file_name, round(float(dist), 6), round(similarity, 4)))
        print(f"{i + 1:<5} {file_name:<30} {dist:<10.6f} {similarity:<15.4f}")

    return results


# ===================== 主程序入口（无改动） =====================
def main():
    print("=" * 60)
    print("3D模型相似度检索系统 V1.0（全版本兼容）")
    print("=" * 60)

    while True:
        print("\n请选择操作：")
        print("1. 批量处理STL文件，构建FAISS索引")
        print("2. 输入新文件，进行模型相似度匹配")
        print("3. 退出程序")

        choice = input("\n请输入选项（1/2/3）：").strip()

        if choice == "1":
            build_faiss_index()
        elif choice == "2":
            # 获取输入文件路径
            query_path = get_input_file_path()
            if not query_path:
                print("❌ 未输入有效路径，请重新操作")
                continue
            # 验证文件有效性
            if not os.path.exists(query_path):
                print(f"❌ 文件不存在：{query_path}")
                continue
            if not query_path.lower().endswith(".stl"):
                print("❌ 非STL格式文件，请重新输入")
                continue
            # 执行匹配
            try:
                match_similar_models(query_path, top_k=5)
            except Exception as e:
                print(f"❌ 匹配失败：{str(e)}")
        elif choice == "3":
            print("\n👋 程序已退出，感谢使用！")
            sys.exit(0)
        else:
            print("❌ 无效选项，请输入 1/2/3")


if __name__ == "__main__":
    # 安装依赖提示（首次运行可执行）
    print("📌 若缺少依赖，请执行：pip install open3d faiss-cpu numpy tqdm")
    main()