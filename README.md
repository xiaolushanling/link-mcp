# 链路 ERP MCP

根据[链路开放平台 API 文档](https://demo.linkl.com.cn/doc/index.html)生成的 Python MCP 服务。
当前快照包含 **6 个服务、27 个业务接口**，另有 **3 个本地文档工具**。
使用官方 MCP Python SDK 2.x，支持 stdio 和 Streamable HTTP。

## 通过 Git 使用

与 [UPS MCP](https://github.com/UPS-API/ups-mcp) 的分发方式一致，客户端可通过 `uvx` 从 Git 仓库安装并启动。
需要 Git、Python 3.11+ 和 [uv](https://docs.astral.sh/uv/getting-started/installation/)。
安装 uv 后，确认 MCP 客户端启动进程能找到 `uvx`（必要时重启客户端）：

```shell
python -m pip install uv
uvx --from git+https://github.com/xiaolushanling/link-mcp.git link-mcp --help
```

将 [mcp-config.example.json](mcp-config.example.json) 加入支持该配置格式的 MCP 客户端：

```json
{
  "mcpServers": {
    "link-mcp": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "git+https://github.com/xiaolushanling/link-mcp.git", "link-mcp"],
      "env": {
        "LINK_API_BASE_URL": "https://demo.linkl.com.cn/api",
        "LINK_TOKEN": "YOUR_LINK_TOKEN",
        "LINK_CUSTOMER_KEY": "YOUR_CUSTOMER_KEY"
      }
    }
  }
}
```

将 `LINK_API_BASE_URL` 改为实际网关根地址，保留 `/api`，不要加入 `/lmsservice` 等服务路径。
例如国际物流轨迹请求会发送到
`LINK_API_BASE_URL + /lmsservice/openapi/queryTracks`。
将凭证占位值改为对应环境的真实值；无需默认客户凭证时删除 `LINK_CUSTOMER_KEY` 这一行。
`uvx` 自动建立隔离环境、安装依赖并启动 `link-mcp`，不要求手动克隆或创建项目 `.env`。

不同客户端的配置层级可能不同，可复用上述 `command`、`args` 和 `env`。
如果客户端找不到 `uvx`，将 `command` 改成该程序的绝对路径。

从默认分支更新代码后，可刷新 Git 来源缓存：

```shell
uvx --refresh --from git+https://github.com/xiaolushanling/link-mcp.git link-mcp --help
```

如需固定版本，将来源写成 `git+https://github.com/xiaolushanling/link-mcp.git@<tag或完整commit>`；
此处的版本必须已存在于仓库。Git 安装仍从包内加载接口快照，不会在每次启动时抓取官网文档。

## 本地开发与启动

需要 Python 3.11+。在项目根目录执行（PowerShell）：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

编辑 `.env`：

```dotenv
LINK_API_BASE_URL=https://demo.linkl.com.cn/api
LINK_TOKEN=替换为对应环境的linkToken
LINK_CUSTOMER_KEY=替换为客户customerKey
```

`LINK_TOKEN` 用于所有业务接口的 `linkToken` 请求头。
`LINK_CUSTOMER_KEY` 可选，仅在请求体定义了 `customerKey` 且调用方省略时自动补入。
接口文档中的 `oauthLogin` 仅用于第三方登录，返回重定向地址，不是获取 `linkToken` 的接口。
真实凭证只放 `.env` 或进程环境变量；`.env` 已加入 `.gitignore`。

stdio 启动：

```powershell
.\.venv\Scripts\python.exe server.py
```

stdio 启动后等待 MCP 客户端通信，终端没有欢迎消息属于正常现象。
也可以安装后运行 `link-mcp` 或 `python -m link_mcp`。
`server.py` 默认读取项目根目录 `.env`，后两种方式默认读取当前目录 `.env`；
均支持 `--env-file` 指定文件，现有进程环境变量优先。

## 本地开发客户端与 HTTP 模式

将 [mcp-config.local.example.json](mcp-config.local.example.json) 中的服务配置加入客户端。
其中已使用当前项目的绝对路径：

```json
{
  "mcpServers": {
    "link-mcp": {
      "type": "stdio",
      "command": "D:/pythonProjects/link-mcp/.venv/Scripts/python.exe",
      "args": ["D:/pythonProjects/link-mcp/server.py"]
    }
  }
}
```

客户端协议配置入口不同，可复用这里的 `command` 和 `args`。
移动目录或部署到 Linux 时请相应修改路径。

本机 HTTP 模式：

```powershell
.\.venv\Scripts\python.exe server.py --transport streamable-http --port 8000
```

客户端连接 `http://127.0.0.1:8000/mcp`。此模式是使用同一组环境凭证的单租户服务，
默认只监听本机；远程部署需要由部署方配置入站认证和访问控制。

## 工具与调用示例

完整目录见 [docs/api-tools.md](docs/api-tools.md)。

| 服务代码 | 服务 | 业务工具数 |
| --- | --- | --- |
| `user` | 用户服务 | 3 |
| `lms` | 国际物流 | 11 |
| `pds` | 尾派制单 | 6 |
| `finance` | 结算服务 | 3 |
| `edge` | 综合服务 | 1 |
| `basicdata` | 基础数据 | 3 |

先发现接口，再查看定义，最后传入业务参数：

1. `link_list_services {}`：检查启用服务、接口数量、凭证是否已配置（不会返回凭证）。
2. `link_search_apis {"query":"查价"}`：按中文用途、路径或工具名检索。
3. `link_describe_api {"tool_name":"link_finance_query_price"}`：读取请求和响应 Schema。
4. 调用对应业务工具，`body` 保留官网字段名。

查询轨迹：

```json
{
  "body": {"nos": ["TEST000000001"], "noType": 1},
  "result_limit": 20
}
```

以上参数传给 `link_lms_query_tracks`，对应 `POST /lmsservice/openapi/queryTracks`。

查价（`customerKey` 从环境变量补入）：

```json
{
  "body": {"countryCode": "US", "weight": 1.5},
  "response_format": "json"
}
```

以上参数传给 `link_finance_query_price`。未配置 `LINK_CUSTOMER_KEY` 时需要在 `body` 中传入。
仓库接口也声明了必需请求体，使用 `{"body":{}}`。

推送与 DWS 接口额外需要 `headers.serviceCode`，推送还需要 `headers.event`。
这几类接口在文档中以字符串表示自定义请求体：`body` 是原始文本，服务会直接发送 UTF-8 字节，
不会将 JSON 文本再次编码成带引号的 JSON 字符串；实际结构按双方对接约定提供。
文件上传接口按文档传 `base64`、`fileName` 等字段，MCP 不会任意读取本机文件。

查询工作流可组合“可用产品 → 查价 → 用户选择 → 下单 → 查询详情 → 打印/查询轨迹”。
尾派运费试算返回的 `calPriceId` 可交给 `link_pds_order_by_cal_price` 下单。
创建、取消、删除、上传和推送工具按可能影响业务标注，调用应符合用户意图。

## 返回值与错误

业务调用返回 `success`、`service`、`operation`、`http_status`、`result`；
`result` 保留上游 JSON。上游业务码 `code != 0`、HTTP 错误及本地校验错误都会置 MCP `isError=true`。
参数失败只返回字段路径和约束，不在错误中打印参数值。
默认输出 JSON；`response_format="markdown"` 使用 JSON 代码块，结构化结果仍可供客户端读取。

`result_offset` / `result_limit` **只对本次完整响应的顶层数组或 `result.data` 数组做本地分页**，
不发送给接口，不代表服务端分页，也不保证多次请求之间的数据快照一致。
返回 `pagination.mode="local_response"`、`total`、`has_more`、`next_offset`。
顶层对象保持原结构。超长结果明确返回 `truncated=true` 和文本预览；不会伪装成完整数据。
写操作不要为翻页或重新获取长响应而重复执行，应改用对应查询接口。

本地校验保留 OpenAPI 中的必填、类型、长度、数值及数组约束。
只写在描述里的枚举、条件必填和其他业务规则仍由上游服务校验。
客户端使用请求超时与响应大小限制，禁止自动跟随重定向；**不自动重试任何业务请求**。
写操作超时可能已生效，需先查询状态再决定是否重试。

## 可选配置

| 环境变量 | 默认值 | 含义 |
| --- | --- | --- |
| `LINK_API_BASE_URL` | `https://demo.linkl.com.cn/api` | 网关根地址，包含 `/api`，不含服务路径 |
| `LINK_TOKEN` | 空 | 上游 `linkToken`，业务调用时检查 |
| `LINK_CUSTOMER_KEY` | 空 | 可选客户凭证补入 |
| `LINK_SERVICES` | 空 | 逗号分隔的服务代码，空值启用全部 |
| `LINK_READ_ONLY` | `false` | `true` 时仅暴露 11 个查询业务工具和 3 个文档工具 |
| `LINK_TIMEOUT_SECONDS` | `30` | 请求超时秒数 |
| `LINK_MAX_RESPONSE_BYTES` | `20971520` | 上游响应最大字节数 |
| `LINK_MAX_RESPONSE_CHARACTERS` | `25000` | 返回给模型的最大字符数 |

上游 OpenAPI 的 `servers` 指向其他站点；本服务按网页实际调试逻辑使用
`LINK_API_BASE_URL + contextPath + path`，不会自动切换到生产环境。
没有凭证时仍可启动、检索和阅读接口文档。

## 更新文档与验证

快照位于 `src/link_mcp/data/`，随 Python 包发布。启动时不联网下载文档。
同步先下载到临时目录，全部解析及 Schema 检查通过后再替换文件；同步后重启 MCP：

```powershell
.\.venv\Scripts\python.exe -m link_mcp.sync --tools-file docs/api-tools.md
```

同步只 GET Swagger 配置及文档，不调用业务接口。可用 `--api-base-url` 指定其他文档环境。
快照只读标注为显式名单，官网新增接口默认按非只读处理，更新后应检查工具目录。

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m build
```

测试使用模拟上游，覆盖请求地址、凭证补入、原始文本、嵌套校验、错误、只读过滤、分页及 MCP 握手。
`evaluations/document-workflows.xml` 提供 10 个无需业务凭证的文档评估场景。
离线测试不证明真实账号权限、下单、计费、打印或外部供应商行为，联调时使用对应环境凭证。
