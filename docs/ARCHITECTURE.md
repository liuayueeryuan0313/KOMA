# 实现与接口

`server.py` 提供静态 WebUI、账户 REST API 与私密 ICS；`core.py` 管理 SQLite、加密、权限和持久化；`sync.py` 执行手动任务、定时任务和教学故障转移；`adapters/school_bridge.mjs` 通过标准输入接收凭据，调用学校适配器。凭据不放在命令行参数，不把上游原始错误或响应直接写入日志。

## 三条接入链

| 来源 | 登录与数据链 | 输出 |
| --- | --- | --- |
| App | RSA/AES 登录 → H5 token → 当前学期、教学周 → 全学期逐周拉取 | 教学快照 |
| 教务系统 | 登录页面 CSRF → RSA PKCS#1 v1.5 密码提交 → Cookie 会话 → 学期课表查询 | 排课规则 → 教学快照 |
| 实验平台 | 学生服务大厅 CAS → 服务 ticket 回调 → 实验服务 Authorization → 签名分页查询所有页 | 实验项目 → 实验快照 |

App 重新登录仅通过显式授权入口。学校身份优先读取真实姓名，缺失时显示学校用户名；教务、实验响应的学号会与当前账号校验。实验平台单独处理页数、总数与完整性，不参加教学故障转移。

统一快照经过 `normalize`、日期与节次校验、`compile_calendar` 后写入数据库。仅在成功时替换当前 ICS；两份成功快照随后重新生成聚合。调度器每 15 秒检查到期计划，最多 3 个工作线程，同一用户任务串行，计划由数据库保存。**只运行一个应用实例**，本版没有多实例分布式锁。

## HTTP API

| 方法 / 路径 | 用途 |
| --- | --- |
| GET `/healthz` | 健康检查 |
| GET `/api/bootstrap` | 首次设置状态、注册状态、免责声明 |
| POST `/api/setup` | 一次性设置码创建首个管理员 |
| POST `/api/register` | 创建普通用户 |
| POST `/api/login` / `/api/logout` | 站内会话 |
| GET `/api/session` | 用户和 CSRF token |
| GET `/api/dashboard` | 本人来源状态、日期、统计、课表、链接和最近日志 |
| PUT `/api/settings` | 本人学校账号、加密凭据、学期、教学模式与更新计划 |
| POST `/api/sync` | `scope=teaching/lab/all`；拒绝 `initialize_app=true`，同步绝不登录 App |
| POST `/api/platforms/{app|jw|lab}/test` | 认证后完整拉取与转换检查；不发布、不保存临时凭据 |
| POST `/api/platforms/{app|jw|lab}/login` | 显式登录；App 获取 token 需确认手机会话风险 |
| POST `/api/links/{kind}/rotate` | 更换指定种类私密订阅链接 |
| POST `/api/account/password` | 校验当前站内密码后更改，并注销原会话 |
| GET `/api/admin/users` | 管理员用户列表 |
| PATCH `/api/admin/users/{id}` | 管理员调整权限或停用状态 |
| GET / HEAD `/cal/{token}/{kind}.ics` | 无登录私密订阅，支持 ETag / 304 |

已登录的修改请求使用 `X-CSRF-Token`，并校验 Origin、JSON 内容类型；会话 Cookie 为 HttpOnly / SameSite Strict，HTTPS 可配置 Secure。登录、注册、初始设置有限流。普通注册不会接受客户端指定的管理员权限。

`kind` 为 `teaching/lab/combined`。三种私密链接分别校验种类，不能互换。订阅请求直接提供数据库最近成功 ICS，不在客户端访问时触发学校重新登录。

## 时间与日志语义

- `last_attempt`：最近学校同步任务开始时间，成功或失败都更新。
- `last_success`：学校拉取、转换并发布成功时间，失败不覆盖。
- `next_run`：下次学校自动同步的计划时间，关闭自动更新时为空。
- `calendars.updated_at`：对应日历版本写入时间，与学校同步任务时间分别保存。
- `school` 日志：三种学校平台登录/拉取的开始、完成、条数或失败。
- `sync` 日志：归一化、故障转移、合并、发布及保留旧版。
- `delivery` 日志：日历客户端 GET 获取、304 检查与私密链接更换。

数据库/API 时间为带时区 UTC 字符串，WebUI 显示北京时间。每用户保留最近 1000 条日志，当前界面/API 返回最近 100 条；访问量很大时较早拉取记录可能滚出最近列表。

## 后续扩展边界

基础版尚未包含邮件、Webhook 或系统推送渠道；“订阅访问日志”记录服务向日历客户端提供内容，不能证明手机已刷新或展示通知。没有自动识别新学期，需修改学期设置；没有验证码识别或自动绕过。学校接口变更时修改对应适配器并重新验收，不修改其他来源的归一化和订阅规则。

## v0.2.0 状态规则

`platform_checks` 按用户、平台和操作保存独立测试/登录结果、学校身份与检查时间，不覆盖学校同步成功时间。加密凭据中的 `token_invalid` 在确认失效后锁定 App 访问；自动教学直接使用教务，手动填入新 token 或显式获取成功才清除。普通网络故障不触发故障转移。调度任务与 App 测试均无重新登录路径。

## v0.3.0 学校配置

`school_profiles.py` 校验每用户学校目的地址、参数与作息。学校切换先清除旧凭据与日历、轮换私密链接；临时测试不保存配置或沿用旧学校秘密。Node `school-profile.mjs` 提供默认配置、基址拼接、教务请求配置及受限网络传输；自定义连接固定已验证的公开 DNS 地址，不自动跟随跨域重定向。App 登录、H5 拉取、正方登录与课表、实验与 CAS 均使用当前学校配置。不同协议不通过改域名自动适配。

前端 ICS / CalDAV 标签是显示切换。CalDAV 仅占位，没有服务器端 DAV 功能。
