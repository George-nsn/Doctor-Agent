# Program MVP

这个目录是根据 `user_docs/` 里的设计落地的可运行 MVP 原型。

它不是完整医疗产品，而是一个本地可跑的展示版本，用来证明主链路可以串起来：

```text
InputGuard
-> IntakeAgent
-> Conditional routing:
	- 信息不足且无红旗症状：GuidedIntakeAgent -> AnswerComposerAgent
	- 信息足够或有红旗症状：SafetyTriageAgent
	- 急症风险：EmergencyResponseAgent -> OutputSafetyGuard
	- 非急症：MemoryRetrieveAgent -> 普通 RAG 链路
-> DepartmentRouterAgent
-> SearchRouterAgent
-> MCPMedicalWebSearch (PubMed / openFDA)
-> MedicalHybridRetriever (Qdrant + BGE-small-zh + graph expansion)
-> WebEvidenceCleaner
-> EvidenceFusionAgent / ConflictResolverAgent
-> Department Expert Agents
-> ContextBudgetManager
-> AnswerComposerAgent
-> OutputSafetyGuard
-> FollowUpPlannerAgent
-> MemoryWriteGuard
-> EvaluationHarness
```

## Run

先安装项目依赖：

```powershell
python -m pip install -e .
```

在项目根目录运行：

```powershell
python program/medical_agent_system.py --case program/data/sample_case.json --knowledge program/data/mock_medical_knowledge.json --out reports/program-demo/sample_case_result.json
```

输出：

- 控制台 summary。
- `reports/program-demo/sample_case_result.json`：完整 state、trace、证据、答案、回诊计划和评测摘要。

其他样例：

```powershell
python program/medical_agent_system.py --case program/data/attack_case.json --knowledge program/data/mock_medical_knowledge.json --out reports/program-demo/attack_case_result.json
python program/medical_agent_system.py --case program/data/unclear_case.json --knowledge program/data/mock_medical_knowledge.json --out reports/program-demo/unclear_case_result.json
```

`attack_case` 会触发语义安全识别和急症 early exit；`unclear_case` 会触发 `GuidedIntakeAgent` 追问并跳过普通检索链路。

## Real Qdrant Vector Retrieval

当前真实落地组件是 Qdrant Local 持久化向量库，embedding 使用已实际下载并验证的 `BAAI/bge-small-zh-v1.5`（FastEmbed ONNX，512 维）。

下载/验证模型：

```powershell
python program/download_medical_models.py
```

构建本地 Qdrant 索引：

```powershell
python program/index_knowledge.py --knowledge program/data/level_a_medical_knowledge.json
```

Qdrant Local 数据存放在 `.cache/qdrant/`。它适合单进程 MVP；FastAPI 启动时请使用一个 worker。多 worker/多实例部署应改用独立 Qdrant Server。

## LTP 4 Chinese Medical NLP

`IntakeAgent` 已真实接入哈工大 LTP 4 的 `LTP/small`，执行 CWS、POS 和通用 NER，并通过项目医学词典补充疾病、症状、药品等领域实体。通用 LTP NER 不是医学 NER；同名冲突时医学词典优先，避免把“布洛芬”等药名误标成人名。

安装可选 NLP 依赖：

```powershell
python -m pip install -e ".[nlp]"
```

配置：

```text
MEDICAL_LTP_MODEL=LTP/small
MEDICAL_LTP_CACHE=models/ltp
MEDICAL_LTP_REQUIRED=0
```

`MEDICAL_LTP_REQUIRED=0` 时加载失败会退化到正则+医学词典；生产前置检查可设为 `1` 以 fail-fast。LTP 官方许可对商业使用设有付费要求，不能默认用于商业部署。

## Chinese Medical Benchmarks

项目已登记 CBLUE 3.0、作者官方 IMCS-21 GitHub corpus、cMedQA2、CMB、CMExam、PromptCBLUE 和 MedBench。机器可读清单是 `program/data/chinese_medical_benchmark_registry.json`，详细说明见 `../user_docs/chinese-medical-benchmarks.md`。

```powershell
python program/prepare_chinese_medical_benchmarks.py list
python program/prepare_chinese_medical_benchmarks.py status
```

本地已经探测到 CMB 仓库和 `data/CMB.zip`，并已解压至 `data/benchmarks/cmb/`。CBLUE 完整数据需要在天池数据集 95414 页面申请并同意条款；工具不会绕过审批下载。

作者官方 IMCS-21 仓库可以直接准备：

```powershell
python program/prepare_chinese_medical_benchmarks.py prepare --dataset imcs21
python program/prepare_chinese_medical_benchmarks.py status --id imcs21_official
```

