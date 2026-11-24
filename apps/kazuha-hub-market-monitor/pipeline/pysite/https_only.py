"""Send every plain-HTTP request to a non-loopback host over https.

The backend reaches the internet only through the platform's HTTPS proxy
(HTTPS_PROXY; there is no HTTP_PROXY), so a plain-HTTP request goes direct and
fails, typically on DNS. Some akshare functions still name http:// URLs (for
example stock_report_fund_hold asks data.eastmoney.com over plain HTTP), and the hosts
they call all serve https. Loopback stays plain: the pipeline's own data
server listens on 127.0.0.1.
"""
from urllib.parse import urlsplit, urlunsplit

LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def upgrade(url):
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if parts.scheme.lower() != "http" or (parts.hostname or "") in LOOPBACK:
        return url
    host = parts.hostname or ""
    if ":" in host:
        host = "[" + host + "]"
    if parts.port not in (None, 80):
        host += ":%d" % parts.port
    if parts.username:
        cred = parts.username + (":" + parts.password if parts.password else "")
        host = cred + "@" + host
    return urlunsplit(("https", host, parts.path, parts.query, parts.fragment))


def install():
    """Patch requests' Session.send, which every request and every redirect
    goes through. Idempotent."""
    import requests.sessions as sessions
    send = sessions.Session.send
    if getattr(send, "_https_only", False):
        return

    def https_send(self, request, **kwargs):
        request.url = upgrade(request.url)
        return send(self, request, **kwargs)
    https_send._https_only = True
    sessions.Session.send = https_send
