#!/usr/bin/env python3
"""Read local VPN settings and supply one per-run FortiToken via a private PTY."""

import errno
import fcntl
import getpass
import json
import os
import pty
import re
import select
import signal
import subprocess
import sys
import termios
import time


PROFILE = "container-vpn"
SUPERVISOR = ["supervisorctl", "-c", "/etc/supervisor/conf.d/forticlient.conf"]


def load_config(path):
    with open(path) as stream:
        config = json.load(stream)
    if not isinstance(config, dict):
        raise ValueError("VPN 配置必须是 JSON 对象")
    for key in ("host", "username", "password"):
        value = config.get(key)
        if not isinstance(value, str) or not value or any(c in value for c in "\r\n\0"):
            raise ValueError(f"VPN 配置字段 {key} 必须是非空单行字符串")
    config.setdefault("port", 443)
    if type(config["port"]) is not int or not 1 <= config["port"] <= 65535:
        raise ValueError("VPN port 必须是 1–65535 之间的整数")
    return config


def redact(text, config, token=""):
    for value in (config["password"], token, config["username"], config["host"]):
        if value:
            text = text.replace(value, "<hidden>")
    return text


def read_token():
    if sys.stdin.isatty():
        token = getpass.getpass("本次 FortiToken（不保存）: ")
    else:
        token = sys.stdin.readline().rstrip("\r\n")
    if not token or len(token) > 256 or any(c in token for c in "\r\n\0"):
        raise ValueError("启动需要本次 FortiToken；不会读取或复用环境变量中的令牌")
    return token


def configure(config):
    result = subprocess.run(
        ["forticlient", "vpn", "edit", PROFILE],
        input=f'{config["host"]}\n{config["port"]}\n1\n3\n',
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=20,
    )
    if result.returncode or "DONE." not in result.stdout:
        raise RuntimeError("创建 VPN 配置失败：\n" + redact(result.stdout, config))


def connect(config, token, timeout=120):
    master, slave = pty.openpty()
    attributes = termios.tcgetattr(slave)
    attributes[3] &= ~termios.ECHO
    termios.tcsetattr(slave, termios.TCSANOW, attributes)
    process = None
    output = ""
    pending = ""
    password_sent = token_sent = False
    deadline = time.monotonic() + timeout
    try:
        process = subprocess.Popen(
            ["forticlient", "vpn", "connect", PROFILE, "-u", config["username"], "-p"],
            stdin=slave, stdout=slave, stderr=slave, start_new_session=True,
        )
        os.close(slave)
        slave = -1
        while time.monotonic() < deadline:
            if not select.select([master], [], [], 0.25)[0]:
                if process.poll() is not None:
                    break
                continue
            try:
                chunk = os.read(master, 8192)
            except OSError as error:
                if error.errno == errno.EIO:
                    break
                raise
            if not chunk:
                break
            text = chunk.decode(errors="replace")
            output = (output + text)[-16000:]
            pending = (pending + text)[-4000:]
            if re.search(r"(?i)(?:password|passwd)\s*:\s*$", pending):
                if password_sent:
                    raise RuntimeError("客户端重复要求密码，已停止；请检查配置后重新启动")
                os.write(master, (config["password"] + "\n").encode())
                password_sent = True
                pending = ""
                print("已从配置输入密码，等待 FortiToken 验证。", flush=True)
            elif re.search(r"(?i)(?:fortitoken|token|otp|verification code)\s*:\s*$", pending):
                if token_sent:
                    raise RuntimeError("客户端再次要求令牌，已停止；请用新的 FortiToken 重新启动")
                os.write(master, (token + "\n").encode())
                token_sent = True
                pending = ""
                print("已提交本次 FortiToken。", flush=True)
        else:
            raise RuntimeError("VPN 连接超时：\n" + redact(output, config, token))
        code = process.wait(timeout=5)
        if code:
            raise RuntimeError("VPN 认证失败：\n" + redact(output, config, token))
    except subprocess.SubprocessError:
        raise RuntimeError("VPN 客户端进程异常，已停止本次连接") from None
    finally:
        if slave != -1:
            os.close(slave)
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        os.close(master)


def vpn_status():
    result = subprocess.run(
        ["forticlient", "vpn", "status"], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=10,
    )
    match = re.search(r"(?m)^Status:\s*([^\r\n]+)", result.stdout)
    return match.group(1).strip() if result.returncode == 0 and match else "Unavailable"


def main():
    config = load_config("/config/vpn.json")
    # Only one login/monitor may control a container at a time.
    with open("/run/user/1000/vpn-session.lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("已有 VPN 启动会话，请先关闭它") from None
        for _ in range(30):
            ready = subprocess.run(
                ["forticlient", "vpn", "list"], stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=5,
            )
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("FortiClient 后台未就绪，请检查容器日志")
        if vpn_status() != "Not Running":
            raise RuntimeError("VPN 已在连接或运行，请先断开现有连接")
        configure(config)
        print("已载入 /config/vpn.json，主机、端口和账号已配置。", flush=True)
        token = read_token()
        attempted = False
        try:
            attempted = True
            connect(config, token)
            token = ""
            for _ in range(15):
                state = vpn_status()
                if state == "Connected":
                    break
                if state not in ("Connecting", "Connecting...", "Logging in", "Logging in..."):
                    raise RuntimeError("VPN 未连接，当前状态：" + state)
                time.sleep(1)
            else:
                raise RuntimeError("等待 VPN 连接就绪超时")
            subprocess.run(SUPERVISOR + ["start", "socks"], check=True, timeout=15)
            print("VPN 已连接；SOCKS5 已监听容器端口 1080。按 Ctrl+C 关闭。", flush=True)
            while vpn_status() == "Connected":
                time.sleep(1)
            raise RuntimeError("VPN 已断开，正在停止 SOCKS5；不会自动重连")
        finally:
            subprocess.run(SUPERVISOR + ["stop", "socks"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
            if attempted:
                subprocess.run(["forticlient", "vpn", "disconnect"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
