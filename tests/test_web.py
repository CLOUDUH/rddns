import base64
import copy
import json
import stat
import threading
from unittest.mock import Mock

import pytest
import requests

from rddns_web.app import create_app
from rddns_web.config import DEFAULTS, Store, validate
from rddns_web.router import (RouterError, valid_ip, router_url, login_ip,
                              password_constants, encode_password, same_router_url, get_wan_ip)
from rddns_web.providers import DNSError, sync_ali, sync_cf, alidns
from rddns_web.service import Service

PASSWORD = 'test-admin-password-123'
HEADERS = {'Authorization':'Basic ' + base64.b64encode(('admin:' + PASSWORD).encode()).decode(),
           'X-RDDNS-Request':'1'}


def configured():
    return dict(DEFAULTS, zone='example.com', domains=['home.example.com','nas.example.com'],
                access_id='test-id', access_secret='test-secret', router_password='test-router-secret')


@pytest.fixture
def app(tmp_path):
    return create_app(tmp_path, PASSWORD, start_worker=False)


def test_auth_and_csrf(app):
    client = app.test_client()
    assert client.get('/healthz').status_code == 200
    for path in ('/','/api/config','/api/status','/static/app.js'):
        assert client.get(path).status_code == 401
    assert client.get('/', headers=HEADERS).status_code == 200
    assert client.put('/api/config', json={}, headers={'Authorization':HEADERS['Authorization']}).status_code == 403
    assert client.put('/api/config', json={}, headers=dict(HEADERS, **{'Sec-Fetch-Site':'cross-site'})).status_code == 403
    assert client.get('/api/status', headers=HEADERS).headers['Cache-Control'] == 'no-store'


def test_persistence_encrypted_and_no_secret_echo(app, tmp_path):
    client = app.test_client()
    assert client.put('/api/config', json=configured(), headers=HEADERS).status_code == 200
    data = client.get('/api/config', headers=HEADERS).json
    for key in ('router_password','access_secret','access_id'):
        assert data[key] == '' and data[key+'_set'] is True
        assert configured()[key].encode() not in (tmp_path / 'config.enc').read_bytes()
    assert client.put('/api/config', json={'access_secret':''}, headers=HEADERS).status_code == 200
    assert Store(tmp_path).config['access_secret'] == 'test-secret'
    assert stat.S_IMODE((tmp_path / 'config.enc').stat().st_mode) == 0o600


@pytest.mark.parametrize('bad', [-1, '-1', '', '0.0.0.0','127.0.0.1','224.0.0.1','169.254.1.1','255.255.255.255','::1'])
def test_invalid_wan(bad):
    with pytest.raises(RouterError):
        valid_ip(bad)


@pytest.mark.parametrize('value', ['192.168.2.9','10.0.0.2','100.64.1.2','8.8.8.8'])
def test_second_level_ip(value):
    assert valid_ip(value) == value


@pytest.mark.parametrize('bad',['https://evil.test','http://127.0.0.1','http://192.168.1.1/x','http://u:p@192.168.1.1','file:///etc/passwd'])
def test_bad_router_address(bad):
    with pytest.raises(RouterError):
        router_url(bad)


def test_login_failure_does_not_read_wan():
    session = Mock()
    session.request.return_value = Mock(status_code=200, content=b'{}')
    session.request.return_value.json.return_value = {'error_code':-1}
    with pytest.raises(RouterError, match='登录失败'):
        login_ip(session, dict(configured(), password_mode='encoded'))
    assert session.request.call_count == 1


def test_login_reads_private_wan():
    session = Mock()
    responses = [dict(error_code=0,stok='abc123'),{'network':{'wan_status':{'ipaddr':'100.64.2.7'}}}]
    session.request.side_effect = [Mock(status_code=200,content=b'{}',json=Mock(return_value=x)) for x in responses]
    assert login_ip(session, dict(configured(), password_mode='encoded')) == '100.64.2.7'
    for call in session.request.call_args_list:
        assert call.kwargs['timeout'] and call.kwargs['allow_redirects'] is False


def test_constants_and_encoding():
    alphabet = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
    text = 'orgAuthPwd=function(p){var s="abcdefgh",d="' + alphabet + '";return securityEncode(p,s,d);}'
    assert password_constants(text) == ('abcdefgh', alphabet)
    assert encode_password('a', 'a', alphabet) == '0'
    assert encode_password('', 'a', alphabet) == alphabet[(187 ^ 97) % len(alphabet)]
    with pytest.raises(RouterError):
        password_constants('unknown firmware')


def test_no_other_router_or_redirect_destination():
    with pytest.raises(RouterError):
        same_router_url('http://192.168.1.1','http://192.168.1.2/desc.xml')
    assert same_router_url('http://192.168.1.1','http://192.168.1.1:1900/desc.xml').endswith(':1900/desc.xml')


