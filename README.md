# RDDNS · TP-LINK WAN 动态解析

通过网页配置 TP-LINK 路由器、DNS 密钥及域名，定时将路由器的 **WAN IPv4** 同步到 DNS A 记录。保留二级网络中的 RFC1918 / CGNAT 地址，不会用公网查 IP 网站替换它。

- 取址：自动优先 UPnP（免登录），失败后使用原仓库的国内版 TP-LINK `stok / ds` 接口。
- 配置：路由器地址、账户记录、普通密码或旧版 `rpwd`；阿里云 DNS / Cloudflare。
- 状态：WAN IP、取址来源、下次检查、最近成功、逐域名结果、最近 100 条活动，每 2 秒刷新。
- 控制：保存配置、仅测试取址、立即同步、启用或暂停自动同步。
- 运行：单进程后台调度、请求超时、配置加密与原子落盘、管理登录、非 root 容器、健康检查。

## Portainer 从 Git URL 部署

适用于 Linux / NAS 的 Docker Standalone 环境。在 Portainer 选择对应环境，打开 **Stacks → Add stack → Repository / Git repository**，填写：

| 字段 | 值 |
| --- | --- |
| Name | `rddns` |
| Repository URL | `https://github.com/CLOUDUH/rddns` |
| Repository reference | `refs/heads/master` |
| Compose path | `compose.portainer.yaml` |

公开仓库无需开启 Git 身份验证。在 Environment variables 中添加 `NAS_IP`，值为 **Docker 主机的局域网 IPv4 地址**（不是路由器地址），例如 `192.168.1.20`。

可选变量：`RDDNS_PORT`（默认 8080，端口冲突可改为 18080）、`RDDNS_ADMIN_PASSWORD`（默认 `admin`；其他自定义密码至少 12 字符）、`RDDNS_PIP_INDEX_URL`（PyPI 下载失败时可设为 `https://pypi.tuna.tsinghua.edu.cn/simple`）。

点击 **Deploy the stack** 后，Portainer 会拉取仓库并在目标 Docker 环境构建镜像。首次构建需要主机能够访问 GitHub、Docker Hub 和 Python 包源。此方式不需要预先上传本地镜像；不要只把 Compose 内容粘贴到 Web editor，因为构建需要同仓库的源码。

启动后访问 `http://NAS_IP:RDDNS_PORT`，默认用户名和密码均为 `admin`，容器名称固定为 `rddns`。此配置使用 host 网络，无需端口映射；仅监听指定 NAS 地址。先测试取址，再填写 DNS 配置并启用同步。

更新时在同一个 Stack 内拉取仓库并重新构建/部署，保留其数据卷。暂不适用于 Swarm：Swarm 不执行 Compose 的 `build`。Portainer 版本若不支持从 Git 构建，使用下方 Docker 构建流程后以本地镜像部署。

