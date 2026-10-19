# 脚本索引（`scripts/` 和 `eval/`）

这份索引按用途分组，列出 `scripts/` 和 `eval/` 下的全部脚本。每个脚本一行：用途、怎么运行、会碰什么、现在的状态。底稿是 2026-10-17 的脚本盘点，2026-10-19 按当时的 main 更新。

## 先看这几条

- **怎么运行：** 在仓库根目录用 `uv run python scripts/<名字>.py --help` 看全部参数（`eval/` 下的换成 `eval/<名字>.py`）。表里只列主要参数。标「模块」的文件没有命令行入口，由别的脚本或测试导入。
- **写库的脚本大多要加 `--commit` 才真正写入。** 不加时只读，或者只打印将要做的改动。不传 `--db-path` 时用配置里的库（`config/settings.py` 的 `sqlite_path`，可以被 `.env` 的 `SQLITE_PATH` 覆盖），也就是本机的运行库。想在副本上跑，就把副本的路径传给 `--db-path`。
- **「会碰什么」一列的说法：**
  - 读库／写库：配置里的库，或者参数指定的库；
  - 联网：发 HTTP 请求（抓 NEU 目录、RMP，或者请求 API）；
  - 调模型：调 Gemini，要 API key，会产生费用；
  - 本地模型：在本机加载 bge-m3 或 reranker；
  - 写文件：写到参数指定的输出位置。
- **会碰线上的：**
  - `scripts/deploy.ps1` 会登录 NAS、上传代码、重启容器；
  - `eval_via_api.py`、`probe_inference_latency.py` 把 `--base-url` 指向线上地址时会请求线上的 /search，写进 query_log 的行带 `X-Eval-Run` 评测标记；
  - `eval_answers_live.py` 的 `--api-base` 只读线上的 GET /course，也带评测标记。
- **测线上性能用 `scripts/eval_via_api.py`。** `eval/run_eval.py` 是进程内重建，不是生产路径。
- **状态：** 在用；发布工具（上线、演练、迁移时用）；数据管线（重建或补数据时用，不常跑）；历史（一次性的脚本，留作复现依据，不删）。
- 「会碰什么」是按代码写法静态整理的，可能有出入。不确定时，先读脚本开头的说明。

## 1. 线上服务、CI 和模型导出

这一组不要随便改：线上服务、CI 和部署都直接用到它们。

| 文件 | 用途 | 怎么运行 | 会碰什么 | 状态 |
|---|---|---|---|---|
| `scripts/backup_daemon.py` | NAS 上的每日 SQLite 备份（compose 里的 backup 服务） | `--once` | 读库、写备份文件、删除过期备份 | 在用（线上） |
| `scripts/rehearse_recovery.py` | 灾难恢复演练 | `--backup-dir --force-rebuild-index --no-cleanup --json` | 只在临时目录里读写、删除 | 在用（CI 每次都跑） |
| `scripts/export_openvino.py` | 把 bge-m3 和 reranker 导出成 OpenVINO IR | `--output --weight-format --only` | 本地模型、写文件 | 在用（线上后端） |
| `scripts/export_models_onnx.py` | 导出 ONNX 版本 | `--output --dtype --device` | 本地模型、写文件 | 在用（备选后端 `rag/onnx_backend.py` 要用） |
| `eval/__init__.py` | 包标记 | 模块 | — | 在用 |

## 2. 发布与运维

