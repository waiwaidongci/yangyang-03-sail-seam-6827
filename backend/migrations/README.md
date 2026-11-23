# 数据表初始化

本版通过 `src.models.base.Base.metadata.create_all` 创建首次运行所需的表。模型在 `src/models/workflow.py`，新增 `sampling_plans`、`plan_batches`、`supplements`、`supplement_specimens` 四张表，`analysis_runs` 增加 `kind`、`plan_id`、`supplement_id`。`python -m scripts.seed_demo` 按观测内容键补全演示样本，并在尚无方案时预置 2026-08-14 质检班的两阶段方案和首检，保留现有分析及签核。数据库端口只发布到本机。
