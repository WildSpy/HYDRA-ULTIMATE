"""
hydra/plugins/amneziawg/tuning.py — Hardware-aware tuning для VPS.
"""
from __future__ import annotations
import re
import shutil
import subprocess
from pathlib import Path

SYSCTL_TARGETS: dict[str, int | str] = {
    "net.ipv4.ip_forward": 1,
    "net.ipv6.conf.all.forwarding": 1,
    "net.core.default_qdisc": "fq",
    "net.ipv4.tcp_congestion_control": "bbr",
    "net.core.rmem_max": 7500000,
    "net.core.wmem_max": 7500000,
    "net.core.rmem_default": 7500000,
    "net.core.wmem_default": 7500000,
}

SYSCTL_CONF = Path("/etc/sysctl.d/99-hydra-tuning.conf")


def sysctl_get(key: str) -> str:
    """Читает текущее значение sysctl-параметра."""
    try:
        r = subprocess.run(["sysctl", "-n", key], capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def sysctl_set(key: str, value: int | str) -> bool:
    """Применяет значение sysctl (runtime + persistent)."""
    try:
        # Runtime
        r = subprocess.run(["sysctl", "-w", f"{key}={value}"], capture_output=True, text=True)
        if r.returncode != 0:
            return False

        # Persistent
        SYSCTL_CONF.parent.mkdir(parents=True, exist_ok=True)
        existing = SYSCTL_CONF.read_text(encoding="utf-8") if SYSCTL_CONF.exists() else ""
        new_lines = [l for l in existing.splitlines() if not l.strip().startswith(f"{key}=")]
        new_lines.append(f"{key} = {value}")
        SYSCTL_CONF.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        return True
    except Exception:
        return False


def sysctl_apply_idempotent() -> dict:
    """Применяет все целевые sysctl-настройки idempotent-методом."""
    results = {}
    for key, target in SYSCTL_TARGETS.items():
        current = sysctl_get(key)
        # IPv6 forwarding check
        if key == "net.ipv6.conf.all.forwarding":
            ipv6_disable = sysctl_get("net.ipv6.conf.all.disable_ipv6")
            if ipv6_disable == "1":
                results[key] = {"old": current, "new": current, "changed": False, "skipped": "IPv6 disabled on host"}
                continue

        if str(current) == str(target):
            results[key] = {"old": current, "new": current, "changed": False}
            continue

        ok = sysctl_set(key, target)
        results[key] = {
            "old": current,
            "new": str(target) if ok else current,
            "changed": ok
        }
    return results


def detect_ram_mb() -> int:
    """Возвращает размер RAM в МБ."""
    try:
        meminfo = Path("/proc/meminfo").read_text()
        m = re.search(r"^MemTotal:\s+(\d+)\s+kB", meminfo, re.MULTILINE)
        if m:
            return int(m.group(1)) // 1024
    except Exception:
        pass
    return 0


def optimize_swap() -> dict:
    """Подгоняет swap под размер RAM."""
    result = {"ram_mb": 0, "current_swap_mb": 0, "target_swap_mb": 0, "changed": False}

    ram = detect_ram_mb()
    result["ram_mb"] = ram
    if ram == 0:
        return result

    # Текущий swap
    try:
        r = subprocess.run(["swapon", "--show=SIZE", "--bytes", "--noheadings"], capture_output=True, text=True)
        current_swap_bytes = 0
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                line = line.strip()
                if line and line.isdigit():
                    current_swap_bytes += int(line)
        current_swap_mb = current_swap_bytes // (1024 * 1024)
    except Exception:
        current_swap_mb = 0

    result["current_swap_mb"] = current_swap_mb

    # Целевой swap: swap = max(1G, RAM/2) если RAM < 4G; иначе swap = RAM/4
    if ram < 4096:
        target_swap_mb = max(1024, ram // 2)
    else:
        target_swap_mb = ram // 4
    result["target_swap_mb"] = target_swap_mb

    if current_swap_mb >= target_swap_mb:
        return result

    # Создаём/расширяем swap-файл
    swapfile = Path("/swapfile")
    try:
        if swapfile.exists():
            current_size = swapfile.stat().st_size // (1024 * 1024)
            if current_size >= target_swap_mb:
                return result
            subprocess.run(["swapoff", str(swapfile)], capture_output=True)
            swapfile.unlink()

        # fallocate -> chmod -> mkswap -> swapon
        subprocess.run(["fallocate", "-l", f"{target_swap_mb}M", str(swapfile)], capture_output=True)
        subprocess.run(["chmod", "600", str(swapfile)], capture_output=True)
        subprocess.run(["mkswap", str(swapfile)], capture_output=True)
        subprocess.run(["swapon", str(swapfile)], capture_output=True)

        # fstab entry
        fstab = Path("/etc/fstab")
        if fstab.exists():
            fstab_content = fstab.read_text(encoding="utf-8")
            if "/swapfile" not in fstab_content:
                fstab.write_text(fstab_content.rstrip() + "\n/swapfile none swap sw 0 0\n", encoding="utf-8")

        result["changed"] = True
    except Exception:
        pass

    return result


def detect_default_iface() -> str:
    """Возвращает имя интерфейса по умолчанию."""
    try:
        r = subprocess.run(["ip", "route", "show", "default"], capture_output=True, text=True)
        if r.returncode == 0:
            m = re.search(r"\bdev\s+(\S+)", r.stdout)
            if m:
                return m.group(1)
    except Exception:
        pass
    return ""


def optimize_nic() -> dict:
    """Включает GRO/GSO/TSO если они выключены."""
    result = {"iface": "", "changed": [], "skipped": ""}

    iface = detect_default_iface()
    if not iface:
        result["skipped"] = "Не удалось определить default interface"
        return result
    result["iface"] = iface

    if not shutil.which("ethtool"):
        result["skipped"] = "ethtool не установлен"
        return result

    for offload in ("gro", "gso", "tso"):
        try:
            r = subprocess.run(["ethtool", "-k", iface], capture_output=True, text=True)
            if r.returncode != 0:
                continue
            # Ищем статус generic-receive-offload/generic-segmentation-offload/tcp-segmentation-offload
            key_name = offload.replace('gro', 'generic-receive-offload').replace('gso', 'generic-segmentation-offload').replace('tso', 'tcp-segmentation-offload')
            m = re.search(rf"^{key_name}:\s+(\w+)", r.stdout, re.MULTILINE | re.IGNORECASE)
            if m and m.group(1).lower() == "on":
                continue

            subprocess.run(["ethtool", "-K", iface, offload, "on"], capture_output=True)
            result["changed"].append(offload)
        except Exception:
            pass

    return result


def hw_tune_all() -> dict:
    """Применяет все hardware-оптимизации (sysctl + swap + NIC)."""
    return {
        "sysctl": sysctl_apply_idempotent(),
        "swap": optimize_swap(),
        "nic": optimize_nic(),
    }
