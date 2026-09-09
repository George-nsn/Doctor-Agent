# Chinese Medical Fine-tuning Data

本目录用于整理医疗领域微调数据。数据来源参考用户提供的“23 个医疗领域微调大模型及数据汇总”清单，并优先挑选中文医疗问诊、医学 QA、中医、考试和医疗对话数据。

## Important Notes

- 不把大体量数据直接提交进仓库。
- Google Drive、天池、部分 HuggingFace 数据可能需要登录、授权或人工下载。
- 数据仅用于学习、研究和项目演示；实际使用前必须逐一确认原始数据集 license、隐私和合规要求。
- 医疗数据中可能包含敏感信息，使用前需要做脱敏和安全审查。

## Files

- `dataset_manifest.json`：中文医疗微调数据清单。
- `download_datasets.py`：按 manifest 下载可公开访问的数据。
- `raw/`：下载后的原始数据目录，默认被 `.gitignore` 忽略。
- `samples/`：小样例或转换后的少量演示数据。

## Quick Start

列出数据集：

```powershell
python data/medical_finetune/download_datasets.py --list
```

下载 GitHub 可公开数据：

```powershell
python data/medical_finetune/download_datasets.py --target data/medical_finetune/raw --source github
```

只下载 cMedQA2：

```powershell
python data/medical_finetune/download_datasets.py --target data/medical_finetune/raw --source github --ids cmedqa2_github
```

从 cMedQA2 原始 zip 中抽取 100 条项目统一格式样例：

```powershell
python data/medical_finetune/prepare_samples.py --dataset cmedqa2 --limit 100 --out data/medical_finetune/samples/cmedqa2_sample.jsonl
```

如果 PowerShell `Get-Content` 预览中文时出现乱码，先用 Python 检查：

```powershell
python -c "import json; f=open('data/medical_finetune/samples/cmedqa2_sample.jsonl',encoding='utf-8'); print(json.loads(next(f))['instruction'])"
```

`prepare_samples.py` 已对 cMedQA2 的常见错码做修复，生成的 JSONL 文件本身是 UTF-8。

下载 HuggingFace 数据需要先安装依赖并可能登录：

```powershell
python -m pip install huggingface_hub
huggingface-cli login
python data/medical_finetune/download_datasets.py --target data/medical_finetune/raw --source hf
```

## Recommended First Batch

建议优先关注这些中文数据：

| Dataset | Type | Reason |
| --- | --- | --- |
| Chinese-medical-dialogue-data | 中文医疗对话 | 适合问诊 Agent 和 GuidedIntake |
| cMedQA2 | 中文医学 QA | 适合 RAG QA 评测和问答微调 |
| webMedQA | 中文医学问答 | 适合医学问答检索 |
| Huatuo-26M | 大规模中文医学 QA | 适合知识增强和大规模训练，体量较大 |
| HuatuoGPT-sft-data-v1 | 中文医疗 SFT | 适合指令微调 |
| ChatMed_Consult_Dataset | 中文问诊咨询 | 适合医疗问诊场景 |
| ShenNong_TCM_Dataset | 中医数据 | 适合中医问诊/知识问答 |
| CMB | 中文医学考试/评测 | 适合评测而非直接问诊训练 |

## Data Use In This Project

这些数据后续可用于：

- 生成 `GuidedIntakeAgent` 的问诊追问样例。
- 构造 `EvaluationHarness` 的中文医疗测试集。
- 训练或评测医学 embedding / reranker。
- 构建医学知识库和 Neo4j 图谱实体关系。
- 生成安全防御测试样例，如不安全用药建议、红旗症状遗漏等。