官方入口说明：[Portainer Git repository stacks](https://docs.portainer.io/user/docker/stacks/add#option-3-git-repository)。

### 更新已有 Portainer Stack

进入原来的 `rddns` Stack，保持 Git 分支 `refs/heads/master` 和 Compose 路径 `compose.portainer.yaml`。在 **Edit Git settings / Environment variables** 中将 `RDDNS_ADMIN_PASSWORD` 设为 `admin`，保留现有 `NAS_IP`、`RDDNS_PORT` 和包源变量，然后 **Pull and redeploy → Update**。这是源码构建项目，无需开启从镜像仓库重新拉取应用镜像的选项。

本次更新会把容器名称从 Compose 自动生成的名称改为 `rddns`；Stack 名称和数据卷名称不变。更新过程会短暂中断服务，不要删除数据卷。若已有其他独立容器占用了 `rddns` 名称，先确认其用途再处理冲突。

Compose 默认显式传入 `RDDNS_ADMIN_PASSWORD=admin`，优先于旧数据卷的随机密码文件，因此保留数据卷也可以使用新默认密码；若你已在 Stack 中配置其他密码，那个值仍然优先。直接运行 Python 且不设置此变量时，保留已有本地密码文件，新安装才使用 `admin`。

## Docker 部署

在可访问路由器的 NAS / Linux / Docker 主机上，将本目录复制过去，然后：

```sh
cp .env.example .env
# 若需要局域网访问，把 .env 中 RDDNS_BIND_IP 改成 NAS 的局域网 IP。
# 默认账户 admin / admin；可通过 RDDNS_ADMIN_PASSWORD 指定至少 12 字符的自定义密码。
docker compose up -d --build
docker compose logs rddns
```

浏览器打开 `http://部署机器的IP:8080`，默认用户名和密码均为 **admin**。若设置了 `RDDNS_ADMIN_PASSWORD`，以该变量为准。

默认 `127.0.0.1` 仅允许部署机器本地访问，地址为 `http://127.0.0.1:8080`。局域网访问请在 `.env` 设置该主机实际局域网 IP 后重新执行 `docker compose up -d`。

1. 填写路由器地址，例如 `http://192.168.1.1`。取址方式选“自动”。
2. 填写路由器密码，或选择“仅 UPnP”免密码读取。保存配置后点击“测试取址”，确认 IP 是目标 WAN 地址；此操作不会修改 DNS。
3. 填写 DNS 密钥、完整域名和 TTL，保存后点击“立即同步”。
4. 确认域名结果后，勾选“启用自动同步”并保存。

如果构建时 PyPI 下载失败，可在 `.env` 添加 `RDDNS_PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple` 后重新构建。

首次配置自动同步默认关闭。修改中的配置不会用于测试或同步，必须先保存；任务运行或排队时禁止保存，防止新旧配置混用。最小检查间隔 60 秒，默认 300 秒。

### UPnP 与网络

UPnP 使用 SSDP 发现 + `GetExternalIPAddress`，仅接受所填路由器 IPv4 发出的发现响应，且描述文档与控制接口必须仍指向该路由器。只读取 IP，不创建端口映射。路由器须已开启并支持此服务。

Docker bridge 网络不一定能收到 SSDP 响应；自动模式会回退登录。Linux / NAS 上可以改用独立的 host 网络配置（不要与默认文件叠加）：

```sh
docker compose down
docker compose -f compose.host.yaml up -d --build
```

两份 Compose 使用相同命名数据卷。host 模式仍使用 `.env` 中的 `RDDNS_BIND_IP`；在 Linux/NAS 使用，不假设 Docker Desktop 的 host 网络功能可用。登录取址通常不需要 host 网络，但容器须能连到路由器管理端口。

### TP-LINK 固件范围

本版登录适配的是原仓库采用的 `POST /` → `stok` → `/stok=.../ds` → `network.wan_status.ipaddr` 接口，**不是所有 TP-LINK 型号**。该接口仅使用密码，网页的账户字段只保存作配置记录，不会被发送。需要用户名认证、RSA/AES 登录、国际版 Archer 或其他接口的固件暂未实现。

普通密码模式尝试从路由器首页及最多 8 个同设备脚本中读取 `orgAuthPwd / securityEncode` 的常量，按对应 XOR/字符表算法编码；不执行路由器 JavaScript。常量无法识别时会明确报错，不会猜测或重试其他登录协议。高级选项“已编码 rpwd”可直接使用原 `config.json` 的 `rpwd`。请勿把普通密码填入该模式。

UPnP 是固件支持时的免登录途径，不能保证所有型号可用。2026-09-11 已在用户的 TL-XDR3010 上实测 UPnP 免登录取址成功，并核对了固件编码常量及算法。尚未测试真实密码登录，也未使用真实密钥更新 DNS。

### DNS 配置

| 服务商 | 网页参数 | 所需操作 |
| --- | --- | --- |
| 阿里云 DNS | 主域名（如 `example.com`）、AccessKey ID / Secret、完整域名 | `DescribeDomainRecords`、`AddDomainRecord`、`UpdateDomainRecord` |
| Cloudflare | Zone ID、API Token、完整域名 | 对该 Zone 的 DNS 记录读取和编辑权限 |

阿里云一份配置管理一个主域名下最多 20 个域名；填写完整域名即可处理 `@` 根记录。Cloudflare 使用指定 Zone ID，无需账户 Email 或 Global API Key，记录必须为 **DNS only**。TTL 默认 600 秒；服务商套餐可能规定更高下限，若拒绝请求请在服务商控制台核对。

每轮都查询服务商当前记录，IP 与 TTL 一致则不写；记录不存在则创建；存在唯一 A 记录则更新；同名多条记录时停止，避免误改分线路/多地址记录。阿里云保留原解析线路；Cloudflare PATCH 保留备注等其他属性，不会擅自关闭已开启的代理。

“同步成功”表示服务商 API 确认更新或当前记录已一致，**不表示全网递归 DNS 缓存已经刷新**。DDNS 不提供内网穿透，私有地址仍要求访问端具备可达路由。

## 数据与管理访问

`/data` 使用持久化命名卷，含 `config.enc`（加密配置）、`encryption.key`（解密密钥）、`admin-password`（未显式设置密码变量时使用的本地密码文件）。密钥文件权限为 0600。备份时应整体备份数据卷；能同时读取加密文件和密钥的人仍可解密配置，因此加密不能替代主机权限控制。

密钥不通过 API 回显，密码框留空保留旧值；输入新值保存可替换。不要执行 `docker compose down -v`，这会删除配置卷。最近活动和运行状态只保留在内存，重启后重新检查；配置与启用状态会恢复。

网页登录采用 HTTP Basic。局域网 HTTP 不提供传输加密；远程访问应通过 HTTPS 反向代理或可信 VPN，不要直接把 8080 暴露到公网。反向代理必须保留 Authorization 头。浏览器可能缓存登录凭据，需要退出时关闭对应浏览器会话。可通过修改 `.env` 中管理密码并重建容器轮换凭据。

## 本地运行与测试

要求 Python 3.12（容器基线；测试也可在兼容的较新 Python 运行）：

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
RDDNS_HOST=127.0.0.1 .venv/bin/python run.py
# 另一个终端
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

新服务入口为 `python -m rddns_web.app` 或 `python run.py`。不要开启多个 worker / 多个实例共享同一数据卷；每个进程包含一个独立调度器。

原 `run.py` 保存于 `legacy/run.py` 供查阅，旧 `dns/`、`util/` 和打包文件保留作历史参考，不会进入新 Docker 镜像。新版不读取旧 `config.json`，请在网页迁移其路由器、rpwd 和 DNS 配置；旧 CLI 参数及旧 cron/systemd 启动方式不再适用。旧服务商中除阿里云和 Cloudflare 之外的后端尚未迁移。

CI 执行 Python 测试、Compose 校验、镜像构建和容器重启持久化测试；手动打包 workflow 仅输出镜像文件，不推送镜像仓库。代码审阅结果及验证边界见 [docs/REVIEW.md](docs/REVIEW.md)。

## 接口依据

- [UPnP WANIPConnection 标准](https://upnp.org/specs/gw/UPnP-gw-WANIPConnection-v1-Service.pdf)
- [TP-LINK UPnP 设置说明](https://www.tp-link.com/ca/support/faq/4624/)
- [阿里云 DescribeDomainRecords](https://help.aliyun.com/zh/dns/api-alidns-2015-01-09-describedomainrecords)
- [Cloudflare DNS Records API](https://developers.cloudflare.com/api/resources/dns/subresources/records/)

基于 [CLOUDUH/rddns](https://github.com/CLOUDUH/rddns) / [NewFuture/DDNS](https://github.com/NewFuture/DDNS) 改进，沿用 MIT License。