| 文件 | 用途 | 怎么运行 | 会碰什么 | 状态 |
|---|---|---|---|---|
| `scripts/release_preflight.py` | 对独立的库副本和存档做离线只读检查 | `--db-copy --plan-file` | 读库（副本，只读打开） | 发布工具 |
| `scripts/rehearse_release.py` | 在新建的临时目录里演练 v1.3–v1.7 的发布 | 无参数 | 只读写临时库 | 发布工具 |
| `scripts/release_rehearsal_fixtures.py` | 演练用的合成输入 | 模块 | 写临时目录 | 发布工具 |
| `scripts/verify_release_imports.py` | 核对存档和离线副本是否一致 | `--db-copy --catalog-file --plan-file` | 读库（副本） | 发布工具 |
| `scripts/verify_index_manifest.py` | 校验 FAISS 索引和 manifest 的哈希 | `--index-path --expected-model --verify-load --json` | 读索引文件 | 发布工具 |
| `scripts/rebuild_faiss.py` | 从 SQLite 重建 FAISS 索引（ADR-0013 灾难恢复） | `--db-path --index-path --all --incremental --status` | 读库、本地模型、写索引文件 | 发布工具。⚠️ `--incremental --status pending` 会把其他课从索引里删掉 |
| `scripts/repair_course_names.py` | 把被句子顶替的课名改回目录标题 | `--db-path --catalog-dir --use-catalog-title --commit` | 写库（要加 `--commit`） | 发布工具 |
| `scripts/sync_catalog_sources.py` | 从 JSONL 存档补目录来源 | `--db-path --catalog-dir --commit` | 写库（要加 `--commit`） | 发布工具 |
| `scripts/eval_via_api.py` | 对指定的 /search 跑固定标签评测；测线上性能用它 | `--base-url --test-set --k --label --out-json` | 联网（请求 `--base-url`；写带评测标记的 query_log，HyDE 可能调模型）、写文件 | 发布工具（每次上线后的评测） |
| `scripts/init_db.py` | 对配置的库执行 `db/init.sql`，可以重复执行 | `--path` | 写库 | 在用 |
| `scripts/migrate_answer_feedback.py` | v1.7 加表迁移 | `--db-path --commit` | 写库（不加 `--commit` 只读） | 发布工具（迁移） |
| `scripts/migrate_coop_submissions.py` | 私有 Co-op 投稿队列和贡献账本的迁移 | `--db-path --commit` | 写库（不加 `--commit` 只读） | 发布工具（迁移） |
| `scripts/migrate_add_query_log.py` | 给旧库加 query_log 表 | `--db-path --commit` | 写库 | 保留：重建旧库时可能要用 |
| `scripts/migrate_db_to_v1_1.py` | 旧库升到 1.1 | `--db-path --commit` | 写库 | 保留：重建旧库时可能要用 |
| `scripts/migrate_db_to_v1_2.py` | 升到 1.2 | `--db-path --commit` | 写库 | 保留：重建旧库时可能要用 |
| `scripts/migrate_schema.py` | 对 courses 全表套用 schema 迁移 | `--db-path --dry-run` | 写库（`--dry-run` 不写） | 保留：重建旧库时可能要用 |

## 3. 数据管线

重建或补数据时用，平时不跑。

| 文件 | 用途 | 怎么运行 | 会碰什么 | 状态 |
|---|---|---|---|---|
| `scripts/scrape_neu_catalog.py` | 抓 NEU 课程目录，写成 JSONL | `--dept --limit --out --overwrite --rate-limit-sec` | 联网、写文件 | 数据管线 |
| `scripts/ingest_neu_catalog.py` | 把 JSONL 写进库，加上跨列别名 | `--in --dept --dry-run` | 写库 | 数据管线 |
| `scripts/ingest_coop_seed.py` | 从整理好的 JSON 导入 Co-op 种子数据 | `--file --db-path --commit` | 写库 | 数据管线 |
| `scripts/load_slang_dict.py` | 把 `data/slang_dict.json` 写进 course_aliases | `--db-path --slang-path` | 写库 | 数据管线 |
| `scripts/mark_pending_indexed.py` | 有 raw_text 的课从 pending 改成 indexed | 无参数 | 写库 | 数据管线（和 `rebuild_faiss.py` 配合用） |
| `scripts/backfill_prereq_edges.py` | 用抓到的先修课号补 course_prerequisites | `--db-path --commit` | 写库 | 数据管线 |
| `scripts/seed_program.py` | 从 `data/program_seed/` 把一个培养方案和它的必修课、先修写进运行库 | `--file --db-path --commit` | 写库 | 数据管线。和 `sync_program_plans.py` 分工不同：后者写的是经过来源核对的结构化方案文档 |
| `scripts/capture_course_requisites.py` | 抓官方院系页面上的先修条款（只存档，不推导资格） | `--dept --catalog-year --output-dir` | 联网、写文件 | 数据管线 |
| `scripts/capture_program_sources.py` | 抓培养方案的官方来源 | `--plan-file --output-dir` | 联网、写文件 | 数据管线 |
| `scripts/capture_program_policy_sources.py` | 抓政策章节 | `--request-file --output-dir` | 联网、写文件 | 数据管线 |
| `scripts/sync_course_requisites.py` | 把核过的存档条款导入已有的库 | `--db-path --manifest-file --source-dir --commit` | 写库（要加 `--commit`） | 数据管线 |
| `scripts/sync_program_plans.py` | 校验并写入结构化的方案文档（v1.5），默认只读 | `--db-path --plan-file --source-dir --commit --allow-downgrade` | 写库（要加 `--commit`） | 数据管线 |
| `scripts/generate_doc_expansion.py` | doc2query 扩写、中文关键词和缩写（ADR-0020） | `--db-path --out --limit` | 读库、调模型、写文件 | 数据管线（偶尔重跑） |
| `scripts/apply_doc_expansion.py` | 把扩写写进库，生成缩写表 | `--jsonl --db-path --min-sigmoid --commit` | 写库、写文件 | 数据管线 |
| `scripts/enrich_course_via_rmp.py` | 用 RMP 和 Gemini 补一门课的软字段 | `--course-id --professor --live --save` | 查 RMP 时联网；`--live` 才调模型（默认只打印提示词）；`--save` 和 `--live` 一起用才写库 | 数据管线 |