该仓库包含完整 2,472/833/811 train/dev/test 中文医患对话，可直接运行 `imcs21-ner` 严格实体级 Precision、Recall 和 F1。仓库没有显式 LICENSE，当前只用于本地研究评测。

cMedQA2 作者仓库也可直接准备，包含 108,000 个问题、203,569 个回答和 train/dev/test 候选集，适合后续 BGE 检索与 reranker 对照：

```powershell
python program/prepare_chinese_medical_benchmarks.py prepare --dataset cmedqa2
python program/prepare_chinese_medical_benchmarks.py status --id cmedqa2_official
```

其 README 明确限定非商业研究用途。

拿到 CMeEE-V2 后，可评测 LTP+训练集医学词典混合管线：

```powershell
python program/benchmark_medical_nlp.py cmeee-v2 `
	--train data/benchmarks/cblue/CMeEE-V2/CMeEE-V2_train.json `
	--eval data/benchmarks/cblue/CMeEE-V2/CMeEE-V2_dev.json `
	--out reports/benchmarks/cmeee-v2-ltp.json
```

该分数是项目混合管线分数，不是 LTP 上游通用 NER 分数。当前尚未取得 CBLUE 数据，因此不声称已有 CMeEE-V2 或 KUAKE-IR 项目分数。

## Real MCP Network Search

MCP v1 stdio server：`program/mcp_tools/server.py`。

当前工具：

- `search_pubmed`：调用 NCBI PubMed E-utilities 搜索论文标题和摘要。
- `search_openfda_drug`：调用 openFDA Drug Label API 获取官方说明书警示、禁忌、不良反应和相互作用。

直接测试 MCP client：

```powershell
python -c "from program.mcp_tools.client import call_medical_tool_sync; print(call_medical_tool_sync('search_pubmed', {'query':'右下腹痛 恶心','max_results':2}))"
```

项目还提供 `.vscode/mcp.json`，可在 VS Code 中启动 `medical-network-knowledge` MCP server。

## FastAPI Service

启动：

```powershell
python -m uvicorn program.api:app --host 127.0.0.1 --port 8000 --workers 1
```

接口：

- `GET /health`：检查 Qdrant 和知识库状态。
- `POST /knowledge/reindex`：重建本地向量索引。
- `POST /consult`：运行完整 LangGraph 医疗问诊准备流程。

请求示例：

```json
{
	"message": "我右下腹痛，从昨晚开始，大概7分，吃了止痛药没效果，有点恶心，没有便血。",
	"session_id": "demo-api",
	"profile": {"age_group": "adult"},
	"history": []
}
```

## Optional LLM API Generation

`AnswerComposerAgent` 已接入 `program/llm_api_client.py`。默认无 key 时使用确定性安全模板；在 `.env` 设置后会真实调用模型 API：

```text
MEDICAL_LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=...
DEEPSEEK_MODEL=deepseek-chat
```

也支持 `openai`、`gemini`、`github_models` 和 OpenAI-compatible 网关。

模型清单见 `program/model_manifest.json`。已下载的是中文检索 embedding；可选生成模型需要显式下载，避免自动占用 3-5GB：

```powershell
python program/download_medical_models.py --generation-model Irathernotsay/qwen2-1.5B-medical_qa-Finetune
```

## Level A Medical Data

`program/download_level_a_sources.py` 可以下载公开官方医学资料并转换成当前检索器可用的知识库格式。

当前 Level A 定义：

- NIH/NLM MedlinePlus Health Topic XML：官方健康主题、症状、诊断和就医提示。
- openFDA Drug Labeling API：FDA SPL 药品说明书字段，包括适应证、警示、禁忌、不良反应和相互作用。

下载并生成知识库：

```powershell
python program/download_level_a_sources.py --out program/data/level_a_medical_knowledge.json
```

使用 Level A 数据跑 demo：

```powershell
python program/medical_agent_system.py --case program/data/sample_case.json --knowledge program/data/level_a_medical_knowledge.json --out reports/program-demo/sample_case_level_a_result.json
```

生成文件会保留 `source_name`、`source_url`、`source_note` 和 `source_metadata`。这些资料可用于问诊准备、检索和安全提示，不替代医生诊断或治疗决策。

### Official Guide Database For Knowledge Graph

`program/ingest_official_medical_sources.py` 会把官方指南、手册和 Level A 数据写入 MySQL 8 staging database，供后续人工审核和 Neo4j 知识图谱构建。

当前实际采集：

- WHO-ICRC Basic Emergency Care 急症评估手册。
- WHO Pocket book of hospital care for children 儿科住院诊疗手册。
- WHO Guideline for the pharmacological treatment of hypertension in adults 高血压指南。
- 8 条 MedlinePlus 健康主题摘要。
- 4 条 openFDA SPL 药品标签。

WHO PDF 按 `CC BY-NC-SA 3.0 IGO` 记录许可和署名；MedlinePlus 仅使用公共领域健康主题摘要；openFDA 按 CC0/其条目标记的权利说明使用。不会系统抓取 NCBI Bookshelf 网页或复制商业医学教材正文。

启动本地 MySQL 8：

```powershell
docker compose -f docker-compose.mysql.yml up -d
```

数据库配置使用 `.env` 中的 `MYSQL_DATABASE_URL`，或 `MYSQL_HOST`、`MYSQL_PORT`、`MYSQL_USER`、`MYSQL_PASSWORD`、`MYSQL_DATABASE`。默认开发配置与 Compose 一致。

全量采集并重建项目表（`--reset` 会删除并重建目标数据库中的项目表，但不会删除 database，仅限开发环境）：

```powershell
python program/ingest_official_medical_sources.py --reset
```

输出：

- MySQL 数据库 `agentic_rag_medical`：知识图谱暂存库。
- `program/data/official_sources/`：WHO 官方 PDF 原始文件。
- 表：`sources`、`documents`、`chunks`、`entities`、`document_entities`、`relation_candidates`、`crawl_runs`。

自动规则抽取的关系只标记为 `pending`；原有人工整理关系标记为 `approved`。每条关系保留来源文档、页码、chunk、证据原文和抽取方法，禁止未经审核直接当成医学事实发布。

导出已批准关系为 Neo4j CSV：

```powershell
python program/export_neo4j_csv.py --status approved
```

如需导出待审核候选用于标注：

```powershell
python program/export_neo4j_csv.py --status approved,pending
```

### Chinese Guidelines, Drug Labels And Licensed Textbooks

三类中国临床知识源的治理配置：

- `program/data/knowledge_source_registry.json`：卫健委、NMPA、全国医学会和授权教材的来源等级、入库策略与版权状态。
- `program/data/knowledge_import_manifest.example.json`：指南、药品说明书、教材三类 manifest 示例。
- `docs/chinese-medical-knowledge-governance.md`：完整字段、证据分层、版权边界和验收规则。

项目将 `authority_tier` 与 `evidence_grade` 分开：全国性专家共识可以是高权威来源，但不自动等于高确定性研究证据。

合规导入本地内容：

```powershell
python program/import_authorized_medical_content.py `
	--manifest program/data/your_authorized_manifest.json
```

