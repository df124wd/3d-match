# 3D模型相似度检索服务 — 接口开发文档

## 服务信息

| 项目 | 说明 |
|------|------|
| 基础地址 | `http://{host}:8001/api/v1` |
| 协议 | HTTP / JSON |
| 字符编码 | UTF-8 |

## 统一响应格式

所有接口返回统一的 JSON 信封：

```json
{
  "code": 0,
  "message": "success",
  "data": { ... }
}
```

### 错误码定义

| 错误码 | 含义 | 说明 |
|--------|------|------|
| 0 | 成功 | |
| 40001 | 资源未找到 | 文件路径不存在、查询的 model_id 无点云记录 |
| 40003 | 格式无效 | 文件不是 STL/STP/STEP 格式 |
| 50001 | 处理失败 | 特征提取、数据库写入等内部错误 |
| 50002 | 索引为空 | FAISS 索引中没有向量，需先入库 |
| 50003 | 格式转换失败 | STP 转 STL 失败 |

---

## 一、入库接口

### 基本信息

```
POST /api/v1/models/ingest
Content-Type: application/json
```

### 处理逻辑

```
1. 校验 file_path 文件存在且格式合法（.stl / .stp / .step）
2. 在 kb_model_3d 表创建记录（model_name = 文件名）
3. 在 kb_programming_project_file 表创建记录（关联文件信息）
4. 如果是 STP/STEP → 临时转换为 STL
5. 读取 3D 文件 → 均匀采样 15000 个点 → 生成点云
6. 从点云中提取 64 维几何特征向量
7. 将特征向量加入 FAISS 索引
8. 生成 .npy 文件（内部用）和 .pcd 文件（存数据库）
9. 在 kb_model_3d_point_cloud 表创建记录
10. 返回新生成的 model_id 和处理结果
```

### 请求参数

| 字段 | 类型 | 必填 | 说明 | 示例值 |
|------|------|------|------|--------|
| file_path | string | 是 | 3D 模型文件在服务器上的绝对路径 | `"/data/models/part_A.stl"` |
| creator | string | 是 | 创建人（用户 ID 或用户名） | `"admin"` |
| description | string | 否 | 点云描述信息 | `"前门外板点云"` |

**请求示例：**

```json
{
  "file_path": "/data/models/part_A.stl",
  "creator": "admin",
  "description": "前门外板点云"
}
```

### 响应参数

| 字段 | 类型 | 说明 |
|------|------|------|
| code | int | 0 表示成功 |
| message | string | 状态描述 |
| data.model_id | int | **新生成的模型 ID**（kb_model_3d 表的主键，Java 端需保存此 ID） |
| data.pointcloud.file_path | string | 生成的 .pcd 文件路径 |
| data.pointcloud.file_format | string | 固定值 `"PCD"` |
| data.pointcloud.point_count | string | 采样点数量，固定 `"15000"` |
| data.pointcloud.sampling_precision | string | 采样方式：`"poisson_disk"` 或 `"uniform_random"` |
| data.pointcloud.file_size | string | .pcd 文件大小，如 `"175.9 KB"` |
| data.pointcloud.description | string | 描述信息 |
| data.vector_db_status | int | 向量库状态：`1` = 已入库 |
| data.vector_db_time | string | 入库时间，ISO 8601 格式 |

**响应示例：**

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "model_id": 2,
    "pointcloud": {
      "file_path": "./pointcloud/part_A_pointcloud.pcd",
      "file_format": "PCD",
      "point_count": "15000",
      "sampling_precision": "poisson_disk",
      "file_size": "175.9 KB",
      "description": "前门外板点云"
    },
    "vector_db_status": 1,
    "vector_db_time": "2026-05-19T11:17:26"
  }
}
```

### curl 示例

```bash
curl -X POST http://localhost:8001/api/v1/models/ingest \
  -H "Content-Type: application/json" \
  -d '{"file_path": "/data/models/part_A.stl", "creator": "admin", "description": "前门外板点云"}'
