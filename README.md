# 3D 模型相似度检索系统

工业级 3D 模型（模具/注塑件）相似度检索微服务。通过提取 STL/STP 文件的 64 维几何特征向量，结合 FAISS 向量搜索引擎，实现毫秒级的 3D 模型匹配。

## 功能特性

- **模型入库** — 上传 STL/STP/STEP 文件，自动提取点云和特征向量，支持批量上传
- **相似度匹配** — 上传查询文件，秒级返回最相似的 Top-K 模型列表
- **点云查询** — 按 model_id 查询点云信息和入库状态
- **OSS 存储** — 支持阿里云 OSS 文件存储（可选，未配置则使用本地存储）
- **STP 转换** — 自动将 STP/STEP 文件转换为 STL 进行处理

## 技术栈

| 组件 | 技术 |
|------|------|
| Web 框架 | FastAPI + Uvicorn |
| 数据库 | MySQL (SQLAlchemy ORM + PyMySQL) |
| 向量检索 | FAISS IndexFlatL2 |
| 3D 处理 | Open3D (点云采样) + pythonOCC (STP 转换) |
| 对象存储 | 阿里云 OSS v2 (可选) |
| 日志 | Loguru (终端彩色 + 文件轮转) |

## 项目结构

```
3dmatch/
├── api/                          # FastAPI REST API 服务
│   ├── app.py                    # 应用工厂 + 日志配置 + 生命周期管理
│   ├── config.py                 # 配置管理 (pydantic-settings)
│   ├── db/
│   │   └── session.py            # 数据库连接 (SQLAlchemy engine)
│   ├── models/
│   │   └── database.py           # ORM 模型 (映射 Java 端已有表)
│   ├── routers/
│   │   ├── health.py             # GET  /api/v1/health
│   │   ├── ingestion.py          # POST /api/v1/models/ingest (批量上传)
│   │   ├── query.py              # GET  /api/v1/models/{id}/pointcloud
│   │   └── matching.py           # POST /api/v1/models/match
│   ├── schemas/
│   │   └── responses.py          # 响应体模型
│   └── services/
│       ├── feature_extraction.py # 核心算法: 点云采样 + 64维特征提取
│       ├── faiss_manager.py      # FAISS 索引管理 (线程安全单例)
│       ├── oss_service.py        # 阿里云 OSS 上传/删除
│       └── stp_converter.py      # STP/STEP → STL 转换
├── main.py                       # CLI 交互工具 (独立于 API 服务)
├── TrimeshPart.py                # STL 连通体分解工具
├── docs/
│   └── API开发文档.md             # 完整接口文档 (含 Java 调用示例)
├── requirements.txt
├── .env.example                  # 环境变量模板
└── CLAUDE.md                     # AI 开发辅助文档
```

## 快速开始

### 1. 环境准备

```bash
# 克隆项目
git clone https://github.com/df124wd/3d-match.git
cd 3d-match/3dmatch

# 创建虚拟环境
python -m venv venv

# 激活虚拟环境
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置

复制环境变量模板并填写实际配置：

```bash
cp .env.example .env
```

编辑 `.env` 文件：

```ini
# 服务配置
APP_HOST=0.0.0.0
APP_PORT=8001
APP_DEBUG=false

# MySQL (与 Java 平台共用同一数据库)
APP_MYSQL_HOST=192.168.1.201
APP_MYSQL_PORT=3306
APP_MYSQL_USER=root
APP_MYSQL_PASSWORD=your_password
APP_MYSQL_DATABASE=dpydp

# OSS (可选，留空则使用本地存储)
APP_OSS_ENDPOINT=cn-hangzhou
APP_OSS_BUCKET_NAME=your_bucket_name
APP_OSS_ACCESS_KEY_ID=your_key_id
APP_OSS_ACCESS_KEY_SECRET=your_key_secret
```

### 3. 启动服务

```bash
# 激活虚拟环境后
uvicorn api.app:app --host 0.0.0.0 --port 8001 --reload
```

启动成功后会看到：

```
FAISS index loaded: X vectors
OSS configured: bucket=xxx, region=xxx   (或 OSS not configured)
Service started. MySQL=xxx DB=xxx FAISS vectors=X OSS=enabled
```

### 4. 验证

```bash
# 健康检查
curl http://localhost:8001/api/v1/health

# API 文档 (Swagger UI)
# 浏览器打开 http://localhost:8001/docs
```

## API 接口

### 入库接口 (支持批量)

```bash
# 单文件入库
curl -X POST http://localhost:8001/api/v1/models/ingest \
  -F "files=@./stl/model.stl" \
  -F "creator=admin" \
  -F "description=前门外板"

# 多文件批量入库
curl -X POST http://localhost:8001/api/v1/models/ingest \
  -F "files=@./stl/model_A.stl" \
  -F "files=@./stl/model_B.stl" \
  -F "creator=admin"