规则：

- 卫健委/NMPA/医学会内容默认先保存目录和元数据。
- 全文只有在 `public_domain`、`open_license`、`licensed` 或 `user_provided_authorized` 时允许。
- 教材全文还必须提供 `license_proof_path`；购买或个人阅读权限不等于知识库处理授权。
- 未授权内容会被导入器硬阻断，不会进入 MySQL chunks 或 Qdrant。

把 MySQL 中版权许可且来源已核验的 chunks 写入 Qdrant：

```powershell
python program/index_database_knowledge.py
```

当前已验证索引 1177 个官方 chunks，collection 为 `medical_knowledge_v1`。

Qdrant 通过 `mysql_database`、`runtime_knowledge` 和 `knowledge_file_<hash>` 命名空间隔离正式库、demo 和单文件索引。正式库存在时问诊只检索 `mysql_database`，不会写入运行时副本；正式库不存在时才启用 JSON fallback，防止运行 case 时把正式知识点清空或产生重复证据。

## LLM API Client

`program/llm_api_client.py` 提供一个轻量统一 API 接入脚本，先用环境变量里的 API key 调通模型调用，后续可以接到 `AnswerComposerAgent`、LLM-as-judge 或安全语义分类器中。

支持的 provider：

| Provider | 默认接口形态 | 默认 base URL | 常用 key 变量 |
| --- | --- | --- | --- |
| `gpt` / `openai` | Chat Completions | `https://api.openai.com/v1` | `OPENAI_API_KEY` / `GPT_API_KEY` |
| `codex` | Chat Completions | `https://api.openai.com/v1` | `CODEX_API_KEY` / `OPENAI_API_KEY` |
| `deepseek` | Chat Completions | `https://api.deepseek.com` | `DEEPSEEK_API_KEY` |
| `gemini` | `generateContent` REST | `https://generativelanguage.googleapis.com/v1beta` | `GEMINI_API_KEY` / `GOOGLE_API_KEY` |
| `copilot` / `github_models` | Chat Completions compatible | `https://models.github.ai/inference` | `GITHUB_TOKEN` / `GITHUB_MODELS_API_KEY` |

