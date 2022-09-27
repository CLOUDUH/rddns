#!/usr/bin/env python
# -*- coding:utf-8 -*-
"""
DDNS
@author: New Future
@modified: rufengsuixing
"""
from __future__ import print_function
from time import ctime
from os import path, environ, name as os_name
from tempfile import gettempdir
from logging import DEBUG, basicConfig, info, warning, error, debug
from subprocess import check_output

import sys
import requests

from util import ip
from util.cache import Cache
from util.config import init_config, get_config

__version__ = "${BUILD_VERSION}@${BUILD_DATE}"  # CI 时会被Tag替换
__description__ = "automatically update DNS records to dynamic local IP [自动更新DNS记录指向本地IP]"
__doc__ = """
ddns[%s]
(i) homepage or docs [文档主页]: https://ddns.newfuture.cc/
(?) issues or bugs [问题和帮助]: https://github.com/NewFuture/DDNS/issues
Copyright (c) New Future (MIT License)
""" % (__version__)

environ["DDNS_VERSION"] = "${BUILD_VERSION}"

if getattr(sys, 'frozen', False):
    # https://github.com/pyinstaller/pyinstaller/wiki/Recipe-OpenSSL-Certificate
    environ['SSL_CERT_FILE'] = path.join(
        getattr(sys, '_MEIPASS'), 'lib', 'cert.pem')

CACHE_FILE = path.join(gettempdir(), 'ddns.cache')

def login_router(url, pwd):
    
    request_body = '{"method":"do","login":{"password":"'+pwd+'"}}'
    header = {"Content-Type": "application/json"}
    res = requests.post(url, data=request_body, headers=header)
    res = res.json()
    code, stok = int(res["error_code"]), res["stok"]

    if(code == 0):
        # print("Router login successfully: {}".format(url))
        return stok
    else:
        print("Can't get stok")
        return -1

def request_wan_ip(url, stok):
    if(stok != -1):
        url = "{}/stok={}/ds".format(url, stok)
        request_body = '''{
            "network": {"name": "wan_status"},
            "cloud_config": {"name": ["new_firmware", "device_status", "bind"]},
            "wireless": {"name": ["wlan_wds_2g", "wlan_wds_5g"]},
            "method": "get"
        }'''
        header = {"Content-Type": "application/json"}
        res = requests.post(url, data=request_body, headers=header)
        res = res.json()
        ip = res['network']['wan_status']['ipaddr']
        # print("Get ip address successfully: {}".format(ip))
        return ip
    else:
        print("Can't get ip address")
        return -1

def get_ip():
    url = get_config('router') 
    pwd = get_config('rpwd') 

    stok = login_router(url, pwd)
    value = request_wan_ip(url, stok)

    return value

def change_dns_record(dns, proxy_list, **kw):
    for proxy in proxy_list:
        if not proxy or (proxy.upper() in ['DIRECT', 'NONE']):
            dns.PROXY = None
        else:
            dns.PROXY = proxy
        record_type, domain = kw['record_type'], kw['domain']
        print('\n%s(%s) ==> %s [via %s]' %
              (domain, record_type, kw['ip'], proxy))
        try:
            return dns.update_record(domain, kw['ip'], record_type=record_type)
        except Exception as e:
            error(e)
    return False


def update_ip(ip_type, cache, dns, proxy_list):
    """
    更新IP
    """
    ipname = 'ipv' + ip_type
    domains = get_config(ipname)

    if not domains:
        return None
    if not isinstance(domains, list):
        domains = domains.strip('; ').replace(
            ',', ';').replace(' ', ';').split(';')
    index_rule = get_config('index' + ip_type, "default")  # 从配置中获取index配置
    address = get_ip()
    if not address:
        error('Fail to get %s address!', ipname)
        return False
    elif cache and (address == cache[ipname]):
        print('runing', end=" ")  # 缓存命中
        return True
    record_type = (ip_type == '4') and 'A' or 'AAAA'
    update_fail = False  # https://github.com/NewFuture/DDNS/issues/16
    for domain in domains:
        if change_dns_record(dns, proxy_list, domain=domain, ip=address, record_type=record_type):
            update_fail = True
    if cache is not False:
        # 如果更新失败删除缓存
        cache[ipname] = update_fail and address


def main():
    """
    更新
    """
    init_config(__description__, __doc__, __version__)
    # Dynamicly import the dns module as configuration
    dns_provider = str(get_config('dns', 'dnspod').lower())
    dns = getattr(__import__('dns', fromlist=[dns_provider]), dns_provider)
    dns.Config.ID = get_config('id')
    dns.Config.TOKEN = get_config('token')
    dns.Config.TTL = get_config('ttl')
    if get_config('debug'):
        ip.DEBUG = get_config('debug')
        basicConfig(
            level=DEBUG,
            format='%(asctime)s <%(module)s.%(funcName)s> %(lineno)d@%(pathname)s \n[%(levelname)s] %(message)s')
        print("DDNS[", __version__, "] run:", os_name, sys.platform)
        if get_config("config"):
            print("Configuration was loaded from <==",
                  path.abspath(get_config("config")))
        print("=" * 25, ctime(), "=" * 25, sep=' ')

    proxy = get_config('proxy') or 'DIRECT'
    proxy_list = proxy if isinstance(
        proxy, list) else proxy.strip('; ').replace(',', ';').split(';')

    cache = get_config('cache', True) and Cache(CACHE_FILE)
    if cache is False:
        info("Cache is disabled!")
    elif get_config("config_modified_time") is None or get_config("config_modified_time") >= cache.time:
        warning("Cache file is out of dated.")
        cache.clear()
    elif not cache:
        debug("Cache is empty.")
    update_ip('4', cache, dns, proxy_list)
    update_ip('6', cache, dns, proxy_list)


if __name__ == '__main__':
    if sys.version_info.major == 3 and os_name == 'nt':
        from io import TextIOWrapper
        sys.stdout = TextIOWrapper(sys.stdout.detach(), encoding='utf-8')
        sys.stderr = TextIOWrapper(sys.stderr.detach(), encoding='utf-8')
    main()