def test_auto_prefers_upnp(monkeypatch):
    monkeypatch.setattr('rddns_web.router.upnp_ip', lambda *a: '10.0.0.7')
    login = Mock()
    monkeypatch.setattr('rddns_web.router.login_ip', login)
    assert get_wan_ip(configured())[0] == '10.0.0.7'
    login.assert_not_called()


def test_probe_never_changes_dns(tmp_path, monkeypatch):
    service = Service(Store(tmp_path))
    monkeypatch.setattr('rddns_web.service.get_wan_ip', lambda c: ('100.64.0.3','UPnP'))
    update = Mock()
    monkeypatch.setattr('rddns_web.service.sync_domain', update)
    service.cycle('probe')
    update.assert_not_called()
    assert service.snapshot()['phase'] == 'tested'


def test_partial_failure_retried_and_no_false_success(tmp_path, monkeypatch):
    store = Store(tmp_path)
    store.save(configured())
    service = Service(store)
    monkeypatch.setattr('rddns_web.service.get_wan_ip', lambda c: ('100.64.0.3','UPnP'))
    update = Mock(side_effect=['updated', DNSError('失败'),'unchanged','updated'])
    monkeypatch.setattr('rddns_web.service.sync_domain', update)
    service.cycle('sync')
    assert service.snapshot()['phase'] == 'partial_error'
    assert service.snapshot()['last_success'] is None
    service.cycle('sync')
    assert update.call_count == 4
    assert service.snapshot()['phase'] == 'success'


def test_router_failure_blocks_all_dns(tmp_path, monkeypatch):
    store = Store(tmp_path)
    store.save(configured())
    service = Service(store)
    monkeypatch.setattr('rddns_web.service.get_wan_ip', Mock(side_effect=RouterError('取址失败')))
    update = Mock()
    monkeypatch.setattr('rddns_web.service.sync_domain', update)
    service.cycle('sync')
    update.assert_not_called()
    assert service.snapshot()['phase'] == 'error'


def test_save_blocked_during_run(app):
    service = app.extensions['rddns']
    service.status['running'] = True
    assert app.test_client().put('/api/config',json={},headers=HEADERS).status_code == 409


def test_malformed_input(app):
    client = app.test_client()
    for payload in ([],{'ttl':True},{'interval':1},{'domains':['bad.example.com.evil'],'zone':'example.com'}, {'enabled':True}):
        assert client.put('/api/config',json=payload,headers=HEADERS).status_code == 400


def test_ali_http200_api_error():
    session = Mock()
    session.request.return_value = Mock(status_code=200,json=Mock(return_value={'Code':'Denied','Message':'secret'}))
    with pytest.raises(DNSError) as exc:
        alidns(session, configured(), 'DescribeDomainRecords')
    assert 'secret' not in str(exc.value)


def test_ali_create_and_signing(monkeypatch):
    request = Mock(side_effect=[{'TotalCount':0,'DomainRecords':{'Record':[]}}, {'RecordId':'123'}])
    monkeypatch.setattr('rddns_web.providers.alidns', request)
    assert sync_ali(Mock(), configured(), 'home.example.com','10.0.0.3') == 'updated'
    assert request.call_args.args[2] == 'AddDomainRecord'
    assert request.call_args.kwargs['Value'] == '10.0.0.3'


def test_ali_unchanged_and_case(monkeypatch):
    record = {'RR':'home','Type':'A','RecordId':'1','Status':'Enable','Value':'10.0.0.3','TTL':600}
    request = Mock(return_value={'TotalCount':1,'DomainRecords':{'Record':[record]}})
    monkeypatch.setattr('rddns_web.providers.alidns', request)
    assert sync_ali(Mock(),configured(),'home.example.com','10.0.0.3') == 'unchanged'
    assert request.call_count == 1
    assert request.call_args.kwargs['SearchMode'] == 'COMBINATION'


def test_ali_multiple_records_rejected(monkeypatch):
    record = {'RR':'home','Type':'A'}
    request = Mock(return_value={'TotalCount':2,'DomainRecords':{'Record':[record,record]}})
    monkeypatch.setattr('rddns_web.providers.alidns',request)
    with pytest.raises(DNSError, match='多于一条'):
        sync_ali(Mock(),configured(),'home.example.com','10.0.0.3')
    assert request.call_count == 1


def test_cf_patch_preserves_other_properties(monkeypatch):
    request = Mock(side_effect=[{'result':[{'id':'1','name':'home.example.com','type':'A','content':'10.0.0.1','ttl':600,'proxied':False}]},{'result':{'id':'1'}}])
    monkeypatch.setattr('rddns_web.providers.cloudflare',request)
    assert sync_cf(Mock(),dict(configured(),zone_id='a'*32),'home.example.com','10.0.0.3') == 'updated'
    assert request.call_args.args[2] == 'PATCH'
    assert request.call_args.kwargs['json'] == {'content':'10.0.0.3','ttl':600}