```

### 数据库变更

入库成功后，Python 会写入以下三张表：

**kb_model_3d（新建记录）：**

| 字段 | 写入内容 |
|------|----------|
| model_name | 文件名（如 `"part_A.stl"`） |
| creator | 请求中的 creator |

**kb_programming_project_file（新建记录）：**

| 字段 | 写入内容 |
|------|----------|
| project_id | 新生成的 kb_model_3d.id |
| file_name | 文件名 |
| file_type | `"FILE"` |
| physical_path | 原始文件路径 |
| file_size | 文件大小（字节） |
| file_ext | 文件扩展名（如 `"stl"`） |
| creator | 请求中的 creator |

**kb_model_3d_point_cloud（新建记录）：**

| 字段 | 写入内容 |
|------|----------|
| model_id | 新生成的 kb_model_3d.id |
| file_path | Python 生成的 .pcd 文件路径 |
| file_format | `"PCD"` |
| point_count | `"15000"` |
| sampling_precision | `"poisson_disk"` 或 `"uniform_random"` |
| file_size | 文件大小字符串，如 `"175.9 KB"` |
| vector_db_status | `1`（已入库） |
| vector_db_time | 入库完成时间 |

---

## 二、查询接口

### 基本信息

```
GET /api/v1/models/{model_id}/pointcloud
```

### 处理逻辑

```
1. 根据 model_id 查询 kb_model_3d_point_cloud 表
2. 返回该模型的点云信息和向量库状态
```

### 请求参数

| 字段 | 类型 | 必填 | 说明 | 示例值 |
|------|------|------|------|--------|
| model_id | int | 是 | URL 路径参数，入库接口返回的模型 ID | `2` |

### 响应参数

| 字段 | 类型 | 说明 |
|------|------|------|
| data.model_id | int | 模型 ID |
| data.pointcloud | object/null | 点云信息，未入库则为 null |
| data.pointcloud.file_path | string | .pcd 文件路径 |
| data.pointcloud.file_format | string | 文件格式，如 `"PCD"` |
| data.pointcloud.point_count | string | 采样点数量 |
| data.pointcloud.sampling_precision | string | 采样方式 |
| data.pointcloud.file_size | string | 文件大小 |
| data.pointcloud.description | string | 描述信息 |
| data.vector_db_status | int | `0` = 未入库，`1` = 已入库 |
| data.vector_db_time | string/null | 入库时间 |

**响应示例（已入库）：**

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "model_id": 2,
    "pointcloud": {
      "file_path": "./pointcloud/part_A_pointcloud.pcd",
      "file_format": "PCD",
      "point_count": "15000",
      "sampling_precision": "poisson_disk",
      "file_size": "175.9 KB",
      "description": "前门外板点云"
    },
    "vector_db_status": 1,
    "vector_db_time": "2026-05-19T11:17:26"
  }
}
```

**响应示例（未找到）：**

```json
{
  "code": 40001,
  "message": "Point cloud for model 99 not found",
  "data": null
}
```

### curl 示例

```bash
curl http://localhost:8001/api/v1/models/2/pointcloud
```

---

## 三、匹配接口

### 基本信息

```
POST /api/v1/models/match
Content-Type: application/json
```

### 处理逻辑

```
1. 校验 file_path 文件存在且格式合法
2. 校验 FAISS 索引非空（至少有一条入库记录）
3. 如果是 STP/STEP → 临时转换为 STL
4. 读取文件 → 采样 15000 个点 → 提取 64 维特征向量
5. 用特征向量在 FAISS 索引中搜索最相似的 top_k 条记录
6. 查询 kb_model_3d + kb_project_mold 表，补充模型名称和项目名称
7. 计算归一化相似度（0~1，越大越相似）
8. 返回匹配结果列表
```

### 请求参数

| 字段 | 类型 | 必填 | 说明 | 示例值 |
|------|------|------|------|--------|
| file_path | string | 是 | 待匹配的 3D 模型文件在服务器上的绝对路径 | `"/data/upload/query_part.stl"` |
| top_k | int | 否 | 返回最相似的前 N 条，默认 5，范围 1~50 | `5` |

**请求示例：**

```json
{
  "file_path": "/data/upload/query_part.stl",
  "top_k": 5
}
```

### 响应参数

| 字段 | 类型 | 说明 |
|------|------|------|
| data.query_filename | string | 查询文件名（仅文件名，不含路径） |
| data.top_k | int | 实际返回数量 |
| data.matches | array | 匹配结果列表，按相似度从高到低排序 |
| data.matches[].rank | int | 排名，从 1 开始 |
| data.matches[].model_id | int | 匹配到的模型 ID（kb_model_3d.id） |
| data.matches[].model_name | string | 模型文件名（如 `"前门外板模型.stp"`） |
| data.matches[].part_name | string | 零件名称，可能为 null |
| data.matches[].project_id | int | 所属项目 ID，可能为 null |
| data.matches[].project_name | string | 所属项目名称，可能为 null |
| data.matches[].distance | float | L2 距离，越小越相似 |
| data.matches[].similarity | float | 归一化相似度，0~1，越大越相似 |

**响应示例：**

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "query_filename": "query_part.stl",
    "top_k": 5,
    "matches": [
      {
        "rank": 1,
        "model_id": 23,
        "model_name": "前门外板模型.stp",
        "part_name": "前门外板",
        "project_id": 7,
        "project_name": "前门模具V2.0",
        "distance": 0.042156,
        "similarity": 1.0
      },
      {
        "rank": 2,
        "model_id": 41,
        "model_name": "前门内板模型.stp",
        "part_name": "前门内板",
        "project_id": 7,
        "project_name": "前门模具V2.0",
        "distance": 0.089312,
        "similarity": 0.5286
      }
    ]
  }
}
```

### curl 示例

```bash
curl -X POST http://localhost:8001/api/v1/models/match \
  -H "Content-Type: application/json" \
  -d '{"file_path": "/data/upload/query_part.stl", "top_k": 5}'
