# 3D模型相似度检索服务 — 接口开发文档

## 服务信息

| 项目 | 说明 |
|------|------|
| 基础地址 | `http://{host}:8001/api/v1` |
| 协议 | HTTP |
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
| 40001 | 资源未找到 | 查询的 model_id 无点云记录 |
| 40003 | 格式无效 | 文件不是 STL/STP/STEP 格式 |
| 50001 | 处理失败 | 特征提取、数据库写入等内部错误 |
| 50002 | 索引为空 | FAISS 索引中没有向量，需先入库 |
| 50003 | 格式转换失败 | STP 转 STL 失败 |

---

## 一、入库接口

### 基本信息

```
POST /api/v1/models/ingest
Content-Type: multipart/form-data
```

### 处理逻辑

```
1. 接收上传的 3D 文件，保存到服务器 uploads/ 目录
2. 校验文件格式（.stl / .stp / .step）
3. 在 kb_model_3d 表创建记录（model_name = 文件名）
4. 在 kb_programming_project_file 表创建记录（关联文件信息，project_id=NULL）
5. 如果是 STP/STEP → 临时转换为 STL
6. 读取 3D 文件 → 均匀采样 15000 个点 → 生成点云
7. 从点云中提取 64 维几何特征向量
8. 将特征向量加入 FAISS 索引（同一文件覆盖更新）
9. 生成 .npy 文件（内部用）和 .pcd 文件（存数据库）
10. 在 kb_model_3d_point_cloud 表创建记录
11. 返回新生成的 model_id 和处理结果
```

### 请求参数

| 字段 | 类型 | 必填 | 说明 | 示例值 |
|------|------|------|------|--------|
| file | File | 是 | 3D 模型文件（STL/STP/STEP） | `part_A.stl` |
| creator | string | 是 | 创建人（用户 ID 或用户名） | `"admin"` |
| description | string | 否 | 点云描述信息 | `"前门外板点云"` |

**请求示例：**

```bash
curl -X POST http://localhost:8001/api/v1/models/ingest \
  -F "file=@/data/models/part_A.stl" \
  -F "creator=admin" \
  -F "description=前门外板点云"
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
    "vector_db_time": "2026-05-22T14:30:00"
  }
}
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
| project_id | `NULL`（Java 端后续关联） |
| file_name | 文件名 |
| file_type | `"FILE"` |
| physical_path | 文件保存路径 |
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
    "vector_db_time": "2026-05-22T14:30:00"
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
Content-Type: multipart/form-data
```

### 处理逻辑

```
1. 接收上传的查询文件，保存到临时目录
2. 校验文件格式（.stl / .stp / .step）
3. 校验 FAISS 索引非空（至少有一条入库记录）
4. 如果是 STP/STEP → 临时转换为 STL
5. 读取文件 → 采样 15000 个点 → 提取 64 维特征向量
6. 用特征向量在 FAISS 索引中搜索最相似的 top_k 条记录
7. 查询 kb_model_3d + kb_project_mold 表，补充模型名称和项目名称
8. 计算归一化相似度（0~1，越大越相似）
9. 返回匹配结果列表，清理临时文件
```

### 请求参数

| 字段 | 类型 | 必填 | 说明 | 示例值 |
|------|------|------|------|--------|
| file | File | 是 | 待匹配的 3D 模型文件（STL/STP/STEP） | `query_part.stl` |
| top_k | int | 否 | 返回最相似的前 N 条，默认 5，范围 1~50 | `5` |

**请求示例：**

```bash
curl -X POST http://localhost:8001/api/v1/models/match \
  -F "file=@/data/upload/query_part.stl" \
  -F "top_k=5"
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

---

## 四、Java 端调用指南

### 4.1 调用方式

入库和匹配接口使用 `multipart/form-data` 上传文件，Java 端用 `MultipartFile` 或 `RestTemplate` 发送：

**RestTemplate 示例（入库）：**

```java
RestTemplate restTemplate = new RestTemplate();

