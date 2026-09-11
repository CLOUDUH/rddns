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

公开仓库无需开启 Git 身份验证。Environment variables **只需一项**：

```text
PORT=18080
```

不填时端口为 8080。点击 **Deploy the stack**，Portainer 会拉取源码并构建镜像。构建默认使用清华 Python 镜像，失败自动回退 PyPI，无需配置包源变量。Docker 主机仍需能访问 GitHub、Docker Hub 和至少一个 Python 包源。

启动后访问 `http://虚拟机或NAS的IP:18080`，默认用户名和密码均为 **admin**，容器名为 **rddns**。服务监听 `0.0.0.0`，无需提供 `NAS_IP`。主机 IP 由操作系统管理，浏览器通过该地址访问网页；**需要读取 WAN 的路由器地址**在网页中填写。

此配置使用 Linux host 网络，无需端口映射。Docker Swarm 不支持这里的源码构建方式；本配置适用于 Docker Standalone。官方入口说明：[Portainer Git repository stacks](https://docs.portainer.io/user/docker/stacks/add#option-3-git-repository)。

### 更新已有 Portainer Stack

1. 打开原来的 `rddns` Stack，保持分支 `refs/heads/master` 和 Compose 路径 `compose.portainer.yaml`。
2. 在 **Edit Git settings / Environment variables** 中删除旧的 `RDDNS_PORT`、`NAS_IP`、`RDDNS_ADMIN_PASSWORD`、`RDDNS_PIP_INDEX_URL` 等 RDDNS 部署变量，只保留 `PORT=18080`。Portainer 自己的 HTTP_PROXY/HTTPS_PROXY 属于另一个容器，不要删除。
3. 保存设置，执行 **Pull and redeploy → Update**，等待源码重新构建与容器启动。
4. 继续访问原来的主机地址和端口，使用 `admin / admin` 登录。浏览器若缓存旧凭据，可用无痕窗口重新登录。

保持原 Stack 和数据卷，已保存的路由器与 DNS 配置会保留。旧 `admin-password` 文件不会再用于管理登录，也无需手工删除。旧 `RDDNS_*` 环境变量不再控制本服务。

## Docker 部署

将本目录复制到可访问路由器的 Docker 主机：

```sh
cp .env.example .env
# .env 中只需 PORT=18080
docker compose up -d --build
```

默认 Compose 使用 bridge 网络，通过主机同名端口访问。Linux/NAS 如需改善 UPnP 发现，可改用 host 配置：

```sh
docker compose down
docker compose -f compose.host.yaml up -d --build
```

两份配置使用相同数据卷和 `PORT` 设置，不要叠加使用。host 网络模式下，所选端口必须未被主机其他服务占用。

### 网页配置

1. 填写路由器地址，例如 `http://192.168.1.1`，取址方式选“自动”或“仅 UPnP”。
2. 登录取址时填写管理密码；仅 UPnP 可留空。保存后点击“测试取址”，确认返回的是目标 WAN 地址，此操作不会修改 DNS。
3. 填写阿里云或 Cloudflare 的域名与密钥，保存后点击“立即同步”。
4. 成功后勾选“启用自动同步”并保存。

自动同步默认关闭。任务运行或排队时不能保存配置。最小检查间隔 60 秒，默认 300 秒。

### UPnP 与网络

UPnP 只读取指定路由器的 WAN IP，不创建端口映射；路由器必须已支持并开启服务。Docker bridge 不一定能收到 SSDP 响应，自动模式会回退登录；Linux host 配置有利于发现。登录取址不依赖 UPnP，但容器需要能访问路由器管理端口。

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

`/data` 使用持久化命名卷，含 `config.enc`（加密配置）、`encryption.key`（解密密钥）。密钥文件权限为 0600。备份时应整体备份数据卷；能同时读取加密文件和密钥的人仍可解密配置，因此加密不能替代主机权限控制。

密钥不通过 API 回显，密码框留空保留旧值；输入新值保存可替换。不要执行 `docker compose down -v`，这会删除配置卷。最近活动和运行状态只保留在内存，重启后重新检查；配置与启用状态会恢复。

网页登录采用 HTTP Basic。局域网 HTTP 不提供传输加密；远程访问应通过 HTTPS 反向代理或可信 VPN，不要直接把 8080 暴露到公网。反向代理必须保留 Authorization 头。浏览器可能缓存登录凭据，需要退出时关闭对应浏览器会话。当前版本的管理登录为 `admin / admin`。

## 本地运行与测试

要求 Python 3.12（容器基线；测试也可在兼容的较新 Python 运行）：

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
PORT=18080 .venv/bin/python run.py
# 另一个终端
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

本地运行默认将数据保存在当前目录的 `data/`；容器固定使用 `/data`。

新服务入口为 `python -m rddns_web.app` 或 `python run.py`。不要开启多个 worker / 多个实例共享同一数据卷；每个进程包含一个独立调度器。

原 `run.py` 保存于 `legacy/run.py` 供查阅，旧 `dns/`、`util/` 和打包文件保留作历史参考，不会进入新 Docker 镜像。新版不读取旧 `config.json`，请在网页迁移其路由器、rpwd 和 DNS 配置；旧 CLI 参数及旧 cron/systemd 启动方式不再适用。旧服务商中除阿里云和 Cloudflare 之外的后端尚未迁移。

CI 执行 Python 测试、Compose 校验、镜像构建和容器重启持久化测试；手动打包 workflow 仅输出镜像文件，不推送镜像仓库。代码审阅结果及验证边界见 [docs/REVIEW.md](docs/REVIEW.md)。

## 接口依据

- [UPnP WANIPConnection 标准](https://upnp.org/specs/gw/UPnP-gw-WANIPConnection-v1-Service.pdf)
- [TP-LINK UPnP 设置说明](https://www.tp-link.com/ca/support/faq/4624/)
- [阿里云 DescribeDomainRecords](https://help.aliyun.com/zh/dns/api-alidns-2015-01-09-describedomainrecords)
- [Cloudflare DNS Records API](https://developers.cloudflare.com/api/resources/dns/subresources/records/)

基于 [CLOUDUH/rddns](https://github.com/CLOUDUH/rddns) / [NewFuture/DDNS](https://github.com/NewFuture/DDNS) 改进，沿用 MIT License。