```

---

## 四、Java 端调用指南

### 4.1 调用方式

使用 Java HTTP 客户端（如 `RestTemplate`、`WebClient`、`OkHttp`、`Hutool HttpUtil`）发送 JSON 请求。

**RestTemplate 示例（入库）：**

```java
RestTemplate restTemplate = new RestTemplate();
HttpHeaders headers = new HttpHeaders();
headers.setContentType(MediaType.APPLICATION_JSON);

Map<String, Object> body = new HashMap<>();
body.put("file_path", filePath);
body.put("creator", "admin");
body.put("description", "前门外板点云");

HttpEntity<Map<String, Object>> request = new HttpEntity<>(body, headers);
ResponseEntity<String> response = restTemplate.postForEntity(
    "http://192.168.x.x:8001/api/v1/models/ingest",
    request,
    String.class
);

// 解析响应，保存 model_id
JSONObject result = JSONUtil.parseObj(response.getBody());
int code = result.getInt("code");
if (code == 0) {
    int modelId = result.getJSONObject("data").getInt("model_id");
    // 保存 modelId 到业务表，后续查询和关联用
}
```

### 4.2 注意事项

**1. 文件路径必须是 Python 服务能访问到的路径**

Java 和 Python 部署在同一台服务器（或共享存储），`file_path` 是 Python 服务器上的绝对路径，不是 URL：

```
正确: "/data/models/part_A.stl"        ← 服务器上的实际路径
错误: "http://xxx.com/files/part.stl"   ← 不要传 URL
错误: "C:\\Users\\xxx\\Desktop\\a.stl"  ← 如果 Python 跑在 Linux 上不能传 Windows 路径
```

**2. 入库是同步接口，会阻塞 3~5 秒**

特征提取是 CPU 密集型操作，单个文件处理大约需要 3~5 秒。Java 端调用时建议：
- 设置 HTTP 超时：连接超时 5 秒，读取超时 30 秒
- 如果批量入库，建议逐个调用，不要并发（FAISS 索引写入有锁）

**3. 务必保存返回的 model_id**

入库接口会新建 `kb_model_3d` 记录，返回的 `model_id` 是后续所有操作的关键：
- 查询点云：`GET /api/v1/models/{model_id}/pointcloud`
- 匹配结果中的 `model_id` 也是这个值

**4. 匹配接口的文件不需要先入库**

匹配接口是传一个新的 3D 文件，临时提取特征做搜索，不会写入数据库或 FAISS 索引。

**5. similarity 归一化说明**

`similarity` 是相对值，不是绝对相似度。它是基于当前 top_k 结果中最大距离做归一化的：
- 第 1 名的 similarity 始终为 `1.0`
- 后续排名的 similarity = `1 - (distance / 最大distance)`

不要用 similarity 做跨次查询的比较，它只代表单次查询内的相对排名。跨次比较应该用 `distance`（L2 距离）。

**6. 错误处理建议**

```java
JSONObject result = JSONUtil.parseObj(responseBody);
int code = result.getInt("code");
String message = result.getStr("message");

switch (code) {
    case 0:
        // 成功
        break;
    case 40001:
        // 文件路径无效 或 查询的 model_id 无点云记录
        break;
    case 40003:
        // 文件格式不支持（非 STL/STP/STEP）
        break;
    case 50001:
        // Python 内部处理失败
        break;
    case 50002:
        // FAISS 索引为空，还没有任何模型入库
        break;
    case 50003:
        // STP 转 STL 失败
        break;
    default:
        // 未知错误
        break;
}
```

**7. 健康检查接口**

部署后可用健康检查确认服务状态：

```bash
curl http://192.168.x.x:8001/api/v1/health
```

```json
{
  "code": 0,
  "data": {
    "status": "healthy",
    "faiss_loaded": true,
    "faiss_vector_count": 59,
    "mysql_connected": true
  }
}
```

`faiss_vector_count` 表示当前已入库的模型数量。

### 4.3 典型调用流程

```
用户上传模具项目到 Java 平台
    ↓
Java 将 STP/STL 文件保存到服务器（如 /data/models/xxx.stl）
    ↓
Java 调用 Python 入库接口：POST /api/v1/models/ingest
    参数: { file_path, creator, description }
    返回: { model_id: 2, ... }
    ↓
Java 保存返回的 model_id，用于后续关联
    ↓
（Python 自动完成：kb_model_3d + kb_programming_project_file + kb_model_3d_point_cloud 三张表写入）
    ↓
前端需要查看点云信息时：GET /api/v1/models/{model_id}/pointcloud
    ↓
用户在前端点击"相似模型匹配"：
    Java 调用 Python 匹配接口：POST /api/v1/models/match
    参数: { file_path, top_k }
    ↓
Java 拿到 matches 列表，渲染到前端展示
```
