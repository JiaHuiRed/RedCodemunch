# RedCodemunch

jcodemunch-mcp 的 RedCode 定制 fork —— 按真实使用数据砍掉 91 个工具中的 39 个，只留实际在用的 52 个。

> 给新会话的自己：这是一个瘦身版 jCodeMunch。工具怎么用看 [AGENTS.md](AGENTS.md)（Code Exploration Policy）；本文件解释这份 fork 是什么、为什么这么改、环境怎么跑。上游英文文档见 [README.md](README.md)，保持原样不动，方便 sync。

## 它是什么

- 上游：[jgravelle/jcodemunch-mcp](https://github.com/jgravelle/jcodemunch-mcp)，2026-08-26 从 v1.108.299 切出
- 维护：JiaHuiRed 自用（RedCode agent 工作流的代码检索 MCP），不向上游提 PR——瘦身与上游"全量工具"哲学相反
- 定位：索引一次代码库，按符号精确取代码，替掉盲读全文的 token 浪费

## 为什么瘦身

从 RedCode 生产数据统计（redcode.db part 表，235,569 条部件记录）：

- 91 个工具里只有 **30 个被调用过**，61 个从未用
- 总调用约 815 次，前四名：search_symbols(202)、get_file_content(149)、search_text(120)、get_symbol_source(99)
- 结论：真实使用面 ≈ 10 个高频工具，其余全是长尾

## 删了什么（39 个）

| 类别 | 数量 | 说明 |
|---|---|---|
| A 场景不存在 | 32 | dbt 列检索、团队度量仪表盘、embedding 管理、运行时 trace、handoff 工具等——依赖的数据源或工作流这里根本没有 |
| D 上游开关 | 7 | analyze_perf、tune_weights、set_tool_tier 等——默认 full profile 下从未启用的自嗨机制 |

完整 39 名单见 [CHANGELOG.md](CHANGELOG.md) Unreleased 段。

**保留的 B 类 19 个**：被 grep / git diff 等更短路径替代，但 AGENTS.md 点名教学过。其中 7 个已放行进 RedCode 白名单试用：check_references、get_dependency_graph、get_blast_radius、get_changed_symbols、find_dead_code、get_class_hierarchy、register_edit。

## 52 工具清单（full profile 全集）

announce_model, assemble_task_context, check_delete_safe, check_edit_safe, check_references, check_rename_safe, find_dead_code, find_implementations, find_importers, find_references, find_similar_symbols, get_architecture_metrics, get_blast_radius, get_call_hierarchy, get_changed_symbols, get_class_hierarchy, get_context_bundle, get_dead_code_v2, get_dependency_graph, get_extraction_candidates, get_file_content, get_file_outline, get_file_tree, get_hotspots, get_impact_preview, get_ranked_context, get_related_symbols, get_repo_health, get_repo_map, get_repo_outline, get_session_context, get_session_snapshot, get_session_stats, get_symbol_complexity, get_symbol_provenance, get_symbol_source, get_tectonic_map, index_dependency, index_file, index_folder, index_repo, jcodemunch_guide, list_repos, plan_refactoring, plan_turn, register_edit, resolve_repo, search_ast, search_symbols, search_text, suggest_queries, winnow_symbols

**生产工具面其实更窄**：`~/.code-index/config.jsonc` 设了 `tool_profile: "core"`（17 个核心工具 + announce_model），RedCode 客户端白名单再过滤一层（23 个）。所以"生产 52 全集"只是 full profile 的理论上限。

## 环境与验证（新会话必读）

本项目用 uv 管理，**测试必须走 `uv run pytest`**：

```bash
uv sync                                    # 建 .venv (cpython-3.13)
uv run pytest                              # 全量 ~4 分钟（xdist: -n auto --dist loadfile）
uv run pytest --lf                         # 只重跑上轮失败
PYTHONUTF8=1 uv run python -c "..."        # 冒烟；GBK 编码问题用它兜底
```

⚠ 坑：全局 python 的 site-packages 里有个 editable install 指向 `E:\AI\RedCode\jcodemunch-mcp`（旧 clone）——直接 `pytest` 会测到旧包，必须 `uv run`。

已知预存失败 38 个（语言解析类：C/Bash/Arduino/Ada/Clojure 等），是 Windows wheel 的 tree-sitter-language-pack 0.13.0 grammar 失效，上游 CI 在 Linux 上全绿所以没发现。**与瘦身无关，不用修**。

## Agent 快速上手（五步）

1. `resolve_repo {"path": "."}` — 确认项目已索引，没有就 `index_folder`
2. `plan_turn {repo, query, model}` — 拿置信度 + 推荐文件，按 confidence 走
3. 找代码：`search_symbols`（符号）/ `search_text`（字符串）→ `get_file_outline` → `get_symbol_source`
4. 关系与影响：`find_importers` / `find_references` / `get_blast_radius` / `check_references`
5. 改完代码调 `register_edit` 保索引新鲜

详细规则（含 _meta.confidence/freshness 信封语义、Model-Driven Tool Tiering）看 [AGENTS.md](AGENTS.md)。

## 与上游同步

- push 到 origin（自己 fork）不影响 upstream；fork 内容独立，GitHub 不回同步
- 将来 sync 上游新版本时，server.py（canonical 名单/dispatch 链）、config.py、counter.py、meta-tests 会结构性冲突（上游 91 vs 我们 52），手工合，工作量可控
- 回滚保险：被删实现备份在 `.redcode/temp/trash_tools/`（正式 commit 后可清）；git 历史可整体回退
