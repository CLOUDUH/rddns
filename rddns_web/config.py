import copy
import json
import os
import re
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet
from .router import router_url

DEFAULTS = dict(router_url='http://192.168.1.1', router_username='admin', router_password='',
                router_method='auto', password_mode='plain', provider='alidns', zone='', zone_id='',
                access_id='', access_secret='', domains=[], ttl=600, interval=300, enabled=False)
SECRETS = ('router_password', 'access_secret', 'access_id')


def atomic_write(path, data):
    path = Path(path)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def domain_name(value):
    if not isinstance(value, str):
        raise ValueError('域名必须为字符串')
    try:
        value = value.strip().rstrip('.').encode('idna').decode().lower()
    except UnicodeError:
        raise ValueError('域名格式无效') from None
    if len(value) > 253 or '.' not in value or any(
        not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in value.split('.')):
        raise ValueError('请输入完整域名，例如 home.example.com')
    return value


def validate(payload, old):
    if not isinstance(payload, dict) or set(payload) - set(DEFAULTS):
        raise ValueError('配置字段不正确')
    cfg = copy.deepcopy(old)
    cfg.update(payload)
    for key in SECRETS:
        if payload.get(key) == '':
            cfg[key] = old[key]  # Blank means keep, never echo stored credentials.
    if cfg['provider'] != old['provider']:
        cfg['access_id'] = payload.get('access_id', '')
        cfg['access_secret'] = payload.get('access_secret', '')
    for key in DEFAULTS:
        if isinstance(DEFAULTS[key], str) and (not isinstance(cfg[key], str) or len(cfg[key]) > 2048):
            raise ValueError('配置文本格式或长度不正确')
    cfg['router_url'] = router_url(cfg['router_url'])
    if cfg['router_method'] not in ('auto','upnp','login') or cfg['password_mode'] not in ('plain','encoded'):
        raise ValueError('取址或密码模式无效')
    if cfg['provider'] not in ('alidns','cloudflare'):
        raise ValueError('暂支持阿里云和 Cloudflare')
    for key, lower, upper in [('interval',60,86400),('ttl',60,86400)]:
        if type(cfg[key]) is not int or not lower <= cfg[key] <= upper:
            raise ValueError(f'{key} 应为 {lower}–{upper} 的整数秒数')
    if type(cfg['enabled']) is not bool:
        raise ValueError('启用状态必须为布尔值')
    domains = cfg['domains']
    if not isinstance(domains, list) or len(domains) > 20:
        raise ValueError('最多配置 20 个域名')
    cfg['domains'] = list(dict.fromkeys(domain_name(x) for x in domains))
    if cfg['zone']:
        cfg['zone'] = domain_name(cfg['zone'])
    if cfg['zone_id'] and not re.fullmatch('[a-fA-F0-9]{32}', cfg['zone_id']):
        raise ValueError('Cloudflare Zone ID 应为 32 位十六进制字符串')
    if cfg['provider'] == 'alidns' and cfg['domains']:
        if not cfg['zone'] or any(d != cfg['zone'] and not d.endswith('.' + cfg['zone']) for d in cfg['domains']):
            raise ValueError('所有域名必须属于填写的阿里云主域名')
    if cfg['enabled']:
        ready(cfg)
    return cfg


def ready(cfg):
    if not cfg['domains'] or not cfg['access_secret']:
        raise ValueError('请先配置域名和 DNS 密钥')
    if cfg['provider'] == 'alidns' and (not cfg['zone'] or not cfg['access_id']):
        raise ValueError('请填写阿里云主域名和 AccessKey ID')
    if cfg['provider'] == 'cloudflare' and not cfg['zone_id']:
        raise ValueError('请填写 Cloudflare Zone ID')


class Store:
    def __init__(self, directory):
        self.path = Path(directory)
        self.path.mkdir(parents=True, exist_ok=True, mode=0o700)
        key = self.path / 'encryption.key'
        if not key.exists():
            if (self.path / 'config.enc').exists():
                raise ValueError('配置解密密钥缺失，请恢复完整数据卷备份')
            atomic_write(key, Fernet.generate_key())
        self.cipher = Fernet(key.read_bytes())
        self.file = self.path / 'config.enc'
        self.config = copy.deepcopy(DEFAULTS)
        if self.file.exists():
            self.config = validate(json.loads(self.cipher.decrypt(self.file.read_bytes())), DEFAULTS)

    def save(self, payload):
        cfg = validate(payload, self.config)
        atomic_write(self.file, self.cipher.encrypt(json.dumps(cfg).encode()))
        self.config = cfg

    def public(self):
        result = copy.deepcopy(self.config)
        for key in SECRETS:
            result[key] = ''
            result[key + '_set'] = bool(self.config[key])
        return result
