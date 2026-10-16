# README 截图维护说明

主 README 已插入 8 张 v0.3.0 实际界面截图。它们来自独立演示环境，所有学生信息、课表与同步记录均为虚构数据；订阅地址使用 `calendar.example.com`，不能读取真实课表。

## 截图列表

| 位置标记 | 文件 | 内容 |
| --- | --- | --- |
| `SCREENSHOT:overview` | `overview.jpg` | 首页、教学与实验同步状态、纸猫 |
| `SCREENSHOT:timetable` | `timetable.jpg` | 按教学周查看课程，区分教学与实验 |
| `SCREENSHOT:subscriptions` | `subscriptions.jpg` | 聚合、教学、实验订阅及手机导入说明 |
| `SCREENSHOT:school-settings` | `school-settings.jpg` | 自定义学校与三平台兼容说明 |
| `SCREENSHOT:logs` | `logs.jpg` | 学校拉取记录 |
| `SCREENSHOT:admin` | `admin.jpg` | 管理员与普通用户权限 |
| `SCREENSHOT:mobile` | `mobile.jpg` | 390×844 视口的手机课表 |
| `SCREENSHOT:about` | `about.jpg` | 项目介绍与开发者联系方式 |

## 替换图片

最方便的方式是保持文件名不变，替换本目录中的对应图片并提交。GitHub 中可进入此目录，选择“Add file → Upload files”上传。

更换文件名或格式时，需要同时修改根目录 README 的引用。使用相对路径，例如：

```markdown
![我的课间](docs/images/overview.jpg)
```

路径和文件名区分大小写。不要使用自己电脑上的绝对路径。

每张图片前面的 `<!-- SCREENSHOT:... -->` 仅用于快速定位，不会隐藏下一行的图片，无需删除。需要继续添加新图片时，可以在对应小节直接新增 Markdown 图片。

手机截图使用 HTML 控制展示宽度：

```html
<img src="docs/images/mobile.jpg" alt="移动端课表" width="360">
```

## 截图内容

优先使用演示账号与虚构课程。公开前逐张检查姓名、学号、账号、密码、token、Cookie、二维码和私密订阅链接。真实链接即使只出现在截图里，也可能被其他人识别并用于读取课表。

页面中不要填入有效凭据来展示登录表单。CalDAV 仍为占位页面，截图与图注不能将其描述成已经提供的服务。

桌面截图保留页面布局和可读文字；手机截图保留设备比例。新增效果图或未来界面时，应明确标注其状态。