def test_cf_proxy_is_not_silently_changed(monkeypatch):
    request = Mock(return_value={'result':[{'name':'home.example.com','type':'A','proxied':True}]})
    monkeypatch.setattr('rddns_web.providers.cloudflare',request)
    with pytest.raises(DNSError,match='代理'):
        sync_cf(Mock(),dict(configured(),zone_id='a'*32),'home.example.com','10.0.0.3')
    assert request.call_count == 1


def test_auto_falls_back_once(monkeypatch):
    monkeypatch.setattr('rddns_web.router.upnp_ip', Mock(side_effect=RouterError('unavailable')))
    login = Mock(return_value='172.16.10.20')
    monkeypatch.setattr('rddns_web.router.login_ip', login)
    assert get_wan_ip(configured())[0] == '172.16.10.20'
    assert login.call_count == 1


@pytest.mark.parametrize('bad',[True, 1234, '0.0.0.1', '240.0.0.1'])
def test_non_wan_values(bad):
    with pytest.raises(RouterError):
        valid_ip(bad)


def test_upnp_uses_only_configured_router(monkeypatch):
    from rddns_web.router import upnp_ip
    packets = [(b'LOCATION: http://192.168.1.2/evil\r\n', ('192.168.1.2',1900)),
               (b'LOCATION: http://192.168.1.1:1900/root.xml\r\n', ('192.168.1.1',1900))]
    sock = Mock()
    sock.__enter__ = Mock(return_value=sock)
    sock.__exit__ = Mock(return_value=False)
    sock.recvfrom.side_effect = packets
    monkeypatch.setattr('rddns_web.router.socket.socket',Mock(return_value=sock))
    monkeypatch.setattr('rddns_web.router.time.monotonic',Mock(side_effect=[0,0,0,3]))
    description = b'<root><device><serviceList><service><serviceType>urn:schemas-upnp-org:service:WANIPConnection:1</serviceType><controlURL>/ctl</controlURL></service></serviceList></device></root>'
    reply = b'<root><NewExternalIPAddress>172.16.10.20</NewExternalIPAddress></root>'
    session = Mock()
    session.request.side_effect = [Mock(status_code=200,content=description),Mock(status_code=200,content=reply)]
    assert upnp_ip(session,'http://192.168.1.1') == '172.16.10.20'
    assert session.request.call_args_list[0].args[1] == 'http://192.168.1.1:1900/root.xml'
    assert session.request.call_args_list[1].args[1] == 'http://192.168.1.1:1900/ctl'


def test_scheduler_no_overlapping_or_midflight_config(tmp_path, monkeypatch):
    service = Service(Store(tmp_path))
    started, finish = threading.Event(), threading.Event()
    def reader(cfg):
        started.set()
        assert finish.wait(3)
        return '172.16.10.20','UPnP'
    monkeypatch.setattr('rddns_web.service.get_wan_ip',reader)
    service.start()
    service.enqueue('probe')
    try:
        assert started.wait(2)
        with pytest.raises(RuntimeError):
            service.enqueue('probe')
        with pytest.raises(RuntimeError):
            service.configure({'interval':120})
    finally:
        finish.set()
        service.stop.set()
        service.wake.set()
        service.thread.join(3)
    assert service.snapshot()['phase'] == 'tested'


def test_ali_paginates_before_deciding_unique(monkeypatch):
    other = [{'RR':'other','Type':'A'}] * 100
    target = {'RR':'home','Type':'A','Status':'ENABLE','RecordId':'2','Value':'10.0.0.3','TTL':600}
    request = Mock(side_effect=[{'TotalCount':101,'DomainRecords':{'Record':other}},
                               {'TotalCount':101,'DomainRecords':{'Record':[target]}}])
    monkeypatch.setattr('rddns_web.providers.alidns',request)
    assert sync_ali(Mock(),configured(),'home.example.com','10.0.0.3') == 'unchanged'
    assert request.call_args.kwargs['PageNumber'] == 2


def test_switch_provider_does_not_reuse_secret():
    cfg = validate({'provider':'cloudflare'},configured())
    assert cfg['access_secret'] == ''
    assert cfg['access_id'] == ''


def test_missing_encryption_key_fails_closed(tmp_path):
    store = Store(tmp_path)
    store.save(configured())
    before = (tmp_path/'config.enc').read_bytes()
    (tmp_path/'encryption.key').unlink()
    with pytest.raises(ValueError,match='密钥缺失'):
        Store(tmp_path)
    assert (tmp_path/'config.enc').read_bytes() == before
    assert not (tmp_path/'encryption.key').exists()