先复制 `.env.example` 为 `.env`，填入对应 key。不要提交 `.env`。

Dry-run 检查请求格式，不真正调用 API：

```powershell
python program/llm_api_client.py --provider deepseek --prompt "用一句话解释医疗 RAG" --dry-run
python program/llm_api_client.py --provider gemini --prompt "用一句话解释医疗 RAG" --dry-run
```

实际调用：

```powershell
python program/llm_api_client.py --provider gpt --model gpt-4.1-mini --prompt "总结这个医疗 Agent RAG 项目的亮点"
python program/llm_api_client.py --provider deepseek --model deepseek-v4-flash --prompt "总结这个医疗 Agent RAG 项目的亮点"
python program/llm_api_client.py --provider gemini --model gemini-3.5-flash --prompt "总结这个医疗 Agent RAG 项目的亮点"
python program/llm_api_client.py --provider copilot --model openai/gpt-4.1-mini --prompt "总结这个医疗 Agent RAG 项目的亮点"
```

如果使用第三方 OpenAI-compatible 网关，可以覆盖：

```powershell
python program/llm_api_client.py --provider gpt --base-url https://your-gateway.example/v1 --model your-model --prompt "hello"
```

## Scope

当前 MVP 已实现：

- 条件 LangGraph 编排：信息不足时提前追问，急症时 early exit 到急症安全响应，非急症才进入普通 RAG 检索链路。
- 轻量语义安全识别：把 prompt injection、角色劫持、直接开药请求、系统提示词窃取和红旗症状表达变体归一到 intent/signals，并保留置信度与证据片段。
- 疼痛类 GuidedIntake 槽位判断。
- 红旗症状安全分诊。
- 动态专家路由。
- 真实 MCP stdio 工具：PubMed 和 openFDA 网络检索。
- LTP 医疗分词的接口占位与医学词典归一化。
- 真实 Qdrant Local 持久化向量检索，使用 `BAAI/bge-small-zh-v1.5` 中文 embedding。
- MySQL 8 图谱 staging database、关系审核状态和 Neo4j CSV 导出已实现；Neo4j Server/TransH 在线查询仍是下一阶段组件。
- FastAPI `/consult`、`/health`、`/knowledge/reindex`。
- 可选真实 LLM API 回答生成，无 key 时安全 fallback。
- Web 脏数据过滤。
- 证据融合与冲突标记。
- ContextBudgetManager 调用现有 token 打包逻辑。
- 回诊计划和安全记忆写入。
- 简单评测摘要。

## Module Layout

```text
program/
├── medical_agent_system.py          # LangGraph 入口，只负责组图和 CLI
├── common.py                        # 共享 state、trace、文本工具
├── health_consult/                  # 健康咨询模块
│   ├── symptom_parser/              # 症状标准化、InputGuard、GuidedIntake
│   ├── dialog_manager/              # 安全分诊、科室专家路由
│   └── treatment_planner/           # 专家建议、回答生成、输出安全检查
├── medical_knowledge/               # 医学知识库模块
│   ├── knowledge_graph/             # Neo4j/TransH 图谱扩展 mock
│   ├── guideparser/                 # 指南/说明书解析占位
│   └── version_control/             # 知识版本管理占位
├── rag_engine/                      # 检索增强模块
│   ├── retriever/                   # BM25-ish + vector-ish + graph mock 检索
│   ├── reranker/                    # 重排序占位
│   └── conflict_resolver/           # 脏数据过滤、证据融合、冲突标记
├── memory_system/                   # 记忆机制模块
│   ├── transient_memory/            # Redis 滑动窗口占位
│   ├── shorttermmemory/             # 病程跟踪占位
│   ├── longtermmemory/              # 健康档案占位
│   └── memory.py                    # 当前 MVP 的读取和安全写入
├── nlp_center/                      # NLP 中心
│   ├── entity_linker/               # LTP 医疗分词/词典归一化占位
│   ├── medical_embedding/           # 医疗 embedding 占位
│   └── response_generator/          # NLG 占位
├── context_budget.py                # ContextBudgetManager 适配
├── follow_up.py                     # 回诊计划
├── evaluation.py                    # 简单评测摘要
└── data/                            # demo case 和 mock knowledge
```

后续要替换成真实能力：

- 真实 LTP 医疗分词。
- 真实 Neo4j 图谱与 TransH embedding。
- 真实 Web Console。