HttpHeaders headers = new HttpHeaders();
headers.setContentType(MediaType.MULTIPART_FORM_DATA);

MultiValueMap<String, Object> body = new LinkedMultiValueMap<>();
body.add("file", new FileSystemResource(new File("/data/models/part_A.stl")));
body.add("creator", "admin");
body.add("description", "前门外板点云");

HttpEntity<MultiValueMap<String, Object>> request = new HttpEntity<>(body, headers);
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

**RestTemplate 示例（匹配）：**

```java
MultiValueMap<String, Object> body = new LinkedMultiValueMap<>();
body.add("file", new FileSystemResource(new File("/data/upload/query_part.stl")));
body.add("top_k", "5");

HttpEntity<MultiValueMap<String, Object>> request = new HttpEntity<>(body, headers);
ResponseEntity<String> response = restTemplate.postForEntity(
    "http://192.168.x.x:8001/api/v1/models/match",
    request,
    String.class
);
```

### 4.2 注意事项

**1. 文件通过 HTTP 上传，不传路径**

Java 端直接将文件内容上传，不需要 Python 能访问到 Java 的文件系统：

```
正确: 上传文件内容（multipart/form-data）
错误: 传文件路径字符串
```

**2. 入库是同步接口，会阻塞 3~5 秒**

特征提取是 CPU 密集型操作，单个文件处理大约需要 3~5 秒。Java 端调用时建议：
- 设置 HTTP 超时：连接超时 5 秒，读取超时 30 秒
- 如果批量入库，建议逐个调用，不要并发（FAISS 索引写入有锁）

**3. 务必保存返回的 model_id**

入库接口会新建 `kb_model_3d` 记录，返回的 `model_id` 是后续所有操作的关键：
- 查询点云：`GET /api/v1/models/{model_id}/pointcloud`
- 匹配结果中的 `model_id` 也是这个值

**4. 同一文件重复入库会覆盖 FAISS 向量**

如果上传相同文件名的文件入库，FAISS 中只保留最新的一条特征向量，不会产生重复。数据库记录每次都会新建。

**5. 匹配接口的文件不需要先入库**

匹配接口是上传一个新的 3D 文件，临时提取特征做搜索，不会写入数据库或 FAISS 索引。上传的文件用完即删。

**6. similarity 归一化说明**

`similarity` 是相对值，不是绝对相似度。它是基于当前 top_k 结果中最大距离做归一化的：
- 第 1 名的 similarity 始终为 `1.0`
- 后续排名的 similarity = `1 - (distance / 最大distance)`

不要用 similarity 做跨次查询的比较，它只代表单次查询内的相对排名。跨次比较应该用 `distance`（L2 距离）。

**7. 错误处理建议**

```java
JSONObject result = JSONUtil.parseObj(responseBody);
int code = result.getInt("code");
String message = result.getStr("message");

switch (code) {
    case 0:
        // 成功
        break;
    case 40001:
        // 查询的 model_id 无点云记录
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

**8. 健康检查接口**

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

`faiss_vector_count` 表示当前已入库的模型数量（去重后）。

### 4.3 典型调用流程

```
用户上传模具项目到 Java 平台
    ↓
Java 将 STP/STL 文件通过 multipart 上传到 Python
    POST /api/v1/models/ingest  (file + creator + description)
    返回: { model_id: 2, ... }
    ↓
Java 保存返回的 model_id，用于后续关联
    ↓
（Python 自动完成：保存文件 + kb_model_3d + kb_programming_project_file + kb_model_3d_point_cloud 三张表写入 + FAISS 入库）
    ↓
前端需要查看点云信息时：GET /api/v1/models/{model_id}/pointcloud
    ↓
用户在前端点击"相似模型匹配"：
    Java 将查询文件上传到 Python：POST /api/v1/models/match  (file + top_k)
    ↓
Java 拿到 matches 列表，渲染到前端展示
```