## 4. 审查和导出

| 文件 | 用途 | 怎么运行 | 会碰什么 | 状态 |
|---|---|---|---|---|
| `scripts/audit_data_coverage.py` | 数据覆盖、冲突和来源报告，只读离线副本 | `--db-copy --details --max-codes` | 读库（副本） | 在用 |
| `scripts/audit_course_requisites.py` | 选定课程的先修存档报告 | `--manifest-file --source-dir --course-code` | 只读存档文件 | 在用 |
| `scripts/audit_program_rule_sources.py` | 把方案规则和冻结的来源表对照 | `--plan-file --source-dir` | 只读存档文件 | 在用 |
| `scripts/audit_program_policy_sources.py` | 审查政策证据的精确范围 | `--bundle-file --plan-file --policy-source-dir` | 读库 | 在用 |
| `scripts/export_query_log.py` | query_log 的私有导出，默认只出计数 | `--db-path --out --origin --since --until --limit` | 读库、写文件 | 在用 |
| `scripts/export_answer_feedback.py` | 回答反馈候选的私有导出，默认只出计数 | `--db-path --out --origin --since --until --limit` | 读库、写文件 | 在用 |
| `scripts/private_export.py` | 两个导出共用的规则 | 模块 | 读库、写文件、删除自己写坏的输出 | 在用 |
| `scripts/review_coop.py` | 审核员离线审核 Co-op 投稿 | `--db-path --list --show --approve --reject --commit` | 写库（默认 dry-run） | 在用 |

## 5. 评测和测量