```

### 匹配接口

```bash
curl -X POST http://localhost:8001/api/v1/models/match \
  -F "file=@./stl/query.stl" \
  -F "top_k=5"
```

### 查询接口

```bash
curl http://localhost:8001/api/v1/models/1/pointcloud
```

### 健康检查

```bash
curl http://localhost:8001/api/v1/health
```

完整接口文档参见 [docs/API开发文档.md](docs/API开发文档.md)，包含请求/响应参数说明和 Java 端调用示例。

## 数据库表

本服务与 Java (芋道) 平台共用同一 MySQL 数据库，直接读写已有表：

| 表名 | 用途 | 读写 |
|------|------|------|
| `kb_model_3d` | 3D 模型基础信息 | 读/写 |
| `kb_model_3d_point_cloud` | 点云信息和入库状态 | 读/写 |
| `kb_programming_project_file` | 项目文件（含 OSS URL） | 读/写 |
| `kb_project_mold` | 模具项目信息 | 只读 |

## 核心算法

```
STL/STP 文件
    ↓ Open3D 读取网格
    ↓ 居中 + 归一化
    ↓ Poisson Disk 采样 15000 个点
    ↓
64 维特征向量
    ├─ 轴统计 (21d): 三轴的 mean/std/max/min/分位数
    ├─ 中心距离统计 (8d): mean/std/max/min/分位数/中位数
    ├─ 协方差/空间 (8d): 协方差矩阵元素 + 偏度 + IQR
    ├─ kNN 距离统计 (10d): k=10 近邻距离的统计量
    └─ 零填充 (17d): 补齐至 64 维
    ↓ L2 归一化
    ↓
FAISS IndexFlatL2 暴力搜索
```

## FAISS 索引机制

- **数据源**: Python 字典 `{文件标识: (model_id, 64维向量)}`
- **索引重建**: 每次新增/更新向量后，从字典重建 FAISS IndexFlatL2
- **去重策略**: 以 `creator_文件名` 为 key，相同 key 覆盖旧向量
- **持久化**: 字典序列化为 `faiss_index/vectors.npy`，服务重启自动加载

## OSS 配置说明

OSS 是可选功能，不影响核心入库和匹配流程：

- **已配置 OSS**: 文件同时保存到本地和 OSS，`physical_path` 存 OSS URL
- **未配置 OSS**: 文件仅保存到本地 `uploads/` 目录，`physical_path` 存本地路径
- **OSS 上传失败**: 自动降级为本地存储，不影响入库成功

OSS object key 格式: `uploads/3d/{creator}/{yyyy}/{MM}/{dd}/{uuid}{suffix}`

## STP 文件转换

STP/STEP 文件需要先转换为 STL 才能进行点云采样：

1. **优先 pythonOCC** — 精度高，需安装 `pythonocc-core`（推荐通过 conda）
2. **降级 FreeCAD** — 通过 `freecadcmd` 命令行转换，作为备选方案

如果环境没有安装转换工具，仅支持 STL 格式文件。

## 日志

- **终端**: 彩色格式，包含时间戳、级别、模块名、函数名、行号
- **文件**: `logs/app.log`，每日午夜轮转，保留 30 天
- **请求日志**: 自动记录每个 HTTP 请求的方法、路径、状态码、耗时

## CLI 工具

项目保留了一个独立的命令行工具，不依赖 API 服务：

```bash
python main.py
# (1) 从 ./stl/ 目录构建 FAISS 索引
# (2) 用一个 STL 文件做相似度匹配
# (3) 退出
```

## 常见问题

**Q: 启动报 `ModuleNotFoundError`?**
A: 确认已激活虚拟环境 (`venv/Scripts/activate`) 并安装了依赖 (`pip install -r requirements.txt`)。

**Q: 启动报端口被占用?**
A: 检查并关闭旧进程: `netstat -ano | grep 8001`，然后 `taskkill /F /PID <pid>`。

**Q: STP 文件入库失败?**
A: 需要安装 pythonOCC: `conda install -c conda-forge pythonocc-core`。STL 文件不需要。

**Q: OSS 上传失败但不影响入库?**
A: 是正常行为。OSS 上传失败会自动降级为本地存储，检查 `.env` 中的 OSS 配置是否正确。

**Q: 同一文件重复入库会怎样?**
A: FAISS 中只保留最新向量（按 `creator_文件名` 去重），数据库每次会新建记录。

## 与 Java 平台集成

本服务作为独立微服务部署，Java 平台通过 HTTP 调用：

1. Java 上传 3D 文件到 Python 入库接口 → 获得 `model_id` 和 `oss_url`
2. Java 保存 `model_id` 到业务表
3. 用户发起匹配时，Java 上传查询文件到 Python 匹配接口 → 获得相似模型列表

详细的 Java 调用示例和注意事项参见 [docs/API开发文档.md](docs/API开发文档.md)。
