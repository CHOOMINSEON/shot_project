import hmac
import secrets
import threading
import time

from fastapi import HTTPException
from starlette.responses import RedirectResponse
from starlette.routing import Route


def install_desktop_entry(app, ttl=120):
    """A single-use login ticket for a server bound only to the local PC."""
    if not hasattr(app.state, 'desktop_tickets'):
        app.state.desktop_tickets = {}
        app.state.desktop_ticket_guard = threading.Lock()
        app.router.routes.insert(0, Route('/__desktop/{ticket}', enter_desktop, methods=['GET']))
    ticket = secrets.token_urlsafe(32)
    with app.state.desktop_ticket_guard:
        tickets = app.state.desktop_tickets
        for key in list(tickets):
            if tickets[key] <= time.monotonic():
                tickets.pop(key)
        while len(tickets) >= 8:
            tickets.pop(next(iter(tickets)))
        tickets[ticket] = time.monotonic() + ttl
    return '/__desktop/' + ticket


async def enter_desktop(request):
    if (not request.client or request.client.host != '127.0.0.1'
            or request.url.hostname != '127.0.0.1'):
        raise HTTPException(403, '이 PC에서만 사용할 수 있는 시작 주소입니다.')
    with request.app.state.desktop_ticket_guard:
        tickets = request.app.state.desktop_tickets
        value = request.path_params['ticket'].encode('utf-8')
        match = next((key for key in tickets if hmac.compare_digest(value, key.encode('ascii'))), None)
        deadline = tickets.pop(match, 0)
        if deadline <= time.monotonic():
            raise HTTPException(403, '시작 주소가 만료되었습니다. 프로그램을 다시 실행해 주세요.')
    from studio.app import Login, login, owner_password
    logged_in = login(Login(password=owner_password()), request)
    response = RedirectResponse('/', status_code=303)
    response.headers['set-cookie'] = logged_in.headers['set-cookie']
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response
