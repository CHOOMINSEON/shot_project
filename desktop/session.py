import hmac
import secrets
import threading
import time

from fastapi import HTTPException
from starlette.responses import RedirectResponse
from starlette.routing import Route


def install_desktop_entry(app, ttl=120):
    """A single-use login ticket for a server bound only to the local PC."""
    ticket = secrets.token_urlsafe(32)
    deadline = time.monotonic() + ttl
    guard = threading.Lock()
    consumed = False

    async def enter(request):
        nonlocal consumed
        if (not request.client or request.client.host != '127.0.0.1'
                or request.url.hostname != '127.0.0.1'):
            raise HTTPException(403, '이 PC에서만 사용할 수 있는 시작 주소입니다.')
        with guard:
            if consumed or time.monotonic() >= deadline or not hmac.compare_digest(request.path_params['ticket'], ticket):
                raise HTTPException(403, '시작 주소가 만료되었습니다. 프로그램을 다시 실행해 주세요.')
            consumed = True
        from studio.app import Login, login, owner_password
        logged_in = login(Login(password=owner_password()), request)
        response = RedirectResponse('/', status_code=303)
        response.headers['set-cookie'] = logged_in.headers['set-cookie']
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    app.router.routes.insert(0, Route('/__desktop/{ticket}', enter, methods=['GET']))
    return '/__desktop/' + ticket
