# ADR-0021: 签名 session token 取代 X-User-Id 信任 stub

## 状态

Accepted - 2026-06-11 (生产启用;SESSION_SECRET 经 .env 下发)

## 背景

Week 6 起 API 对 `X-User-Id` header 完全信任(代码里自我标注的 stub)。
后果:能连到 API 的任何人(LAN / Tailscale / 公网 tunnel 路由)可以读
level-2 薪资数据、把上传归属到任意用户。整条 Google OAuth + JWT 验证
链路对 API 鉴权是装饰性的 — 2026-06 review 的 #1 安全项。原计划等
React 前端一起改契约;Streamlit 升级为正式产品 UI 后,改动自包含,
无外部协调成本。

## 设计

- **签发**:`app/session_tokens.py`,itsdangerous URLSafeTimedSerializer
  (该依赖在 pyproject 里躺了 5 周没人用),salt 固定,max_age 7 天。
  **唯一签发点**是 `POST /auth/callback` — 即必须先通过真实 Google OAuth
  round-trip + 域白名单。HMAC 签名防篡改;payload(user_id/email)对
  持有者本人可读,不是秘密。
- **验证**:`api/dependencies.get_current_user_id` 读
  `Authorization: Bearer <token>`。无 header → None(匿名,公开路由
  正常);**有 header 但无效/过期 → 401**(显式凭证验证失败绝不静默
  降级为匿名)。
- **coop 路由**:X-User-Id 彻底移除。POST 必须认证;GET 匿名只见
  level-0(语义不变)。
- **CSRF**:OAuth `state` 参数补上(authorize_url 一直支持但没人传)——
  重定向前生成、session_state 暂存、回调一次性核销,不匹配即丢弃 code。
- **Dev 降级**:SESSION_SECRET 为空 → 签发/验证都返回 None,新 checkout
  匿名可跑,不炸(与 reranker-less degraded mode 同思路)。
- **客户端**:ApiClient `session_token` + `set_session_token()`;
  state_manager 随 login/logout 存取;Streamlit 回调链路全接通。

## 验证

- 单测 829 全过(coop 套件改为对 monkeypatch 测试密钥签发真 token;
  新增 roundtrip/篡改/过期/错密钥/空密钥/401 路由测试)
- live(NAS 部署后):无 token POST /coop → 401;垃圾 token → 401;
  匿名 GET → 仅 level-0 ✅

## 后果 / 残留

- 登录态仍只活在 st.session_state(刷新即丢)——cookie 持久化是独立
  后续项,token 本身已支持(7 天有效期)
- compose 8000 端口仍发布在 Tailscale/LAN(deploy 探活 + eval 工具依赖);
  有了真实鉴权后该暴露面的风险已实质降级,保持现状
- API 消费方契约变化:`POST /coop` 需要 Bearer;callback 响应多
  `session_token` 字段。docs/api_contract.md 的对应小节待刷新
