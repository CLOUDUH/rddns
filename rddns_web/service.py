import copy
import threading
import time
from datetime import datetime, timezone

from .config import ready
from .providers import DNSError, sync_domain
from .router import RouterError, get_wan_ip


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class Service:
    """One process, one worker. Configuration changes never race DNS mutations."""
    def __init__(self, store):
        self.store = store
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.stop = threading.Event()
        self.pending = None
        self.next_run = 0
        self.status = dict(phase='idle', running=False, wan_ip=None, source=None,
                           checked_at=None, last_success=None, records=[], events=[], error=None)

    def snapshot(self):
        with self.lock:
            result = copy.deepcopy(self.status)
            result['enabled'] = self.store.config['enabled']
            result['next_run'] = self.next_run if result['enabled'] and not result['running'] else None
            return result

    def configure(self, payload):
        with self.lock:
            if self.status['running'] or self.pending:
                raise RuntimeError('任务正在运行或排队，请完成后再保存配置')
            self.store.save(payload)
            self.status.update(phase='idle', error=None, records=[], wan_ip=None, source=None,
                               checked_at=None, last_success=None)
            self.next_run = time.time() if self.store.config['enabled'] else 0
            self.wake.set()

    def enqueue(self, mode):
        with self.lock:
            if self.status['running'] or self.pending:
                raise RuntimeError('已有任务正在运行或排队')
            if mode == 'sync':
                ready(self.store.config)
            self.pending = mode
            self.status['phase'] = 'queued'
            self.wake.set()

    def event(self, message):
        self.status['events'].insert(0, {'time':now(), 'message':message})
        del self.status['events'][100:]

    def cycle(self, mode):
        with self.lock:
            cfg = copy.deepcopy(self.store.config)
            self.status.update(running=True, phase='reading', error=None, records=[])
        try:
            ip, source = get_wan_ip(cfg)
            with self.lock:
                self.status.update(wan_ip=ip, source=source, checked_at=now())
            if mode == 'probe':
                with self.lock:
                    self.status['phase'] = 'tested'
                    self.event('取址测试成功；未更新 DNS')
                return
            ready(cfg)
            with self.lock:
                self.status['phase'] = 'syncing'
            failed = False
            for domain in cfg['domains']:
                try:
                    state = sync_domain(cfg, domain, ip)
                    row = dict(domain=domain, state=state, ip=ip, time=now(), error=None)
                except Exception as exc:
                    failed = True
                    message = str(exc) if isinstance(exc, DNSError) else 'DNS 同步异常，请检查服务商配置'
                    row = dict(domain=domain, state='error', ip=ip, time=now(), error=message)
                with self.lock:
                    self.status['records'].append(row)
            with self.lock:
                self.status['phase'] = 'partial_error' if failed else 'success'
                if not failed:
                    self.status['last_success'] = now()
                self.event('部分或全部域名同步失败，下轮将重新核对' if failed else '全部域名已与 WAN 地址一致')
        except Exception as exc:
            message = str(exc) if isinstance(exc, (RouterError, DNSError)) else '任务失败，请检查配置及网络'
            with self.lock:
                self.status.update(phase='error', error=message, checked_at=now(), wan_ip=None, source=None)
                self.event(message)
        finally:
            with self.lock:
                self.status['running'] = False
                self.next_run = time.time() + cfg['interval']

    def loop(self):
        while not self.stop.is_set():
            with self.lock:
                mode = self.pending
                self.pending = None
                if not mode and self.store.config['enabled'] and time.time() >= self.next_run:
                    mode = 'sync'
                if mode:
                    self.status['running'] = True  # Reserve before releasing the configuration lock.
            if mode:
                self.cycle(mode)
            self.wake.wait(1)
            self.wake.clear()

    def start(self):
        self.thread = threading.Thread(target=self.loop, daemon=True, name='ddns-worker')
        self.thread.start()
