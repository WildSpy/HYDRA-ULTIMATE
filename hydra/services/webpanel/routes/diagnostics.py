"""Маршруты раздела «Тестирование и диагностика».

Используются НЕинтерактивные примитивы из hydra.ui.diagnostics (интерактивные
обёртки test_* полагаются на TTY и здесь не применяются). Тяжёлые проверки
выполняются как фоновые задачи.
"""
from __future__ import annotations

from pathlib import Path

from hydra.services.webpanel.errors import BadRequest

REPORT_PATH = Path("/var/log/hydra/diagnostics_report.md")


def full_report(ctx):
    def _job():
        from hydra.ui import diagnostics as d
        path = d.run_diagnostics_report()
        markdown = ""
        try:
            markdown = Path(path).read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass
        return {"path": path, "markdown": markdown}

    return {"task_id": ctx.tasks.start("diag-report", _job)}


def report_file(ctx):
    if not REPORT_PATH.exists():
        return {"exists": False, "markdown": ""}
    return {"exists": True, "path": str(REPORT_PATH),
            "markdown": REPORT_PATH.read_text(encoding="utf-8", errors="replace")}


def censorcheck(ctx):
    mode = str(ctx.get("mode", "geoblock") or "geoblock")
    if mode not in ("geoblock", "dpi"):
        raise BadRequest("mode: geoblock | dpi")

    def _job():
        from hydra.ui import diagnostics as d
        return d.run_censorcheck_python(mode)

    return {"task_id": ctx.tasks.start(f"diag-censor-{mode}", _job)}


def tspu(ctx):
    def _job():
        from hydra.ui import diagnostics as d
        ip = d.get_ip_address(4)
        sni = d.get_reality_sni()
        return d.run_tspu_radar(ip, sni)

    return {"task_id": ctx.tasks.start("diag-tspu", _job)}


def geoip(ctx):
    def _job():
        from hydra.ui import diagnostics as d
        ipv4 = d.get_ip_address(4) or ""
        ipv6 = d.get_ip_address(6) or ""
        has_v6 = d.check_system_ipv6()
        primary = ["RIPE", "MAXMIND", "IPINFO_IO", "CLOUDFLARE", "IPREGISTRY",
                   "IPAPI_CO", "IPAPI_COM", "IPWHO_IS", "IP2LOCATION_IO"]
        custom = ["Google", "YouTube", "Twitch", "ChatGPT", "Netflix",
                  "Spotify", "Disney+", "Steam", "Claude"]
        geo = []
        for s in primary:
            geo.append({
                "db": s,
                "ipv4": d.query_primary_geoip(ipv4, s) if ipv4 else "—",
                "ipv6": d.query_primary_geoip(ipv6, s) if (ipv6 and has_v6) else "—",
            })
        services = []
        for s in custom:
            services.append({
                "service": s,
                "ipv4": d.check_custom_service(s, 4, has_v6),
                "ipv6": d.check_custom_service(s, 6, has_v6) if has_v6 else "—",
            })
        return {"ipv4": ipv4, "ipv6": ipv6, "has_ipv6": has_v6,
                "reality_sni": d.get_reality_sni(), "geoip": geo, "services": services}

    return {"task_id": ctx.tasks.start("diag-geoip", _job)}


def cpu_bench(ctx):
    def _job():
        import subprocess
        from hydra.ui import diagnostics as d
        d.ensure_packages(["sysbench"])
        r = subprocess.run(
            ["sysbench", "cpu", "--cpu-max-prime=20000", "--time=10", "run"],
            capture_output=True, text=True, timeout=60)
        out = r.stdout
        events = ""
        for line in out.splitlines():
            if "events per second" in line:
                events = line.split(":")[-1].strip()
        print(out)
        return {"events_per_second": events, "raw": out}

    return {"task_id": ctx.tasks.start("diag-cpu", _job)}


def speedtest(ctx):
    """Лёгкий HTTP speed-тест (без интерактива)."""
    url = str(ctx.get("url", "https://speed.cloudflare.com/__down?bytes=50000000"))

    def _job():
        from hydra.ui import diagnostics as d
        return {"result": d.run_http_speed(url), "url": url}

    return {"task_id": ctx.tasks.start("diag-speedtest", _job)}


ROUTES = [
    ("POST", r"/api/diagnostics/report", full_report),
    ("GET", r"/api/diagnostics/report", report_file),
    ("POST", r"/api/diagnostics/censorcheck", censorcheck),
    ("POST", r"/api/diagnostics/tspu", tspu),
    ("POST", r"/api/diagnostics/geoip", geoip),
    ("POST", r"/api/diagnostics/cpu", cpu_bench),
    ("POST", r"/api/diagnostics/speedtest", speedtest),
]
