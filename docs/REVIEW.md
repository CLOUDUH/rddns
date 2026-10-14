# 代码审阅与验证记录

日期：2026-09-11。范围：本地下载的 CLOUDUH/rddns，新增 TP-LINK IPv4 Web / Docker 服务。

## 原实现的问题与处理

| 问题 | 原位置 | 新实现 |
| --- | --- | --- |
| 登录失败先读取 stok，可能 KeyError；返回 -1 仍可能被当作有效 IP | 原 run.py 的 login_router / get_ip / update_ip，可从 Git 历史查看 | 明确错误类型；严格 IPv4 校验；取址失败不调用 DNS |
| 多域名任意一个成功即写 IP 缓存，后续可能跳过失败域名 | 原 update_ip | 每域名单独报告，每轮重新核对服务商，不共用成功缓存 |
| IPv4 WAN 地址被 IPv6 更新路径复用 | 原 update_ip('6') | 新版只提供 A / IPv4，避免写入错误 AAAA |
| 网络请求无超时、路由器请求可能继承代理 | 原 requests.post 和旧 DNS HTTPSConnection | 有限连接/读超时、禁止重定向，路由器连接不继承代理 |
| 阿里云 HTTP 200 错误响应可能被当作成功，调试日志含签名参数 | dns/alidns.py | 独立客户端检查 API 成功字段，不输出原始密钥/请求/响应 |
| 原单次进程缓存与全局供应商配置不适合并发 Web 服务 | dns/、util/cache.py | 实例化配置、单调度器、配置锁、任务排队互斥 |
| 手工编辑 JSON、抓 rpwd，部署依赖老 Alpine/PyInstaller 和外部调度 | 原 README、Dockerfile、entrypoint.sh | 网页配置、自动读取固件编码常量、常驻 Waitress 和后台调度、Compose 持久化卷 |
| CI 仍自动推送 NewFuture 镜像/PyPI，且使用 Python 2 打包路径 | 原 workflows | 替换为测试/镜像 smoke test；可手动导出镜像 artifact，不发布到外部仓库 |

旧模块已从当前目录移除，历史版本保存在 Git 中；新入口是 rddns_web.app。没有把所有历史 DNS 服务商直接接入常驻服务，避免保留其未经验证的全局缓存及错误处理。

## 已完成验证

- 隔离 Python 虚拟环境中的 46 项 pytest 测试：鉴权与请求校验、密钥加密及不回显、原子保存和重载、丢失密钥保护、输入校验、非法/私有 IP、登录失败阻断、UPnP 来源约束、自动回退、仅测试取址不写 DNS、逐域名部分失败和下一轮恢复、调度器互斥、阿里云分页/成功字段/状态大小写、Cloudflare PATCH 与代理保护。
- Flask / requests / Waitress / cryptography / defusedxml 依赖在本地独立虚拟环境安装；未修改全局 Anaconda 包。生产 HTTP 入口用 Waitress 在本机启动成功。
- Compose 和 workflow YAML 可解析；Docker/Compose 的实际校验和构建已写入 CI，但本机没有 Docker，因此本轮未运行它们。
- 桌面和 390px 窄屏网页视觉检查；验证配置保存、真实取址状态自动刷新、缺少密钥时同步被阻断、Cloudflare 字段切换。
- 真实设备只读检查：192.168.1.1 首页标识 **TL-XDR3010**；公开 class.js 的 orgAuthPwd/securityEncode 使用 15 字符 salt 和 255 字符字符表，当前解析器成功识别，已人工核对 XOR 算法。
- 在当前 macOS 主机上调用 UPnP，且通过网页再次调用，均成功读取 **RFC1918 私有 WAN IPv4 地址**（已省略具体地址）。未提供或使用路由器管理密码，未更改 UPnP/端口映射/路由设置。

## 尚未验证及边界

1. 未进行真实 DNS 写入：尚未配置真实目标域名、服务商和密钥。供应商测试使用模拟 API 响应；成功状态含义为 API 确认，不承诺全网缓存已刷新。
2. 未进行 Docker 镜像构建或容器内实机取址。本地未安装 Docker，Linux host 网络方案仍须在部署主机验证。原生 macOS UPnP 成功不等于 Docker bridge SSDP 必然成功。
3. 未使用真实密码登录 TP-LINK；只读核对编码与免登录取址。国际版、RSA/AES 登录及其他 TP-LINK 协议不在本次适配范围。
4. 加密密钥与配置保存在同一受限数据卷；主机/卷完全失陷时不能靠此加密保护秘密。管理 HTTP Basic 应在可信局域网或 HTTPS/VPN 内使用。
5. 仅支持单进程单实例；活动日志在内存中保留最近 100 条。更新域名、服务商或凭据后会重置本轮状态。
6. 当前依赖采用版本范围；构建会解析范围内版本。本轮安装经国内镜像完成，未禁用 TLS 校验。

## API 参考

- UPnP WANIPConnection: https://upnp.org/specs/gw/UPnP-gw-WANIPConnection-v1-Service.pdf
- 阿里云记录查询（COMBINATION 是 RRKeyWord 等字段精确组合匹配模式）：https://help.aliyun.com/zh/dns/api-alidns-2015-01-09-describedomainrecords
- Cloudflare DNS Records：https://developers.cloudflare.com/api/resources/dns/subresources/records/
- Waitress / Flask 部署：https://flask.palletsprojects.com/en/stable/deploying/waitress/

## 2026-09-13 本地归档整理

移除旧 CLI、DNS/缓存工具、schema、Python 2/PyInstaller 打包与定时任务文件，保留当前 Web 服务、54 项测试、Docker/Portainer 部署配置、文档和完整 Git 历史。合并重复工作目录并清除虚拟环境、Python/pytest 缓存与本次开发临时数据。上述早期验证记录保留其当时的时间范围，不代表当前远程部署状态。

## 2026-10-14 页面访问与活动日志调整

按使用需求移除管理页面及 API 的 HTTP Basic 验证，保留浏览器写请求校验、加密配置和密钥不回显机制。最近活动区域改为最高 320px 的独立滚动列表，支持键盘滚动；相同活动数据不重复重建列表，新增日志时保持原阅读位置。

52 项 Python 测试通过，包含无认证读取/保存配置及旧数据卷兼容。隔离本地预览用 100 条模拟活动验证区域高度、独立滚动、两秒轮询和新增日志后的阅读位置，浏览器无脚本错误。容器 CI 的访问及持久化检查同步改为无需凭据。