| 文件 | 用途 | 怎么运行 | 会碰什么 | 状态 |
|---|---|---|---|---|
| `scripts/eval_answers_live.py` | 用固定的课程证据像 /chat 那样问真实模型，再检查回答 | `--api-base --out --questions --runs --max-calls --dry-run --rescore` | 联网（`--api-base` 只读 GET /course）、调模型（最多 `--max-calls` 次）、写文件。`--dry-run` 不调模型；`--rescore` 只重新检查已保存的回答，不联网、不调模型 | 在用 |
| `eval/answer_checks.py` | /chat 回答的检查器 | 模块 | —（纯函数） | 在用 |
| `eval/run_eval.py` | 进程内重建的 Recall@K、MRR 评测 | `--test-set --mode --db-path --out-json --k --rerank` | 读库、本地模型、写文件 | 在用（离线）。⚠️ 测线上性能用 `eval_via_api.py` |
| `eval/ragas_runner.py` | Ragas 指标（Faithfulness、Context Precision／Recall） | 模块 | 读库；调用方传入 LLM 客户端时调模型 | 在用 |
| `eval/probe_contract.py` | 连线上的探针共用的 fail-closed 规则，包括评测标记 | 模块 | — | 在用 |
| `eval/latency_metrics.py` | 统一的最近秩延迟分位数 | 模块 | — | 在用 |
| `eval/profile_eval.py` | 按固定的查询顺序做可选的性能分析 | 模块 | — | 在用 |
| `eval/route_world.py` | 合成的 /chat 世界：真实的路由、FAISS 和 BM25，模型用脚本代替，库只在内存里 | 模块 | 只用合成的内存库和替身模型 | 在用 |
| `eval/route_eval.py` | 离线合成 /chat 评测：检索、流式和回答分开打分 | 模块 | 只用合成的内存库和替身模型 | 在用 |
| `eval/route_guard.py` | 离线评测期间的进程审计钩子，拦下真实库、索引、网络和子进程 | 模块 | — | 在用 |
| `scripts/eval_route_offline.py` | 跑固定的合成 /chat 用例（`eval/route_cases_v1.json`），把报告写进一个新文件 | `--out`（必须是仓库外、已存在目录里的新文件） | 只写 `--out`；不碰真实 API、模型和库 | 在用（改聊天链路时当回归跑） |
| `scripts/probe_inference_latency.py` | 对指定的 /search 测固定查询序列的延迟 | `--base-url --n --label --out-dir --warmup --timeout` | 联网（请求 `--base-url`，带评测标记）、写文件 | 在用 |
| `scripts/probe_latency.py` | 进程内的 /search，用本机的库、索引和模型 | `--test-set --warmup --iterations --k --rerank --label` | 读库、本地模型 | 在用 |
| `scripts/profile_offline_search.py` | 只分析固定的合成内核 | `--trace` | 只用合成的内存库，不碰真实库和模型 | 在用 |
| `scripts/answer_render_check.py` | 用 Streamlit 真实的渲染器手动检查 `answer_markdown()` | `streamlit run scripts/answer_render_check.py --server.headless true`，再把 `answer_render_check.js` 粘贴到浏览器控制台 | — | 在用（改回答渲染时手动跑） |
| `scripts/regenerate_page_layout.py` | 页面布局快照：默认只核对，`--write` 才更新 | `--write` | 写快照文件（要加 `--write`） | 在用 |

## 6. 历史

一次性的脚本，留作复现依据，不删。

| 文件 | 用途 | 怎么运行 | 会碰什么 | 状态 |
|---|---|---|---|---|
| `scripts/generate_test_set_v03.py` | 生成 v0.3 测试集（ADR-0015、0016） | `--db-path --base --out --seed --no-llm` | 读库、调模型、写文件 | 历史（v0.3 是 v0.4 的来源） |
| `scripts/augment_test_set_mixed.py` | 加 code_switched 类，做成 v0.3.1 | `--db-path --base --out --count` | 读库、调模型、写文件 | 历史 |
| `scripts/build_test_set_v04.py` | 用 pooling 和 LLM 判定做 v0.4 的多标签真值 | `--base-url --db-path --test-set --out --pool-k` | 联网、调模型、写文件 | 历史（重建 v0.4 时才用） |
| `scripts/validate_test_set.py` | 检查 v0.1 的 `eval/test_set.json` | 无参数 | 读库 | 历史（只管 v0.1） |
| `scripts/calibrate_rejection.py` | 标定 ADR-0018 的拒答门 | `--out --n-answerable` | 读库、调模型、本地模型、写文件 | 历史（结果在 `eval/rejection_calibration.json`，重新标定时才用） |
| `scripts/sweep_fusion_v03.py` | RRF 和凸组合的对比（ADR-0022） | `--test-set --out` | 读库、本地模型、写文件 | 历史 |
| `eval/sweep_blend_alpha.py` | α 网格搜索（KPI 4） | `--test-set --out-json --alphas --db-path` | 读库、本地模型、写文件 | 历史（`blend_alpha=0.4` 已经定了）。分位数的算法和 `latency_metrics.py` 不同 |
| `eval/sweep_reject_threshold.py` | 拒答阈值的 ROC 扫描 | `--test-set --out-json --thresholds --db-path` | 读库、本地模型、写文件 | 历史（阈值 0.05 已经定了） |
| `eval/compare_prompts.py` | 两份课程抽取结果的逐字段对比 | `--reference` | — | 历史（抽取提示词 v1、v1.1 那时用的） |
| `scripts/bench_path.py` | 比较 Windows H: 和 WSL2 家目录的 I/O | `--paths --blob-mb --write-decision` | 临时文件读写、删除 | 历史（结论见 ADR-0014：代码放 H:，运行数据放 WSL 家目录） |
| `scripts/probe_rmp.py` | 一次性的 RMP GraphQL 探测 | `--teacher --save` | 联网、写文件 | 历史 |
| `scripts/smoke_hybrid_compare.py` | 早期纯向量和 hybrid 的对比冒烟 | 无参数 | 读库 | 历史 |
| `scripts/smoke_rag_query.py` | 早期的 RAG 冒烟 | 无参数 | 读库 | 历史 |
| `scripts/seed_aai6600.py` | 第一门 ground-truth 课 | `--db-path --output-dir` | 写库、写文件 | 历史，但测试还在用，不能删 |
| `scripts/seed_synthetic_courses.py` | 6 门合成课，用于排序实验 | 无参数 | 写库、删除 | 历史，但测试还在用，不能删 |

