# Deferred Work

- source_spec: `_bmad-output/implementation-artifacts/spec-1-3-answer-endpoint.md`
  summary: CLAUDE.md 关键 API 速览补 `POST /api/tasks/{id}/answer`（{id, answers}|{id, cancel:true}，404/409×4/400 语义）
  evidence: Story 1.3 评审（盲审11/验证缺口 Other2）指出新端点未入 curl 速览；按 triage 规则改 agent-context 文件须 defer——已于 Story 1.4 折入完成（2026-09-23），此条留档

- source_spec: `_bmad-output/implementation-artifacts/spec-1-4-e2e-and-acceptance.md`
  summary: 产品缺陷：任务时间线 `_append_log` 整列读-改-写在多线程并发追加下丢行（WAL BUSY_SNAPSHOT 静默吞），留痕 ⛔/✅/⏳ 偶发消失——需新故事修复
  evidence: Story 1.4 E2E 三轮实跑复现：run-20260923-165305 丢端点「⛔」（POST 200、工具确实收到 cancel，仅留痕行消失——端点线程 append 与被唤醒工具线程 _restore_running 写相撞）；run-20260923-165640 丢工具「⏳」（settled DB 行证实从未写入——工具超时留痕与 run() 超时/任务层收尾 append 相撞）；run-20260923-165946 全过。修复方向：append 进程内串行化（threading.Lock 包 _append_log）或改 INSERT 型追加表；修复前 askuser_e2e 偶发 exit 1 属暴露而非误报
