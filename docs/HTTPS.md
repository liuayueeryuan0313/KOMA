# HTTPS 与证书

课表应用无需内置证书申请模块。应用负责账户、学校同步和 ICS，TLS 交给部署层的反向代理管理。

- 本机测试：使用 `http://localhost:8080`，不必申请公网证书。
- 公网域名部署：可使用 Caddy 自动管理域名证书和续期，域名解析和验证条件按部署方式配置，应用设置 `PUBLIC_URL=https://实际域名` 及 `COOKIE_SECURE=true`。
- 内网部署：若使用内部 CA，访问设备需要信任该 CA；不要通过忽略浏览器证书警告代替正确信任配置。内网域名也可按实际 DNS 条件使用可验证的公开域名证书方案。

目前没有配置公网域名、开放防火墙端口或申请证书。Windows 本机 Compose 只监听回环地址，适合先验证容器运行。

参考：[Caddy Automatic HTTPS](https://caddyserver.com/docs/automatic-https)。
