# FortiClient VPN-only + SOCKS5

链路：`Clash → 宿主机 127.0.0.1:1081 → 容器 SOCKS5:1080 → FortiClient VPN → 目标网络`。

使用 `installers/forticlient_vpn_7.4.3.5411_amd64.deb`，在 Ubuntu 24.04 内以 root 安装。容器默认用户和 CLI 为 `ubuntu`，官方后台通过受限 sudo 以 root 运行。未设置 root 密码。

## 配置与启动

需要 Docker、Docker Compose、TUN 设备及上述安装包。ARM 主机需要 amd64 模拟支持。

在项目目录创建 `vpn.json`（已有配置可直接使用）：

```json
{
  "host": "你的 VPN 主机",
  "port": 443,
  "username": "你的账号",
  "password": "你的密码"
}
```

`port` 可省略，默认 `443`。不要把 FortiToken 放入配置文件。

```sh
chmod 600 vpn.json
./start-vpn
```

脚本先构建镜像，随后读取配置、创建或更新 `container-vpn`，提示输入本次 FortiToken（不回显），自动提交配置中的密码及本次令牌。确认 VPN 已连接后才启动 SOCKS5。

指定其他配置文件或宿主机端口：

```sh
VPN_CONFIG=/absolute/path/vpn.json SOCKS_PORT=1080 ./start-vpn
```

配置文件只读挂载到 `/config/vpn.json`，不打入镜像。默认配置和安装包被 Git 忽略；Docker 构建上下文仅包含安装和启动所需文件。自定义凭据文件也应放在 Git 仓库外。

FortiToken 仅从本次终端输入读取，不从环境变量、命令行参数或配置文件读取，也不保存。此启动方式使用前台临时容器和 `--rm`；退出后必须重新运行启动脚本并输入新的令牌。不要使用 `docker compose up -d` 启动交互会话。

认证失败、重复要求令牌或连接断开都会退出，不会自动重连。`restart: "no"` 禁止自动重启。启动脚本会停止本项目之前运行的服务容器以释放端口，保留数据卷。

## Clash 接入

默认 SOCKS5 只绑定宿主机回环地址，Clash 节点可配置为：

```yaml
proxies:
  - name: FortiClient
    type: socks5
    server: 127.0.0.1
    port: 1081
    udp: false
```

VPN 网关应在 Clash 中直连；需要访问的目标网络按你的规则使用此节点。若 Clash 本身也在容器中，需要改用它能访问的宿主机地址和端口绑定。

VPN 状态每秒检查一次，断开后停止 SOCKS5 并退出。此机制不是内核级流量阻断，无法保证断开瞬间没有流量绕行；SOCKS5 仅支持 TCP。目标路由和域名解析仍需实际连接验证。

## 检查与停止

前台按 `Ctrl+C` 停止，或在另一个终端执行：

```sh
docker exec -it forticlient-vpn-only-session bash
docker exec forticlient-vpn-only-session forticlient vpn status
docker stop forticlient-vpn-only-session
```

Compose 项目名为 `forticlient-vpn-only`，官方客户端数据保存在 `vpn-only-data` 卷。手工 `docker exec` 不继承启动时的 D-Bus 会话环境，可能出现系统密钥库提示；自动登录流程运行在 D-Bus 会话内，不使用保存密码选项。

仅 `/usr/local/bin/start-forticlient-service` 这一条无参数命令可免密 sudo。`NET_ADMIN` 和 TUN 用于 VPN，`SYS_PTRACE` 用于官方后台识别非 root CLI 的调用进程。

## 验证范围

已验证 VPN-only 安装、非 root CLI 配合 root 后台，以及真实服务器连接到 FortiToken 提示的流程。自动输入与退出行为使用模拟 CLI 验证；完整 VPN 登录和目标网络访问需要启动时输入有效 FortiToken 后实测。

```sh
python3 -m unittest discover -s tests -v
```