## 7. 其他脚本（非 Python）

| 文件 | 用途 | 怎么运行 | 会碰什么 | 状态 |
|---|---|---|---|---|
| `scripts/deploy.ps1` | 从 PC 把代码推到 NAS：上传代码和 `.env`、`docker compose up -d`、核对健康 | PowerShell，参数见文件开头 | **会碰 NAS**：登录、上传文件、重启容器 | 发布工具（`tests/test_deploy_script.py`） |
| `scripts/backup.sh` | 每日备份：SQLite 和 FAISS → 本地快照 → Google Drive（rclone） | crontab，见文件开头 | 读本机的库和索引、写文件、联网（rclone 上传） | PC 本地栈时期的备份；NAS 上由 `backup_daemon.py` 负责 |
| `scripts/enrich_week8_batch.sh` | 对固定的 15 门课逐个跑 `enrich_course_via_rmp.py --live --save`，最后重建 FAISS | `bash scripts/enrich_week8_batch.sh` | 联网、调模型、写库、重建索引 | 数据管线 |
| `scripts/ensure_streamlit_cfg.sh` | 写 `~/.streamlit` 下的两个配置，免得 Streamlit 第一次启动卡在邮箱提示 | `start_stack.ps1` 会调用；可以重复跑 | 写家目录里的配置文件 | 本机开发栈 |
| `scripts/start_stack.ps1` | 在 PC 上开三个窗口：uvicorn、streamlit、cloudflared | `scripts\start_stack.ps1 -Local`；`-Pytorch`、`-ApiOnly` 见文件开头 | 读本机的库和索引、本地模型；**不加 `-Local` 时会起 cloudflared 隧道 `neu-compass`，接公网域名** | 本机开发栈。⚠️ 线上已经在 NAS 上跑这两个域名，在 PC 上请加 `-Local`，除非确定要让 PC 接公网流量 |
| `scripts/start_stack.bat` | 转发给 `start_stack.ps1`，绕开执行策略 | 双击，或在 cmd 里跑；参数原样转发 | 同 `start_stack.ps1` | 本机开发栈 |
| `scripts/stop_stack.ps1` | 停掉上面三个服务 | `scripts\stop_stack.ps1`；`-KeepCloudflared` 只停 WSL 里的两个 | 结束本机进程 | 本机开发栈 |
| `scripts/stop_stack.bat` | 转发给 `stop_stack.ps1` | 双击，或在 cmd 里跑 | 同 `stop_stack.ps1` | 本机开发栈 |
| `scripts/answer_render_check.js` | 配合 `answer_render_check.py`：页面渲染完以后粘贴到浏览器控制台，只输出计数 | 手动 | — | 在用（改回答渲染时手动跑） |

## 不是脚本的文件

`eval/` 下的 `*.json` 是测试集、离线用例和历史评测结果，这里不逐个列。离线评测的用例在 `eval/route_cases_v1.json`。

## 删掉的脚本

2026-10-19 删掉了两个一次性的调试脚本：`scripts/debug_aai_lookup.py`（查 AAI 6640 为什么走不到别名路径）和 `scripts/debug_print_chat.py`（打印一份写死路径的 /chat 响应）。它们没有调用方，也没有测试；需要时可以在 git 历史里找回。
