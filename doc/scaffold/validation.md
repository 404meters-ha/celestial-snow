# S6 技术验证门结论 · Agent 脚手架生成能力

> 日期：2026-09-22｜结论：**✅ 通过，V3（S7）可按 architecture.md 方案开工**

## 验证内容

示例需求「待办事项 Web 应用」（选型 FastAPI + Vue 3 + SQLite 自研），用 `scripts/scaffold_dryrun.py`
走 `agent_sdk.run` + `SCAFFOLD_SYSTEM` 生成规范，产物落 `scaffolds/workspace/dryrun/`。

## 结果

| 项 | 结果 |
|---|---|
| 产物 | 13 个文件，六件套齐全（代码骨架/前端/调研/需求/架构/LICENSES） |
| 生成成本 | 4 轮 / $0.11 / 88s（远低于预估 10-30 分钟，thinking 关闭后） |
| 启动核验 | `uvicorn app.main:app` → 页面 HTTP 200（Vue 3 CDN 零构建）+ `/api/todos` 真实响应（sqlite 已初始化） |
| 结构化 TODO | 1 处，格式合规（标注条目名与参考） |
| 选型落位 | fastapi/uvicorn 进 requirements.txt（包型）；Vue 走 CDN；sqlite3 标准库自研 |

## 过程中暴露并修复的问题（两个真坑）

1. **cc-mini openai 路径未关思考**：glm-4.7 的 reasoning_content 挤占 max_tokens（回落 8192），
   首轮即 `finish_reason=max_tokens` 截断、零文件产出。修复：`vendor/cc-mini/src/core/llm.py`
   `_build_openai_request` 对第三方 base_url 加 `extra_body={"thinking": {"type": "disabled"}}`
   （平台自身 `app/services/llm.py` 早有同款修复，agent 链路此前没吃到）。
2. **8192 单轮额度不足**：`agent_sdk.run` 增加 `max_tokens` 透传，生成类任务传 16384（`BUILD_MAX_TOKENS`）。

## 附带基础设施（S6 范围）

- `agent_sdk` 写白名单多根化：`WRITE_ROOTS = [courses/, scaffolds/]`，读/列白名单同步扩 scaffolds/
- `run()` 新增 `system_prompt` / `max_tokens` 参数（任务型调用方自定义身份）
- `tests/test_agent_sdk_boundaries.py`：17 项边界断言全过（穿越/前缀伪造/越权/绝对路径）
- `app/services/scaffold_builder.py`：SCAFFOLD_SYSTEM 生成规范 + build_prompt 组装（S7 直接复用）

## 对 S7 的输入

- 生成质量与成本可行（$0.11/次），「改上游重生成」的迭代策略成本可接受
- 4 轮完成说明 MAX_TURNS 120 余量充足
- 待 S7 落地：六件套校验自动化、zipfile 打包、产物指纹缓存、`/scaffolds` 静态挂载
