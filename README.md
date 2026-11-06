# FortiClient VPN-only + SOCKS5

使用用户提供的 `forticlient_vpn_7.4.3.5411_amd64.deb`，在 Ubuntu 24.04 容器内安装 FortiClient VPN-only。安装包位于 `installers/`，被 Git 忽略，不使用 Fortinet 8.0 apt 源。SHA-256：

```text
d2c0366decbf0b907fbf0d9306b8ac0b705d2d9cb4eb7b946ae06ce5388d4e5a
```

## 已验证的状态

- 普通用户不能使用 `dpkg` 安装，镜像构建时使用 root 安装。
- 容器默认用户和 CLI 为 `ubuntu`；官方 VPN 后台通过受限 sudo 命令以 root 运行。没有设置 root 密码。
- VPN-only 的 CLI 拒绝 root 用户，不能通过把整个操作切到 root 来解决。
- 后台需要 `SYS_PTRACE` 读取 CLI 调用进程的身份，另需 `/run/user/1000` 用户会话目录。未添加这些设置时分别出现本地鉴权失败和目录初始化失败。
- 普通用户的 `forticlient vpn list`、`forticlient vpn status` 已通过实测；已从 `vpn.json` 的真实服务器和端口创建 `container-vpn` 配置。
- **VPN 尚未连接。** 当前未实现启动时自动输入密码和一次性 FortiToken；SOCKS5 保持关闭。

## 构建与启动

需要 Docker、Docker Compose、上述 amd64 安装包及 TUN 设备。ARM 主机需要 Docker 的 amd64 模拟支持。

```sh
docker compose up -d --build
docker compose exec forticlient bash
```

Compose 使用独立项目名 `forticlient-vpn-only` 和独立数据卷，避免跨版本数据干扰。`restart: "no"` 禁止容器自动重启；后台进程也不自动重启。

`vpn.json` 以只读方式挂载至 `/config/vpn.json`，被 Git 和 Docker 构建上下文忽略。文件字段为 `host`、`port`（默认 443）、`username`、`password`；不要把 FortiToken 写入文件。当前创建配置时只使用主机和端口，不保存密码或令牌。修改 JSON 后不会自动更新客户端中的连接配置。

## 当前 CLI 用法

在容器的普通用户终端中执行：

```sh
forticlient vpn list
forticlient vpn edit container-vpn
forticlient vpn connect container-vpn -u <账号> -p
forticlient vpn status
forticlient vpn disconnect
```

`edit` 依次提示服务器、端口、认证方式和客户端证书类型。当前使用 `1.prompt` 认证，未配置客户端证书。`connect` 的 `-p` 表示交互输入密码。不要使用保存密码或自动连接选项；FortiToken 应在实际连接时输入，不写入镜像、环境变量或配置文件。

## SOCKS5

目标链路为：

```text
Clash → 宿主机 127.0.0.1:1081 → 容器 SOCKS5:1080 → FortiClient VPN → 目标网络
```

新项目默认使用宿主机 1081 端口，可通过 `SOCKS_PORT` 更改。SOCKS5 未连接 VPN 前不启动。当前尚未实现 VPN 断开时的流量阻断，不要在未验证路由时手动启用代理。代理仅支持 TCP，域名解析和目标路由也尚未通过实际 VPN 连接测试。

## 检查与停止

```sh
docker compose logs --tail 50
docker compose exec forticlient id
docker compose exec forticlient ps -eo user,pid,comm
docker compose exec forticlient forticlient vpn list
docker compose exec forticlient forticlient vpn status
docker compose stop
```

只有 `/usr/local/bin/start-forticlient-service` 这一条无参数命令可免密 sudo；未授予任意 root 命令权限。保留官方程序文件的 root 所有权。数据卷可能包含 VPN 配置，请妥善保护。
