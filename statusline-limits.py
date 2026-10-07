#!/usr/bin/env python3
# Статуслайн Claude Code и мост лимитов в Vorssaint.
# Vorssaint берёт лимиты подписки только из файла, который ведёт десктопный Claude,
# поэтому без открытого приложения цифры замирают. Скрипт дописывает в тот же файл
# проценты из rate_limits, которые Claude Code отдаёт статуслайну, в формате приложения.
import fcntl
import json
import os
import sys
import tempfile
import time

HOME = os.path.expanduser("~")
HISTORY = os.path.join(HOME, "Library/Application Support/Claude/plan-usage-history.json")
PROFILE = os.path.join(HOME, ".claude.json")
KEEP_SECONDS = 31 * 86400
# Без изменений пишем раз в пять минут, у Vorssaint запись старше получаса считается пропуском.
REFRESH_SECONDS = 300


def organization():
    try:
        with open(PROFILE) as f:
            return json.load(f).get("oauthAccount", {}).get("organizationUuid")
    except Exception:
        return None


def read_history():
    try:
        with open(HISTORY) as f:
            data = json.load(f)
        if data.get("version") == 2 and isinstance(data.get("samples"), list):
            return data
    except Exception:
        pass
    return {"version": 2, "samples": []}


def bridge(limits):
    used = {}
    for source, key in (("five_hour", "fh"), ("seven_day", "sd")):
        window = limits.get(source)
        if isinstance(window, dict) and isinstance(window.get("used_percentage"), (int, float)):
            used[key] = round(min(100, max(0, window["used_percentage"])))
    if not used or not os.path.isdir(os.path.dirname(HISTORY)):
        return
    org = organization()
    now_ms = int(time.time() * 1000)
    # Несколько сессий могут писать разом, поэтому файл меняем под блокировкой.
    with open(HISTORY + ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = read_history()
        samples = data["samples"]
        last = samples[-1] if samples else None
        if last and last.get("u") == used and last.get("org") == org \
                and now_ms - last.get("t", 0) < REFRESH_SECONDS * 1000:
            return
        sample = {"t": now_ms, "u": used}
        if org:
            sample["org"] = org
        samples.append(sample)
        data["samples"] = [s for s in samples if now_ms - s.get("t", 0) < KEEP_SECONDS * 1000]
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(HISTORY), prefix=".plan-usage-")
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, separators=(",", ":"))
        os.chmod(tmp, 0o600)
        os.replace(tmp, HISTORY)


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    limits = payload.get("rate_limits") or {}
    try:
        bridge(limits)
    except Exception:
        pass
    parts = [(payload.get("model") or {}).get("display_name") or "Claude"]
    for source, label in (("five_hour", "5ч"), ("seven_day", "нед")):
        window = limits.get(source)
        if isinstance(window, dict) and isinstance(window.get("used_percentage"), (int, float)):
            parts.append(f"{label} {round(window['used_percentage'])}%")
    print(" · ".join(parts))


main()
