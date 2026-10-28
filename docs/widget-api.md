# KOMA 小组件接口 v1

本协议对应包内代码和 `example-response.json`，示例为虚构数据。JSON 使用 UTF-8，正常及错误响应均为 `Cache-Control: no-store`。时间计算统一为北京时间；课程时间显式包含 `+08:00`，生成时间为 UTC。

## 读取课表

```http
GET /api/widget/v1/timetable?days=3&offset=0
Authorization: Bearer <本用户的 kw_ 专用 Token>
Accept: application/json
```

支持 GET 和 HEAD。无需 Cookie、CSRF 或学校登录；每次读取只查询本地已有课表，不启动同步。Token 由服务端映射到用户，不能通过参数指定其他账户。

| 参数 | 默认 | 范围及语义 |
| --- | --- | --- |
| days | 3 | 1–7，返回连续自然日数量 |
| offset | 0 | -365–365，相对北京时间今天的偏移天数 |

重复、未知或非法参数返回 400。Token 只能放在 Authorization 请求头，不能放在 URL。前端三日组件固定请求 `days=3`，跨周、跨月依然是连续三天。

### 顶层字段

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| schemaVersion | integer | 固定 1；客户端拒绝不支持的版本 |
| generatedAt | string | 此次响应生成时间，不代表学校数据刷新时间 |
| timezone | string | 固定 Asia/Shanghai |
| state | string | ok：两种课表均存在；partial：仅一种存在；unavailable：均不存在 |
| range | object | startDate、endDate 为含首尾的 YYYY-MM-DD；days 为天数 |
| term | object | name 为学期名；firstMonday 为第 1 教学周周一；maxWeeks 为学期周数或 null |
| sources | object | teaching 和 lab 两个数据源的状态，见下 |
| days | array | 按日期升序，每个日期均存在，即使 courses 为空 |

`sources.teaching`、`sources.lab`：`available` 表示已有成功课表快照，`updatedAt` 为该快照更新时间，`lastSuccess` 为同步最近成功时间，`syncState` 沿用原项目同步状态。时间无记录时为 null。同步失败时仍可返回上次成功课表；因此顶层 state=ok 不等于“刚刚同步成功”，需一并读取 sources。

每个日期包含 `date`、`weekday`（周一为 1，周日为 7）、`teachingWeek` 和 `courses`。教学周按 firstMonday 计算，假期可能小于 1 或大于 maxWeeks，手机可在学期范围外隐藏周数。

### 课程字段

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| id | string | 课次标识，沿用原 occurrenceId 或确定性生成 |
| kind | string | teaching 或 lab，用于课程配色 |
| name | string | 可直接显示的名称；实验优先使用具体实验项目名 |
| projectName | string/null | lab 与显示名称一致；teaching 为 null |
| location | string | 教室，缺失为空字符串；不附加教师 |
| date | string | 所在日期 YYYY-MM-DD |
| startAt、endAt | string | ISO 8601，北京时间 +08:00 |
| startPeriod、endPeriod | integer/null | 节次，沿用原标准化数据 |
| timeOverlap | boolean | 与另一课次时间实际重叠 |

不返回教师、学校密码、学校会话、原始抓取数据、用户配置或日志。实验项目优先读 projectName；旧数据没有时，从名称中去掉【实验】及分隔符前的父课程名。原始数据若根本没有具体项目名，接口无法凭空补出，需项目同步端补齐。

接口返回窗口内所有课次。4×4 小组件可每天最多显示五门并加“另有 N 门”；不能在接口中截断，以免信息丢失。空课程数组代表该日无已知课程，数据源不可用时应标记“尚无课表”，不要显示成确定无课。

## Token 管理

这两个路由只供已登录的原网页账户使用，Bearer Token 不能调用管理功能。

| 方法和路径 | 请求 | 响应 |
| --- | --- | --- |
| GET /api/widget/token | 原登录 Cookie | configured、createdAt、scope、expiresAt；不返回原 Token |
| POST /api/widget/token | Cookie + X-CSRF-Token + JSON `{"action":"rotate"}` | 新 token、createdAt、scope、expiresAt |
| POST /api/widget/token | Cookie + X-CSRF-Token + JSON `{"action":"revoke"}` | `{"configured":false}` |

POST 保留原项目同源校验。scope 固定 `timetable:read`，expiresAt 为 null，不随网页会话过期。每个 KOMA 用户只有一个专用 Token；rotate 立刻替换旧 Token，多个设备使用时需一起更新。原始 Token 只在生成时返回，SQLite 仅保存 SHA-256。

保存原数据卷后重启、重建容器仍有效；轮换、撤销、用户停用或删除后拒绝访问。Token 不能修改课表、读取管理配置、触发学校采集，也不能登录原网页。CLI 用法见 START_HERE.md。

## 错误与手机缓存

错误响应为 `{"error":"中文原因"}`。401 表示缺失、格式错误、失效或已撤销的 Token；400 表示参数/数据配置错误；503 表示数据库暂不可用；500 表示服务错误。新接口路径 404 通常代表服务器还运行旧版本，需重新构建部署。

手机把 Token 放 Scriptable Keychain，将成功响应缓存到本地；离线或 5xx 时保留上次成功结果并标记缓存时间。401 应提示更新凭证，不能伪装为成功。若缓存日期落后于今天，要按 range 和 date 检查，避免把昨天课程当成今天。`refreshAfterDate` 可建议 15–30 分钟后刷新，实际时机由 iOS 决定，读取频率不改变后台学校同步频率。

## 网页管理与本机管理

登录 KOMA 后进入「订阅日历 → ICS 订阅」，课表订阅下方可生成、更换或撤销小组件 Token。生成后只显示一次；页面不保存明文 Token，也无法再次查询原值。小组件 Token 与 ICS 私密链接分别管理，互不影响。

本机管理员也可在项目根目录执行（容器内数据目录通常为 `/data`）：

```sh
python tools/widget_token.py status --username USER --data-dir /data
python tools/widget_token.py rotate --username USER --data-dir /data
python tools/widget_token.py revoke --username USER --data-dir /data
```

`rotate` 的输出包含新 Token，须私下交给对应用户，勿写入公开日志。工具只操作已存在的数据库，不重置运行中的同步任务。升级时保留原数据卷即可保留 Token；此功能不要求额外环境变量。
