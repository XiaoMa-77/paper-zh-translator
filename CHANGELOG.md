# 更新日志

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循语义化版本。

## [0.3.0] - 2026-10-24

### 新增

- **MCP Server**：`pip install papertrans[mcp]` 后运行 `papertrans-mcp`，Claude 等 AI 助手可直接调用六个工具（doctor / extract_structure / translate_workdir / build_pdf / qa_report / translate_paper 一条龙）；兼容 mcp 1.x（FastMCP）与 2.x（MCPServer）。
- **表格重建为可编辑 HTML**：pdfplumber 多策略抽取（booktabs 横线优先、纯文本对齐兜底），按非空格子数择优；置信度不足（行列太少 / 格子太空）自动回退为图片，不误判正文。表题翻译、单元格保留原文（数字与术语不译）。`--tables auto|image` 可控，默认 auto。

### 改进

- pdfplumber 升级为核心依赖；`doctor` 相应报告表格重建可用性。

## [0.2.0] - 2026-10-24

### 修复

- `papertrans build` 生成的 final.html 把正文渲染了两遍（`document()` 拼装后又整体追加了一次 body）；`run` 不受影响。run 与 build 的组装逻辑合并为 `_finish_pdf()`，从此一处维护。
- 输出 PDF 文件名改用 `os.path.splitext` 推导，不再对整个路径做 `replace(".pdf", ...)`。

### 改进

- 翻译后仍有空缺块时自动补译一轮（只请求漏掉的块），减少因模型偶发漏译导致的退出码 3。
- LLM 请求失败给出可读错误（HTTP 状态码 + 响应片段 / 连接失败原因与排查提示），不再抛裸栈；模型返回的 JSON 解析失败同样带内容摘录。
- `--glossary` 路径写错直接报错。之前会静默跳过，术语约束悄悄失效。
- 质检的数字一致性校验容错千分位与百分号：原文 `1,000` 译作 `1000`、`85%` 译作 `85 %` 不再误报缺失。
- `doctor` 的 pymupdf 版本探测改用 `VersionBind`，不再解析 `__doc__`。
- 删除 `extract.py` 中未使用的 `statistics` 导入。

### 新增

- GitHub Actions CI（`.github/workflows/ci.yml`）：ruff 检查 + 结构级测试 + 自制样本端到端（`--provider none`，不消耗模型额度）。
- `examples/glossary.example.yaml` 术语表模板。
- 本更新日志。

### 文档

- README 补充翻译模型配置说明（`LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` 环境变量与 OpenAI 兼容端点示例）、`--style` 参数、CI 徽章。
- 新增 README 配图：工作流程图 `docs/pipeline.png` 与原译对比图 `docs/compare.png`（对比图由自制样本经真实流水线产出）。

## [0.1.0] - 2026-10-22

- 首个版本：抽取 → 翻译 → 排版 → 打印 → 质检 全流程本地 CLI；`doctor` 环境自检；`--review` 裁剪复核页与 `overrides.json` 人工兜底。
