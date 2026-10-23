# 课间 · KOMA

将教学课表与实验课表整理成自己的日历订阅。

支持从校园 App、教务系统和实验平台同步课程，在网页中查看课表，并通过 ICS 订阅到手机与电脑日历。

**v0.3.0** · [Docker Hub](https://hub.docker.com/r/aweo/koma) · [使用指南](docs/USAGE.md) · [Apache-2.0](LICENSE)

## 功能

- **课表同步**：教学与实验独立同步，支持定时更新；失败时保留最近成功的课表。
- **日历订阅**：提供教学、实验和聚合三种私密 ICS 链接，处理单双周、调课与提醒。
- **教学来源切换**：支持 App 优先、仅 App、仅教务系统；App token 缺失或失效时可转用教务系统。
- **多用户管理**：每个用户独立保存学校配置、凭据、课表、订阅与日志。
- **网页查看**：适配桌面和手机，配有纸色、墨绿界面与纸猫动画。

> 已验证山东理工大学；其他学校需符合现有接口协议并自行测试，详见[自定义学校](docs/CUSTOM_SCHOOLS.md)。CalDAV 尚未实现。

## 界面预览

![我的课间：教学与实验同步状态](docs/images/overview.jpg)

![课表一览：按教学周查看课程](docs/images/timetable.jpg)

截图均为虚构演示数据。[查看更多界面](docs/USAGE.md#界面预览)。

## 快速部署

需要已运行的 Docker 与 Docker Compose，镜像支持 **amd64 / arm64**。

### 一键部署（推荐）

在 Linux / macOS / WSL 的 Bash 终端执行：

```sh
bash -c "$(curl -fsSL https://raw.githubusercontent.com/liuayueeryuan0313/KOMA/main/install.sh)"
```

脚本会生成配置、拉取 `aweo/koma:latest` 并启动，随后输出访问地址和首次管理员设置码。

### 手动部署

下载 [compose.yaml](compose.yaml) 和 [.env.example](.env.example) 到同一目录，将后者复制为 `.env`，按需编辑后执行：

```sh
docker compose up -d --wait
docker compose exec komama cat /data/setup-token
```

默认访问 `http://localhost:8080`。手机或局域网访问时，将 `.env` 中的 `BIND_ADDRESS` 设为 `0.0.0.0`，`PUBLIC_URL` 改为服务器实际地址，例如 `http://192.168.1.100:8080`。

[完整部署说明（含离线镜像与源码构建）](docs/USAGE.md#快速部署) · [HTTPS 配置](docs/HTTPS.md)

## 开始使用

1. 打开部署地址，使用设置码创建首个管理员账户。
2. 进入“账户与同步”，选择学校，填写学校凭据并核对学期、周数与作息。
3. 保存配置，按需获取 App token，再执行教学或实验同步。
4. 同步成功后，在“日历订阅”复制链接，添加到日历客户端的**订阅日历**中。

站内密码与学校密码独立。App“登录获取 token”可能使手机 App 退出登录；日常同步复用 token。聚合订阅需要同一学期的教学与实验均同步成功。

**订阅链接会持续更新，下载 `.ics` 后导入仅是一次性副本。** 手机需能访问部署地址，日历刷新频率由客户端决定。操作细节见[学校账户配置](docs/USAGE.md#学校账户与平台操作)与[日历订阅说明](docs/USAGE.md#日历订阅与手机导入)。

## 更新与备份

先[备份完整数据目录](docs/USAGE.md#备份)，再在部署目录执行：

```sh
docker compose pull
docker compose up -d --wait
```

数据保存在 `/data`，备份时必须同时保留数据库与 `master.key`。不要使用 `docker compose down -v` 升级，它会删除数据卷。

## 文档与反馈

[完整使用指南与常见问题](docs/USAGE.md) · [自定义学校](docs/CUSTOM_SCHOOLS.md) · [架构与开发](docs/ARCHITECTURE.md) · [验收记录](docs/VALIDATION.md)

开发者：[安稳](https://github.com/liuayueeryuan0313) · Telegram：[@aweodev](https://t.me/aweodev)。反馈请附版本、部署方式、复现步骤及脱敏后的错误信息。

本项目非学校官方工具，课程安排以学校通知为准。请妥善保管学校凭据与私密订阅链接，不要公开密码、token 或原始抓包。

Copyright 2026 安稳 · [Apache License 2.0](LICENSE) · [NOTICE](NOTICE)
