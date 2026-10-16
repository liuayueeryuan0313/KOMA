# README 截图插入说明

主 README 预留了 8 处图片位置，使用 HTML 注释隐藏图片语法。因此没有上传图片时，不会显示破图。

## 1. 准备图片

建议使用 PNG；使用 JPG 或 WebP 时，把主 README 中对应扩展名一起修改。文件名使用英文小写与短横线，避免空格和复杂路径。

| 位置标记 | 默认文件名 | 建议展示内容 |
| --- | --- | --- |
| `SCREENSHOT:overview` | `overview.png` | 我的课间：教学与实验状态、上次/下次学校同步 |
| `SCREENSHOT:timetable` | `timetable.png` | 课表一览：课程、教室、实验标记与教学周 |
| `SCREENSHOT:subscriptions` | `subscriptions.png` | ICS / CalDAV 标签、聚合订阅优先排序 |
| `SCREENSHOT:school-settings` | `school-settings.png` | 学校下拉框、自定义参数、适用厂商说明 |
| `SCREENSHOT:logs` | `logs.png` | 学校拉取与客户端订阅访问的分类 |
| `SCREENSHOT:admin` | `admin.png` | 用户权限组与状态管理 |
| `SCREENSHOT:mobile` | `mobile.png` | 手机宽度下的实际界面 |
| `SCREENSHOT:about` | `about.png` | 项目、开发者、GitHub 与 Telegram |

桌面截图建议宽约 1200–1600 像素；手机截图保留设备比例。尺寸只是排版建议，不是上传限制。图片应清楚、文字可读，避免把很长的整页缩成一张难以阅读的图。

## 2. 上传图片

把图片放到仓库 `docs/images/`，与本说明同一目录。可以本地复制后提交，也可以在 GitHub 打开该目录后选择“Add file → Upload files”。

不要把电脑上的 `C:/Users/...` 路径写进 README；其他人无法读取你的本地文件。使用相对路径，例如 `docs/images/overview.png`。

## 3. 启用对应图片

在根目录 `README.md` 搜索对应标记，例如 `SCREENSHOT:overview`。

原内容：

```markdown
<!-- SCREENSHOT:overview
![我的课间：教学与实验同步状态](docs/images/overview.png)
-->
```

上传图片后，删除第一行与最后一行，保留：

```markdown
![我的课间：教学与实验同步状态](docs/images/overview.png)
```

提交后查看 GitHub README 的渲染效果。路径和文件名区分大小写，扩展名必须与实际图片一致。

## 4. 控制显示宽度

普通 Markdown 会按页面宽度展示。手机截图太宽时，可改成 HTML 图片：

```html
<img src="docs/images/mobile.png" alt="课间移动端界面" width="360">
```

需要并排放两张手机图时，可以自行新增图片：

```html
<p>
  <img src="docs/images/mobile.png" alt="移动端课表" width="320">
  <img src="docs/images/mobile-settings.png" alt="移动端学校设置" width="320">
</p>
```

`mobile-settings.png` 是新增图片示例，使用前需自行上传。图下可补充简短图注。

## 5. 图片中的信息

优先使用演示账号和合成课表。真实截图公开前，请遮挡姓名、学号、账号、私密订阅链接、token、Cookie、认证二维码及其他个人信息。

完整订阅链接可以直接读取对应课表。密码框显示为圆点，也不代表页面其他区域没有秘密。

截图应来自实际界面。效果图或尚未实现的界面应在图注说明，不要把 CalDAV 占位页描述成已可用服务。

## 6. 添加完成后的整理

补齐图片后，可将主 README“界面预览”开头的预留说明替换成简单图注，或移除该说明。截图不必一次全部补齐，保留尚未启用的注释即可。

参考：[GitHub README 相对图片路径说明](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes)。
