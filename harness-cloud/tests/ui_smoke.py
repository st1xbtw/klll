"""Проверка всех кнопок интерфейса в реальном Chrome (Playwright).

Запуск: сервер на порту 8799 (python run.py --server --port 8799) с данными, где есть готовый проект,
затем: python tests/ui_smoke.py <project_id> [url]
Скриншот пишется в docs/screenshot-home.png.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
BASE = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8799/"
def _default_pid() -> str:
    """Ждёт, пока на сервере появится готовый проект (фоновый перерендер может идти)."""
    import json, time, urllib.request
    for _ in range(180):
        items = json.load(urllib.request.urlopen(BASE + "api/projects"))
        done = [p for p in items if p["status"] == "done"]
        if done:
            return done[0]["id"]
        time.sleep(5)
    raise SystemExit("Нет готовых проектов на сервере")


PID = sys.argv[1] if len(sys.argv) > 1 else _default_pid()
results: list[str] = []


def ok(name: str) -> None:
    results.append(f"OK   {name}")
    print(results[-1], flush=True)


def run() -> int:
    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, accept_downloads=True)
        ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=BASE.rstrip("/"))
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        page.on("console", lambda m: errors.append(f"console: {m.text}") if m.type == "error" else None)
        page.on("dialog", lambda d: d.accept())

        page.goto(BASE)
        page.evaluate(f"localStorage.setItem('hc_project', '{PID}')")
        page.reload()
        expect(page.locator("#statusText")).to_contain_text("Готово", timeout=15000)
        ok("проект загружен, статус «Готово»")
        page.screenshot(path=str(ROOT / "docs" / "screenshot-home.png"), full_page=False)

        cards = page.locator(".clip-card")
        n = cards.count()
        assert n >= 5, f"клипов {n}"
        ok(f"карточки клипов отрисованы: {n}")

        # Навигация
        for view, title in [("history", "История"), ("settings", "Настройки"), ("about", "О приложении"), ("home", None)]:
            page.locator(f'.nav-item[data-view="{view}"]').click()
            expect(page.locator(f"#view-{view}")).to_have_class("view active")
            ok(f"навигация: {view}")
        page.locator(f'.nav-item[data-view="settings"]').click()

        # История
        page.locator('.nav-item[data-view="history"]').click()
        expect(page.locator("#historyList .hist-item").first).to_be_visible(timeout=5000)
        page.locator(f'#historyList [data-open="{PID}"]').click()
        expect(page.locator("#view-home")).to_have_class("view active")
        ok("история: «Открыть» возвращает на главную")

        # Тема
        start = page.locator("html").get_attribute("data-theme")
        other = "light" if start == "dark" else "dark"
        page.locator(".theme-toggle").click()
        expect(page.locator("html")).to_have_attribute("data-theme", other)
        page.locator(".theme-toggle").click()
        expect(page.locator("html")).to_have_attribute("data-theme", start)
        ok("переключатели светлой/тёмной темы")

        # Тип контента
        page.locator('#contentChips [data-type="game"]').click()
        expect(page.locator("#typeHint")).not_to_be_empty()
        expect(page.locator('#contentChips [data-type="game"]')).to_have_class("chip active")
        page.locator('#contentChips [data-type="podcast"]').click()
        ok("чипы типа контента переключаются, подсказка для «Игры»")

        # Расширенные настройки
        page.locator("#advToggle").click()
        expect(page.locator("#advPanel")).to_be_visible()
        page.locator("#advToggle").click()
        expect(page.locator("#advPanel")).to_be_hidden()
        ok("расширенные настройки открываются и скрываются")

        # Поле ссылки
        page.locator("#urlInput").fill("не ссылка")
        expect(page.locator("#urlHint")).to_contain_text("Не похоже")
        page.locator("#clearUrl").click()
        expect(page.locator("#urlInput")).to_have_value("")
        ok("валидация ссылки и кнопка очистки")

        page.locator("#startBtn").click()
        expect(page.locator("#toasts .toast").last).to_contain_text("ссылку")
        ok("«Начать обработку» с пустым полем показывает ошибку")

        page.locator("#urlInput").fill("https://example.com/no-such-video")
        page.locator("#loadBtn").click()
        expect(page.locator("#toasts .toast").last).to_contain_text("принято")
        ok("«Загрузить» подтверждает ссылку")

        # Предпросмотр и навигация по клипам
        cards.nth(1).click()
        expect(page.locator("#clipPos")).to_have_text(f"2 / {n}")
        page.locator("#nextClip").click()
        expect(page.locator("#clipPos")).to_have_text(f"3 / {n}")
        page.locator("#prevClip").click()
        page.locator("#prevClip").click()
        expect(page.locator("#clipPos")).to_have_text(f"1 / {n}")
        ok("выбор клипа, «вперёд/назад» по карточкам")

        page.locator("#playBtn").click()
        page.wait_for_timeout(300)
        page.locator("#playBtn").click()
        page.locator("#muteBtn").click()
        page.locator("#muteBtn").click()
        ok("плеер: play/pause и звук")

        # Пробел и стрелки
        page.locator("body").click(position={"x": 5, "y": 5})
        page.keyboard.press("Space")
        page.wait_for_timeout(200)
        page.keyboard.press("Space")
        page.keyboard.press("ArrowRight")
        expect(page.locator("#clipPos")).to_have_text(f"2 / {n}")
        page.keyboard.press("ArrowLeft")
        ok("горячие клавиши: пробел и стрелки")

        # Описание и хештеги
        page.locator("#descToggle").click()
        expect(page.locator("#descBody")).to_be_visible()
        page.locator("#copyDesc").click()
        expect(page.locator("#toasts .toast").last).to_contain_text("скопирован")
        page.locator("#descToggle").click()
        ok("описание и хештеги: раскрыть и скопировать")

        # Вкладки платформ и ручная правка (без лишних перерендеров)
        page.locator("#descToggle").click()
        page.locator('#platformTabs [data-plat="shorts"]').click()
        expect(page.locator('#platformTabs [data-plat="shorts"]')).to_have_class("ptab active")
        page.locator('#platformTabs [data-plat="tiktok"]').click()
        page.locator("#descToggle").click()
        ok("описание: вкладки TikTok / Shorts / Reels")
        page.locator("#timeline").click(position={"x": 120, "y": 20})
        expect(page.locator("#newFromPoint")).to_be_enabled()
        ok("таймлайн: клик ставит точку, кнопка «Клип с выбранной точки» активна")
        page.locator("#advToggle").click()
        expect(page.locator("#advPanel")).to_be_visible()
        page.locator("#aspect").select_option("16:9")
        expect(page.locator("#toasts .toast").last).to_contain_text("формат")
        expect(page.locator("#statusText")).to_contain_text("Нарезка", timeout=15000)
        expect(page.locator("#statusText")).to_contain_text("Готово", timeout=900000)
        ok("формат кадра 16:9 запускает перерендер")

        # Ручная подрезка: сдвиг и сброс
        page.locator("#trim").fill("1.5")
        expect(page.locator("#trimLbl")).to_contain_text("+1.5")
        page.locator("#trimApply").click()
        expect(page.locator("#toasts .toast").last).to_contain_text("перерезается")
        ok("обрезка: сдвиг начала применяется")
        expect(page.locator("#trimReset")).to_be_enabled(timeout=180000)
        page.locator("#trimReset").click()
        expect(page.locator("#toasts .toast").last).to_contain_text("возвращено")
        ok("обрезка: сброс")

        # Таймлайн
        page.locator("#timeline").click(position={"x": 200, "y": 20})
        ok("таймлайн: клик по шкале")

        # Скачивание клипа и архива
        with page.expect_download() as d1:
            page.locator("#dlOne").click()
        assert d1.value.suggested_filename.endswith(".mp4")
        ok("«Скачать этот клип»")
        expect(page.locator("#zipBtn")).to_be_enabled()
        with page.expect_download(timeout=120000) as d2:
            page.locator("#zipBtn").click()
        zpath = ROOT / "docs" / "_check.zip"
        d2.value.save_as(str(zpath))
        with zipfile.ZipFile(zpath) as z:
            assert z.testzip() is None
            names = z.namelist()
            assert "metadata.json" in names
            clips_in_zip = [x for x in names if x.endswith(".mp4")]
            assert len(clips_in_zip) >= 5, names
        zpath.unlink()
        ok(f"«Скачать всё»: ZIP открывается, клипов в архиве: {len(clips_in_zip)}")

        # Меню ⋯
        page.locator("#moreBtn").click()
        expect(page.locator("#moreMenu")).to_be_visible()
        page.locator('#moreMenu [data-act="copyall"]').click()
        expect(page.locator("#toasts .toast").last).to_contain_text("скопированы")
        page.locator("#moreBtn").click()
        ok("меню ⋯: копирование всех описаний")

        # Смена стиля субтитров (перерендер без транскрибации)
        expect(page.locator("#statusText")).to_contain_text("Готово", timeout=600000)
        # Выбираем стиль, отличный от текущего: иначе change не сработает и тост не появится
        target = "violet" if page.locator("#subStyle").input_value() == "yellow" else "yellow"
        page.locator("#subStyle").select_option(target)
        expect(page.locator("#toasts .toast").last).to_contain_text("стилем")
        expect(page.locator("#statusText")).to_contain_text("Нарезка", timeout=15000)
        expect(page.locator("#statusText")).to_contain_text("Готово", timeout=900000)
        ok("смена стиля субтитров запускает перерендер")

        # Настройки: сохранение и тема
        page.locator('.nav-item[data-view="settings"]').click()
        page.locator("#setCount").select_option("7")
        page.locator("#saveSettings").click()
        expect(page.locator("#toasts .toast").last).to_contain_text("сохранены")
        page.locator("body").click(position={"x": 5, "y": 5})
        page.keyboard.press("Control+S")
        expect(page.locator("#toasts .toast").last).to_contain_text("сохранены")
        ok("настройки: кнопка и Ctrl+S")

        # Ошибочный проект: сообщение и повтор
        page.locator('.nav-item[data-view="home"]').click()
        page.locator("#urlInput").fill("https://example.com/no-such-video")
        page.locator("#startBtn").click()
        expect(page.locator("#statusText")).to_contain_text("Ошибка", timeout=180000)
        expect(page.locator("#warnBox")).to_be_visible()
        ok("ошибка загрузки показывается в статусе и предупреждениях")
        page.locator("#moreBtn").click()
        page.locator('#moreMenu [data-act="retry"]').click()
        ok("меню: «Повторить с ошибочного шага» отправляется")

        with page.expect_response(lambda r: r.url.endswith("/api/projects") and r.request.method == "GET"):
            page.locator('.nav-item[data-view="history"]').click()
        expect(page.locator("#historyList .hist-item").first).to_be_visible(timeout=10000)
        before = page.locator("#historyList .hist-item").count()
        page.locator(f'#historyList .hist-item:not([data-pid="{PID}"]) [data-del]').first.click()
        expect(page.locator("#historyList .hist-item")).to_have_count(before - 1, timeout=10000)
        ok("история: удаление проекта")

        browser.close()

    real_errors = [e for e in errors if "favicon" not in e and "Failed to load resource" not in e]
    print("\nОшибки JS в консоли:", real_errors or "нет", flush=True)
    return 0 if not real_errors else 1


if __name__ == "__main__":
    sys.exit(run())
