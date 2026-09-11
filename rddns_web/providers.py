"""Small, explicit provider clients. Successful HTTP alone is not API success."""
import base64
import hashlib
import hmac
import uuid
from datetime import datetime, timezone
from urllib.parse import quote, urlencode

import requests


class DNSError(ValueError):
    pass


def api_json(session, method, url, **kwargs):
    try:
        response = session.request(method, url, timeout=(5, 15), allow_redirects=False, **kwargs)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError()
        return data
    except (requests.RequestException, ValueError):
        # Never surface raw responses, request URLs, signatures or credentials.
        raise DNSError('DNS API 网络、HTTP 或响应格式错误；请检查密钥权限及网络') from None


def alidns(session, cfg, action, **params):
    params.update(Action=action, Format='JSON', Version='2015-01-09',
                  AccessKeyId=cfg['access_id'], SignatureMethod='HMAC-SHA1',
                  Timestamp=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                  SignatureVersion='1.0', SignatureNonce=str(uuid.uuid4()))
    query = urlencode(sorted(params.items()), quote_via=quote, safe='~')
    string = 'POST&%2F&' + quote(query, safe='~')
    params['Signature'] = base64.b64encode(hmac.new(
        (cfg['access_secret'] + '&').encode(), string.encode(), hashlib.sha1).digest()).decode()
    data = api_json(session, 'POST', 'https://alidns.aliyuncs.com/', data=params)
    if 'Code' in data:
        # Deliberately use a generic message: providers can echo user secrets.
        raise DNSError('阿里云拒绝请求；请检查 AccessKey 权限、域名和 TTL')
    return data


def sync_ali(session, cfg, domain, ip):
    zone = cfg['zone']
    rr = '@' if domain == zone else domain[:-(len(zone) + 1)]
    records, page = [], 1
    while True:
        data = alidns(session, cfg, 'DescribeDomainRecords', DomainName=zone,
                      RRKeyWord=rr, TypeKeyWord='A', SearchMode='COMBINATION', PageSize=100, PageNumber=page)
        batch = data.get('DomainRecords', {}).get('Record')
        if not isinstance(batch, list) or 'TotalCount' not in data:
            raise DNSError('阿里云返回的记录列表不完整')
        records.extend(r for r in batch if r.get('RR') == rr and r.get('Type') == 'A')
        if page * 100 >= int(data['TotalCount']):
            break
        page += 1
        if page > 100:
            raise DNSError('匹配记录过多，请缩小配置范围')
    if len(records) > 1:
        raise DNSError('同名 A 记录多于一条，请先明确唯一记录，避免覆盖分线路解析')
    if records:
        record = records[0]
        if str(record.get('Status', '')).upper() != 'ENABLE' or record.get('Locked') is True:
            raise DNSError('阿里云记录已暂停或锁定，请先在 DNS 控制台检查')
        if record.get('Value') == ip and record.get('TTL') == cfg['ttl']:
            return 'unchanged'
        result = alidns(session, cfg, 'UpdateDomainRecord', RecordId=record['RecordId'],
                        RR=rr, Type='A', Value=ip, TTL=cfg['ttl'], Line=record.get('Line', 'default'))
    else:
        result = alidns(session, cfg, 'AddDomainRecord', DomainName=zone,
                        RR=rr, Type='A', Value=ip, TTL=cfg['ttl'])
    if not result.get('RecordId'):
        raise DNSError('阿里云未确认记录更新成功')
    return 'updated'


def cloudflare(session, cfg, method, path, **kwargs):
    data = api_json(session, method, 'https://api.cloudflare.com/client/v4/' + path,
                    headers={'Authorization': 'Bearer ' + cfg['access_secret']}, **kwargs)
    if data.get('success') is not True:
        raise DNSError('Cloudflare 拒绝请求；请检查 Token 权限、Zone ID 及记录')
    return data


def sync_cf(session, cfg, domain, ip):
    path = 'zones/' + cfg['zone_id'] + '/dns_records'
    data = cloudflare(session, cfg, 'GET', path, params={'name':domain,'type':'A','per_page':100})
    records = data.get('result')
    if not isinstance(records, list):
        raise DNSError('Cloudflare 未返回记录列表')
    if data.get('result_info', {}).get('total_pages', 1) > 1 or len(records) > 1:
        raise DNSError('同名 A 记录多于一条，请先明确唯一记录')
    if records:
        record = records[0]
        if record.get('name') != domain or record.get('type') != 'A':
            raise DNSError('Cloudflare 返回了不匹配的记录')
        if record.get('proxied'):
            raise DNSError('该记录已开启 Cloudflare 代理；二级 WAN 场景请先在控制台改为 DNS only')
        if record.get('content') == ip and record.get('ttl') == cfg['ttl']:
            return 'unchanged'
        result = cloudflare(session, cfg, 'PATCH', path + '/' + record['id'],
                            json={'content':ip,'ttl':cfg['ttl']})
    else:
        result = cloudflare(session, cfg, 'POST', path,
                            json={'type':'A','name':domain,'content':ip,'ttl':cfg['ttl'],'proxied':False})
    if not isinstance(result.get('result'), dict) or not result['result'].get('id'):
        raise DNSError('Cloudflare 未确认记录更新成功')
    return 'updated'


def sync_domain(cfg, domain, ip):
    with requests.Session() as session:
        return (sync_ali if cfg['provider'] == 'alidns' else sync_cf)(session, cfg, domain, ip)
