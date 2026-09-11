"""Read a configured TP-LINK gateway; never substitute a public-IP service."""
import ipaddress
import re
import socket
import time
from urllib.parse import urljoin, urlsplit

import requests
from defusedxml import ElementTree as ET


class RouterError(ValueError):
    pass


def valid_ip(value):
    if not isinstance(value, str):
        raise RouterError("路由器没有返回有效 IPv4 地址")
    try:
        ip = ipaddress.IPv4Address(value)
    except (ValueError, TypeError, ipaddress.AddressValueError):
        raise RouterError("路由器没有返回有效 IPv4 地址") from None
    if ip.is_reserved or ip in ipaddress.ip_network('0.0.0.0/8') or ip.is_unspecified or ip.is_loopback or ip.is_multicast or int(ip) == 0xffffffff or ip.is_link_local:
        raise RouterError("WAN 地址尚未就绪或不可用")
    return str(ip)  # RFC1918 and CGNAT addresses are intentionally accepted.


def router_url(value):
    value = value.strip()
    if '://' not in value:
        value = 'http://' + value
    try:
        parts = urlsplit(value)
        addr = ipaddress.IPv4Address(parts.hostname or '')
        port = parts.port
    except ValueError:
        raise RouterError("路由器地址须为 IPv4 地址，可带 http(s) 和端口") from None
    if parts.scheme not in ('http', 'https') or parts.username or parts.password or parts.query or parts.fragment or parts.path not in ('', '/'):
        raise RouterError("路由器地址格式不正确")
    if not any(addr in net for net in map(ipaddress.ip_network, ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16','100.64.0.0/10'))):
        raise RouterError("请使用局域网或 CGNAT 范围的路由器 IPv4 地址")
    return f'{parts.scheme}://{addr}' + (f':{port}' if port else '')


def same_router_url(base, value):
    url = urljoin(base + '/', value)
    p = urlsplit(url)
    if p.scheme not in ('http', 'https') or p.hostname != urlsplit(base).hostname or p.username or p.password:
        raise RouterError("忽略指向其他设备的路由器接口")
    return url


def fetch(session, method, url, **kwargs):
    r = session.request(method, url, timeout=(3, 6), allow_redirects=False, **kwargs)
    if not 200 <= r.status_code < 300:
        raise RouterError(f"路由器 HTTP 请求失败（{r.status_code}）")
    if len(r.content) > 2_000_000:
        raise RouterError("路由器响应过大")
    return r


def encode_password(password, salt, alphabet):
    # Matches the XOR/substitution routine used by supported Chinese firmware.
    # JavaScript charCodeAt operates on UTF-16 code units, not Unicode codepoints.
    def units(s):
        b = s.encode('utf-16-le')
        return [int.from_bytes(b[i:i+2], 'little') for i in range(0, len(b), 2)]
    a, b = units(password), units(salt)
    return ''.join(alphabet[((a[i] if i < len(a) else 187) ^
                             (b[i] if i < len(b) else 187)) % len(alphabet)]
                   for i in range(max(len(a), len(b))))


def password_constants(text):
    # Read constants only; never execute JavaScript supplied by the router.
    candidates = re.findall(r'securityEncode\s*\(([^()]{1,1000})\)', text)
    candidates += re.findall(r'orgAuthPwd\s*[:=]\s*function\s*\([^)]*\)\s*\{([^}]{1,2000})\}', text)
    for block in candidates:
        strings = re.findall(r'''["']([A-Za-z0-9]{8,})["']''', block)
        if len(strings) == 2:
            salt, alphabet = sorted(strings, key=len)
            if len(alphabet) >= 32 and len(salt) < len(alphabet):
                return salt, alphabet
    raise RouterError("未识别此固件的密码编码方式；请使用高级选项的旧版 rpwd，或提供型号以适配")


def encoded_from_firmware(session, base, password):
    html = fetch(session, 'GET', base + '/').text
    texts = [html]
    sources = re.findall(r'''<script\b[^>]*\bsrc=["']([^"']+)["']''', html, re.I)
    for src in sources[:8]:
        try:
            texts.append(fetch(session, 'GET', same_router_url(base, src)).text)
        except (RouterError, requests.RequestException):
            continue
    for text in texts:
        try:
            return encode_password(password, *password_constants(text))
        except RouterError:
            continue
    raise RouterError("无法自动识别此 TP-LINK 固件的密码编码；可在高级选项使用原 rpwd")


def login_ip(session, cfg):
    base = cfg['router_url']
    if not cfg['router_password']:
        raise RouterError("UPnP 不可用；请填写路由器密码或选择仅 UPnP")
    password = cfg['router_password']
    if cfg['password_mode'] == 'plain':
        password = encoded_from_firmware(session, base, password)
    # This specific /stok=/ds firmware authenticates with password only.
    data = fetch(session, 'POST', base + '/', json={'method':'do','login':{'password': password}}).json()
    if data.get('error_code') != 0:
        raise RouterError("TP-LINK 登录失败，请检查密码、编码模式和固件；本次不重复登录")
    stok = data.get('stok', '')
    if not isinstance(stok, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', stok):
        raise RouterError("路由器未返回有效登录会话")
    result = fetch(session, 'POST', base + '/stok=' + stok + '/ds',
                   json={'method':'get','network':{'name':'wan_status'}}).json()
    if result.get('error_code', 0) != 0:
        raise RouterError("路由器拒绝读取 WAN 状态")
    try:
        return valid_ip(result['network']['wan_status']['ipaddr'])
    except (KeyError, TypeError):
        raise RouterError("当前固件不支持 network.wan_status.ipaddr 接口") from None


def upnp_ip(session, base):
    host = urlsplit(base).hostname
    message = ('M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n'
               'MAN: "ssdp:discover"\r\nMX: 1\r\nST: upnp:rootdevice\r\n\r\n').encode()
    locations = set()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(0.4)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.sendto(message, (host, 1900))
        sock.sendto(message, ('239.255.255.250', 1900))
        deadline = time.monotonic() + 2.5
        while time.monotonic() < deadline and len(locations) < 8:
            try:
                data, peer = sock.recvfrom(8192)
            except socket.timeout:
                continue
            if peer[0] != host:
                continue
            m = re.search(r'^location:\s*(\S+)', data.decode(errors='ignore'), re.I | re.M)
            if m:
                locations.add(same_router_url(base, m[1]))
    for location in locations:
        try:
            root = ET.fromstring(fetch(session, 'GET', location).content)
            for service in root.findall('.//{*}service'):
                kind = service.findtext('{*}serviceType', '')
                if not re.fullmatch(r'urn:schemas-upnp-org:service:WAN(?:IP|PPP)Connection:[12]', kind):
                    continue
                control = service.findtext('{*}controlURL', '')
                if not control:
                    continue
                url_base = root.findtext('{*}URLBase') or location
                url = same_router_url(base, urljoin(url_base, control))
                body = ('<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
                        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
                        f'<u:GetExternalIPAddress xmlns:u="{kind}"/></s:Body></s:Envelope>')
                reply = fetch(session, 'POST', url, data=body.encode(), headers={
                    'Content-Type':'text/xml; charset="utf-8"', 'SOAPAction':f'"{kind}#GetExternalIPAddress"'})
                return valid_ip(ET.fromstring(reply.content).findtext('.//{*}NewExternalIPAddress'))
        except (RouterError, requests.RequestException, ET.ParseError):
            continue
    raise RouterError("指定路由器未提供可用的 UPnP WAN 地址；检查 UPnP 开关及 Docker 网络")


def get_wan_ip(cfg):
    with requests.Session() as session:
        session.trust_env = False
        if cfg['router_method'] in ('auto', 'upnp'):
            try:
                return upnp_ip(session, cfg['router_url']), 'UPnP（免登录）'
            except (RouterError, OSError, requests.RequestException):
                if cfg['router_method'] == 'upnp':
                    raise RouterError("UPnP 取址失败，请检查路由器设置和容器网络") from None
        try:
            return login_ip(session, cfg), 'TP-LINK 登录接口'
        except (requests.RequestException, ValueError) as exc:
            if isinstance(exc, RouterError):
                raise
            raise RouterError("路由器连接失败或返回非 JSON 数据，请核对地址和固件") from None
