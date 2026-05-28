"""HTTP Basic Auth для UI-админки.

`/admin*` HTML-страницы закрыты этим dep'ом. JSON-API под `/api/v1/admin/*`
имеет отдельный X-Admin-Token (см. `app.admin.require_admin_token`).

Пара логин/пароль хранится в env (ADMIN_USER / ADMIN_PASSWORD).
Если ADMIN_PASSWORD не задан, доступ к UI-админке полностью закрыт
(возвращаем 403, чтобы не светить отсутствующий пароль через 401-prompt).
"""
from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.config import settings

_REALM = "DSA Faculty Admin"
# auto_error=False — сами выбрасываем 401 с заголовком WWW-Authenticate,
# чтобы браузер показал нативный login-prompt вместо JSON-ошибки.
_basic = HTTPBasic(realm=_REALM, auto_error=False)


def require_admin_basic(
    creds: HTTPBasicCredentials | None = Depends(_basic),
) -> str:
    """Проверяет HTTP Basic-кредеши против ADMIN_USER/ADMIN_PASSWORD.

    Возвращает имя залогиненного пользователя (для отображения в UI).
    """
    if not settings.admin_password:
        # Защита от случайного «открытого» прода — если пароль не задан,
        # админку показывать НЕЛЬЗЯ. 403, без браузерного prompt'а.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin UI закрыта: задайте ADMIN_PASSWORD в окружении.",
        )

    auth_header = {"WWW-Authenticate": f'Basic realm="{_REALM}"'}
    if creds is None:
        # Юзер не прислал креды — показать браузерный login-диалог
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers=auth_header,
        )
    user_ok = secrets.compare_digest(creds.username, settings.admin_user)
    pass_ok = secrets.compare_digest(creds.password, settings.admin_password)
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль",
            headers=auth_header,
        )
    return creds.username


__all__ = ["require_admin_basic"]
