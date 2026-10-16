# GitHub 上传与发布说明

本文件供维护者使用。主 README 使用中文 Markdown，包含功能、部署、使用、数据、开发、反馈与版权说明。

## 仓库根目录

将 `sdut-webui` 内的源码作为仓库根目录，使 `README.md`、`LICENSE`、`Dockerfile` 和 `compose.yaml` 直接位于根目录。

不要把外层输出目录或工作目录整体上传，它们可能包含真实账户、抓包、课表、运行数据库或本机管理员信息。文档采用相对路径，不要替换为电脑绝对路径。

## 上传前检查

- [ ] README 版本、功能与实际镜像一致。
- [ ] CalDAV 明确为占位，没有写成已实现功能。
- [ ] 平台厂商说明保留“同协议、需验证”的边界。
- [ ] `LICENSE` 为完整 Apache-2.0 文本，`NOTICE` 保留开发者署名。
- [ ] `.env`、数据目录、`master.key`、数据库、token、学校密码和站内管理员信息未被跟踪。
- [ ] 原始 HAR、真实接口响应、个人课表与私密订阅链接未被跟踪。
- [ ] 截图已脱敏，且使用相对路径引用。
- [ ] 目录、文档链接和命令均可阅读。

`.gitignore` 不能清除已经提交过的秘密。若秘密已提交过，应撤销相关凭据，并在发布前处理历史记录。

## 截图

主 README 已附 8 张独立演示环境截图，均使用虚构数据与不可用的示例订阅地址。按照 [截图维护说明](images/README.md) 替换图片即可；保持文件名不变时，无需修改引用。

## 仓库信息建议

| 项目 | 建议内容 |
| --- | --- |
| Description | 课表同步与日历订阅工具，支持教学、实验、自定义同协议学校与 Docker 部署。 |
| Topics | `calendar`、`icalendar`、`ics`、`timetable`、`docker`、`python`、`sqlite` |
| Website | 已实际开放的项目站点；没有站点时留空，不填个人局域网地址 |
| Issues | 根据是否接受公开反馈自行开启 |
| Social preview | 可选项目封面，与 README 截图属于不同设置 |

项目仓库为 `https://github.com/liuayueeryuan0313/KOMA`。README 的克隆命令使用此地址；未实际提供的下载、容器仓库或 CI 地址不要写成可用服务。

## 发布离线镜像

Docker 镜像包建议放在 GitHub Releases 资产中，与源码分开管理。

```text
koma-docker-v0.3.0-linux-amd64.zip
koma-docker-v0.3.0-linux-amd64.sha256.txt
koma-docker-v0.3.0-linux-arm64.zip
koma-docker-v0.3.0-linux-arm64.sha256.txt
```

发布标签可使用 `v0.3.0`。说明主要变化、支持架构、升级与持久化事项，以及 ARM64 仿真验收、其他学校兼容范围等实际限制。

未在 Docker Hub 或 GHCR 发布镜像时，不写不存在的 `docker pull` 地址。当前离线流程是 `docker load`，源码流程是本地构建。

## 后续更新

版本变更后，核对标题版本、离线包名、镜像标签、功能状态、验收记录和截图。已有镜像包内置的 README 不会因修改仓库文件自动改变，需要随新打包产物更新。

本文只提供上传准备，不会自动创建仓库、推送提交、发布 Release 或改变仓库可见性。

参考：[GitHub 关于 README](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes)。

