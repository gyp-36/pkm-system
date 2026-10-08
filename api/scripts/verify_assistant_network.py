"""SSRF guard regression: controlled DNS/transport, no real external fetch."""
import json
from unittest.mock import patch
from fastapi import HTTPException
from app.knowledge import m3


def denied(fn):
    try:
        fn()
    except HTTPException as exc:
        assert exc.status_code in (422, 403)
    else:
        raise AssertionError('unsafe URL accepted')


def main():
    urls = ['http://127.0.0.1/', 'http://192.168.1.1/', 'http://[::1]/',
            'http://169.254.169.254/latest/meta-data/', 'file:///etc/passwd',
            'ftp://example.com/a', 'http://user:pass@example.com/', 'http://example.com:8080/']
    for url in urls:
        for _ in range(3):
            with patch.object(m3.socket, 'create_connection', side_effect=AssertionError('unsafe connect')):
                denied(lambda: m3._resolve_public_addresses(url))
    # Mixed public/private DNS must reject the entire result.
    with patch.object(m3.socket, 'getaddrinfo', return_value=[(2,1,6,'',('8.8.8.8',80)),(2,1,6,'',('10.0.0.1',80))]):
        denied(lambda: m3._resolve_public_addresses('http://example.com/'))
    calls = []
    original = m3._resolve_public_addresses
    def dns(host, port, **kwargs):
        address = '127.0.0.1' if host == '127.0.0.1' else '8.8.8.8'
        return [(2,1,6,'',(address,port))]
    def redirect(url):
        original(url)
        calls.append(url)
        return 302, 'text/html', 'http://127.0.0.1/private', b''
    for _ in range(3):
        calls.clear()
        with patch.object(m3.socket, 'getaddrinfo', side_effect=dns), patch.object(m3, '_fetch_pinned_response', side_effect=redirect):
            denied(lambda: m3.fetch_public_page_source('http://example.com/', _check_robots=False))
            assert calls == ['http://example.com/']
    sock = object()
    with patch.object(m3.socket, 'create_connection', return_value=sock) as connection:
        pinned = m3._PinnedHTTPConnection('example.com', 80, ['8.8.8.8'], timeout=4)
        pinned.connect()
        assert connection.call_args.args[0] == ('8.8.8.8',80)
    print(json.dumps({'status':'passed','unsafe_url_checks':24,'redirect_checks':3,'mixed_dns_rejected':True,'address_pin_verified':True,'mode':'deterministic_transport','external_fetches':0}))


if __name__ == '__main__':
    main()
