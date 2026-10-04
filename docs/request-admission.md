# 请求门禁与前端失败提示

07C 是**默认关闭、单进程**的 search/chat 总量保护，不是生产容量调优、按用户限流、账单预算或反滥用体系。本批仅模拟时钟／ASGI／HTTP／Streamlit AppTest／内存库验证，未改运行 `.env`、重启 NAS 或发现场请求。修改和验证历史统一记录在 [开发修改日志](development-change-log.md)。

## 保护范围

`REQUEST_GUARD_ENABLED=false` 时 factory 不创建 guard，不加门禁 middleware，不读门禁时钟；正常 API 请求／响应不增加字段，原行为保留。单独模块 `api.admission` 仅标准库，导入不加载配置、DB 或模型。

明确启用才对 **POST /search、POST /chat**（含尾斜杠路径）应用共享 token bucket＋ASGI 生命周期名额。两接口合用同一份额度；`X-Eval-Run`、Bearer、X-User-Id、X-Forwarded-For、CF-Connecting-IP 都不创建桶或豁免。不把请求头当身份，也不保存 IP、token、query、payload 或逐条时间戳。

health／ready、只读浏览、认证、Co-op、反馈、其他路径／方法及非 HTTP ASGI 消息不受此门禁；这不是“所有接口已限流”。名额检查与扣减用进程内锁，O(1) 状态（tokens／last clock／active），没有队列、周期清理、外部存储、后台任务或持久化日志。即使同时多个线程调用也不超配；release 可重复调用，只释放一次。

配置在 `.env.example` 仅作示例，**没有改运行 .env**：

| 字段 | 默认示例 | 范围／含义 |
|---|---|---|
| REQUEST_GUARD_ENABLED | false | 开关；启用须重启 API，先审容量／路径／调用者共享影响 |
| REQUEST_GUARD_CAPACITY | 8 | 1–10000，初始 burst token 容量 |
| REQUEST_GUARD_REFILL_PER_SECOND | 1.0 | 0.01–1000，有限 tokens/sec，非“每用户请求数” |
| REQUEST_GUARD_MAX_INFLIGHT | 2 | 1–100，两个接口合计同时占用的 ASGI 生命周期 |

这些默认数字未经过 NAS 实测，不是性能最优值。数字布尔值、越界、NaN／Infinity 拒绝；pydantic-settings 仍支持合法环境字符串。`create_app(run_startup=False, admission_guard=...)` 允许测试显式注入 fake clock／policy，不启动模型或持久化配置。

## 准入和失败

1. 只有目标方法／路径读取时钟与额度；没有等待队列。并发已满先返回 **503 service_busy**，Retry-After=1，不扣 token。
2. 有并发名额但 token <1 时返回 **429 rate_limited**，Retry-After 为 `ceil((1−tokens)/refill_rate)` 正整数。不透支，不给拒绝请求补用户查询日志。
3. 接受才扣 1 token、占 1 名额；无论随后是 200、422、业务错误，都消耗这次已接受请求的 token，结束后不返还。拒绝请求会补充经过时间的 token，但不额外扣额度。
4. 名额持有到 `await app(...)` 返回／抛异常，包括所有 stream body 和 app 清理；不在 HTTP headers 或首 token 时提前释放。异常、send 失败、断连处理返回或 coroutine 取消均在 finally 释放，释放不依赖时钟。

计时使用单调 clock、闲置 refill 上限 capacity；时钟倒退／不有限／异常时失败关闭，503 service_unavailable，不放行、不展示异常文本。拒绝响应固定 `detail / error_type / status_code` JSON，`Cache-Control: no-store`、有界整数 Retry-After；不读 body、不调用 route/dependencies、DB 或模型。既有 RequestLogMiddleware 在外层，因此拒绝仍有 x-request-id／访问日志；这**不等于**禁用所有既有日志。

Rate token 只数请求，不数 query 长度、k、实际 Gemini 次数或费用；单请求仍可触发原检索／救援路径。HTTP /ready 200 也不代表当前空闲。慢请求在 max_inflight 内可以长时间占名额，没有强制超时／取消计算或新排队机制。

## 前端行为

ApiError 保留 status_code／detail 的旧调用方式，新增有界 error_type 和 retry_after_seconds。408／429／503／504 使用固定提示，不展示 API／代理原文或原 transport exception；其他状态的既有 detail 兼容保留，**不宣称所有错误原文都已屏蔽**。429／service_busy 区分“频繁”和“忙”；timeout 明确处理可能还在进行，不提示“已撤销”或可安全马上重复提交。

Retry-After 只解析 0–3600 的 ASCII delta-seconds；HTTP-date、越界、符号／小数／坏值当未知，提示稍后。它是提示，不是成功／容量预测，也没有 sleep、倒计时或自动补发。HTTP client 明确不自动 follow redirect，Co-op／feedback／OAuth／chat 写请求均不自动重试。页面 rerun 不重复发送上一条 chat；既有 deep-link 的人工 refresh 行为不在本批改变。

stream 中途 timeout／连接失败仍走 error event，保留已产出内容、固定“仅部分回答／未结束／手动重试”提示，无异常原文。正常 EOF 若未见 done/error，也补 incomplete_stream 错误；malformed JSON 或非对象行仍跳过，未知 event 不当完成。收到 done/error 后结束，不把后面的 event 接成新回答。不是全量 NDJSON schema／最大行长验证。

实际 stream_assistant 会清旧 feedback、遇 error 停止，不绑定未完成回答的反馈凭证；页面保留文字与警告，不伪造完整回答／成功评价。已见 done 的完整回答保留原逻辑；下层服务器可能已经保存完整回答但客户端没收到 done，本批不删除服务器数据或回滚写入，也不将“没收到”称为“未执行”。

## 不变的边界与后续

- 每个 app／worker 有独立桶，重启重置 burst；多 worker、多个 NAS／UI 实例无共享额度。同步 worker／GPU／LLM 在 ASGI 被取消后可能继续执行，本 gate 仅约束 ASGI 生命周期，**不证明计算任务已终止或所有实际模型调用都在名额内**。
- 所有学生共用全局桶，单一使用者仍可挤占资源；匿名／认证／代理可信边界、按身份公平配额和分布式保护未实现。启用前须明确代理拓扑、worker 数、目标吞吐／队列／长流策略，不依靠伪造 header。
- 拒绝不会产生 query_log，future live eval 碰到门禁必须按 [probe 契约](live-probe-contract.md) 中止并报告真实分母，不自动豁免 eval／关门禁、凑成功样本或据此调模型。
- 请求体大小、NDJSON 行长／事件预算、真实客户端断连后底层计算回收及生产配置／并发压力仍待验证。下一入口是这些本地边界，付费／真实后端／static-shape 实验仍须另行授权；不重试已否决的 512→256。
- 06C-1 凭证风险处置、真实账号、留存／备份／分发仍待本人确认。没有部署、真实容量／SLA 或 organic 结论，机器通过不代替上线审批。
