import hmac
import os
import secrets
from pathlib import Path

from flask import Flask, jsonify, request
from .config import Store, atomic_write
from .service import Service


def create_app(directory=None, admin_password=None, start_worker=True):
    store = Store(directory or os.environ.get('RDDNS_DATA_DIR', './data'))
    password = admin_password or os.environ.get('RDDNS_ADMIN_PASSWORD')
    if not password:
        password_file = store.path / 'admin-password'
        if password_file.exists():
            password = password_file.read_text().strip()
        else:
            password = secrets.token_urlsafe(24)
            atomic_write(password_file, password.encode())
            print('RDDNS 初始管理账户：admin；初始密码：' + password, flush=True)
    if len(password) < 12:
        raise ValueError('管理密码至少需要 12 个字符')
    service = Service(store)
    app = Flask(__name__, static_folder='static', static_url_path='/static')
    app.config['MAX_CONTENT_LENGTH'] = 32 * 1024
    app.extensions['rddns'] = service

    @app.before_request
    def guard():
        if request.path == '/healthz' and request.method == 'GET':
            return None
        auth = request.authorization
        if not auth or auth.type.lower() != 'basic' or not hmac.compare_digest((auth.username or '').encode(), b'admin') or not hmac.compare_digest((auth.password or '').encode(), password.encode()):
            return ('需要管理账户登录', 401, {'WWW-Authenticate':'Basic realm="RDDNS", charset="UTF-8"'})
        if request.method in ('POST','PUT','PATCH','DELETE'):
            if request.headers.get('X-RDDNS-Request') != '1' or not request.is_json:
                return jsonify(error='请求校验失败，请从管理页面操作'), 403
            if request.headers.get('Sec-Fetch-Site') == 'cross-site':
                return jsonify(error='禁止跨站请求'), 403

    @app.after_request
    def headers(response):
        response.headers.update({
            'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff',
            'X-Frame-Options':'DENY', 'Referrer-Policy':'no-referrer',
            'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
        return response

    @app.get('/')
    def index():
        return app.send_static_file('index.html')

    @app.get('/healthz')
    def health():
        alive = not start_worker or service.thread.is_alive()
        return jsonify(status='ok' if alive else 'worker_stopped'), 200 if alive else 503

    @app.get('/api/config')
    def config():
        with service.lock:
            return jsonify(store.public())

    @app.put('/api/config')
    def save():
        service.configure(request.get_json())
        return jsonify(ok=True)

    @app.get('/api/status')
    def status():
        return jsonify(service.snapshot())

    @app.post('/api/probe')
    def probe():
        service.enqueue('probe')
        return jsonify(ok=True), 202

    @app.post('/api/sync')
    def sync():
        service.enqueue('sync')
        return jsonify(ok=True), 202

    @app.errorhandler(ValueError)
    def invalid(exc):
        return jsonify(error=str(exc)), 400

    @app.errorhandler(RuntimeError)
    def busy(exc):
        return jsonify(error=str(exc)), 409

    @app.errorhandler(500)
    def unexpected(exc):
        return jsonify(error='服务内部错误，请检查数据目录权限和运行环境'), 500

    if start_worker:
        service.start()
    return app


def main():
    from waitress import serve
    app = create_app()
    serve(app, host=os.environ.get('RDDNS_HOST','0.0.0.0'), port=int(os.environ.get('RDDNS_PORT','8080')),
          threads=6, clear_untrusted_proxy_headers=True)


if __name__ == '__main__':
    main()
