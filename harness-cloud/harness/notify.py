"""Системное уведомление Windows (тост) по окончании обработки.

Браузерный Notification в окне WebView2 обычно недоступен, поэтому тост показывает бэкенд через
PowerShell. Окно PowerShell скрыто, AppID — стандартный «Windows PowerShell», он уже зарегистрирован,
поэтому отдельная установка не нужна. На не-Windows функция ничего не делает.
"""
from __future__ import annotations

import base64
import html
import os
import subprocess
import sys

from .winproc import hidden_kwargs

_SCRIPT = r"""
[void][Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime]
[void][Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom.XmlDocument,ContentType=WindowsRuntime]
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml("<toast><visual><binding template='ToastText02'><text id='1'>$env:HC_TITLE</text><text id='2'>$env:HC_BODY</text></binding></visual></toast>")
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Windows PowerShell').Show($toast)
"""


def show(title: str, body: str) -> bool:
    """Показывает тост. Возвращает False, если уведомление не удалось отправить."""
    if sys.platform != "win32":
        return False
    encoded = base64.b64encode(_SCRIPT.encode("utf-16-le")).decode("ascii")
    env = dict(os.environ, HC_TITLE=html.escape(title[:80]), HC_BODY=html.escape(body[:200]))
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
             "-EncodedCommand", encoded],
            env=env, **hidden_kwargs())
    except OSError:
        return False
    return True
