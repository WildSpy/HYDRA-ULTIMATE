#!/usr/bin/env bash
#
# install-webpanel.sh — установка веб-панели HYDRA поверх готовой инсталляции.
#
# Панель — дополнительный компонент. Он НЕ трогает существующую конфигурацию
# (state.json, sing-box, плагины), а лишь добавляет:
#   • systemd-службу hydra-webpanel
#   • файл настроек /var/lib/hydra/webpanel.json (логин/пароль/bind)
# TUI (`hydra`) продолжает работать как прежде; панель и TUI используют один
# и тот же state.json с общей блокировкой.
#
# Запуск:  sudo bash install-webpanel.sh
#
set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
info(){ echo -e "${CYAN}[*]${NC} $*"; }
ok(){ echo -e "${GREEN}[+]${NC} $*"; }
warn(){ echo -e "${YELLOW}[!]${NC} $*"; }
err(){ echo -e "${RED}[x]${NC} $*" >&2; }

# ── 1. Проверки ──────────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then err "Запустите от root: sudo bash install-webpanel.sh"; exit 1; fi
if ! command -v python3 >/dev/null 2>&1; then err "python3 не найден"; exit 1; fi
PYV=$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])')
info "Python: $PYV"

# ── 2. Поиск каталога установки HYDRA ────────────────────────────────────────
INSTALL_DIR=""
for c in /opt/hydra /opt/HYDRA-ULTIMATE /root/HYDRA-ULTIMATE "$(cd "$(dirname "$0")" && pwd)"; do
  if [[ -f "$c/main.py" && -d "$c/hydra" ]]; then INSTALL_DIR="$c"; break; fi
done
if [[ -z "$INSTALL_DIR" ]]; then
  err "Не найден каталог установки HYDRA (ожидались main.py и hydra/)."
  err "Установите основную платформу через bootstrap.sh, затем повторите."
  exit 1
fi
ok "HYDRA найдена в: $INSTALL_DIR"

# Проверяем импортируемость пакета webpanel
if ! PYTHONPATH="$INSTALL_DIR" python3 -c "import hydra.services.webpanel.server" 2>/dev/null; then
  err "Пакет hydra.services.webpanel не импортируется. Обновите репозиторий HYDRA."
  exit 1
fi
ok "Пакет веб-панели доступен"

# ── 3. Зависимости (best-effort, всё опционально/stdlib) ─────────────────────
# qrcode — для QR-кодов (уже нужен основной платформе); psutil — для метрик.
if command -v pip3 >/dev/null 2>&1; then
  info "Установка опциональных зависимостей (qrcode, psutil)…"
  pip3 install -q qrcode psutil 2>/dev/null || warn "pip3: часть пакетов не установлена (не критично)"
fi

# ── 4. Пароль администратора ─────────────────────────────────────────────────
ADMIN_USER="${HYDRA_PANEL_USER:-admin}"
if [[ -n "${HYDRA_PANEL_PASSWORD:-}" ]]; then
  PYTHONPATH="$INSTALL_DIR" python3 -m hydra.services.webpanel.auth set-password \
    --username "$ADMIN_USER" "$HYDRA_PANEL_PASSWORD"
else
  info "Задайте логин/пароль администратора панели."
  read -r -p "Логин [$ADMIN_USER]: " u; ADMIN_USER="${u:-$ADMIN_USER}"
  PYTHONPATH="$INSTALL_DIR" python3 -m hydra.services.webpanel.auth set-password --username "$ADMIN_USER"
fi
ok "Учётные данные сохранены"

# ── 5. Режим доступа ─────────────────────────────────────────────────────────
PORT="${HYDRA_PANEL_PORT:-8088}"
MODE="${HYDRA_PANEL_MODE:-}"
if [[ -z "$MODE" ]]; then
  echo
  echo "  Режим доступа к панели:"
  echo "    1) Только localhost (127.0.0.1) — доступ через SSH-туннель (безопаснее)"
  echo "    2) Публичный HTTPS (0.0.0.0)   — вход по логину/паролю из интернета"
  read -r -p "  Выбор [1]: " m; m="${m:-1}"
  [[ "$m" == "2" ]] && MODE="public" || MODE="local"
fi
read -r -p "  Порт панели [$PORT]: " p; PORT="${p:-$PORT}"

if [[ "$MODE" == "public" ]]; then
  HOST="0.0.0.0"; TLS_FLAG="--tls"
  # Открываем порт в фаерволе
  PYTHONPATH="$INSTALL_DIR" python3 - "$PORT" <<'PY' || true
import sys
from hydra.utils import firewall
firewall.open_tcp(int(sys.argv[1]), "hydra-webpanel"); firewall.persist()
print("firewall: TCP", sys.argv[1], "open")
PY
  # Самоподписанный сертификат, если нет сертификата HYDRA
  CERT_DIR="/etc/hydra/webpanel"; mkdir -p "$CERT_DIR"
  if [[ ! -f "$CERT_DIR/cert.pem" ]]; then
    info "Генерация self-signed сертификата…"
    openssl req -x509 -newkey rsa:2048 -nodes -keyout "$CERT_DIR/key.pem" \
      -out "$CERT_DIR/cert.pem" -days 3650 -subj "/CN=hydra-panel" 2>/dev/null || warn "openssl недоступен — TLS будет отключён"
  fi
  if [[ -f "$CERT_DIR/cert.pem" ]]; then
    PYTHONPATH="$INSTALL_DIR" python3 -m hydra.services.webpanel.auth configure \
      --host "$HOST" --port "$PORT" --tls --cert "$CERT_DIR/cert.pem" --key "$CERT_DIR/key.pem"
  else
    PYTHONPATH="$INSTALL_DIR" python3 -m hydra.services.webpanel.auth configure --host "$HOST" --port "$PORT" --no-tls
  fi
else
  HOST="127.0.0.1"
  PYTHONPATH="$INSTALL_DIR" python3 -m hydra.services.webpanel.auth configure --host "$HOST" --port "$PORT" --no-tls
fi
ok "Bind: $HOST:$PORT (режим: $MODE)"

# ── 6. systemd-служба ────────────────────────────────────────────────────────
UNIT=/etc/systemd/system/hydra-webpanel.service
info "Создание службы hydra-webpanel…"
cat > "$UNIT" <<EOF
[Unit]
Description=HYDRA Web Panel
After=network.target
Wants=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
Environment=PYTHONPATH=$INSTALL_DIR
ExecStart=/usr/bin/python3 -m hydra.services.webpanel
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable hydra-webpanel >/dev/null 2>&1 || true
systemctl restart hydra-webpanel

sleep 1
if systemctl is-active --quiet hydra-webpanel; then
  ok "Служба hydra-webpanel запущена"
else
  err "Служба не запустилась. Логи: journalctl -u hydra-webpanel -n 40 --no-pager"
  exit 1
fi

# ── 7. Итог ──────────────────────────────────────────────────────────────────
SCHEME="http"; [[ "$MODE" == "public" && -f "/etc/hydra/webpanel/cert.pem" ]] && SCHEME="https"
echo
ok "Веб-панель HYDRA установлена!"
if [[ "$MODE" == "local" ]]; then
  echo -e "  Доступ (через SSH-туннель):"
  echo -e "    ${CYAN}ssh -L $PORT:127.0.0.1:$PORT root@<server-ip>${NC}"
  echo -e "    затем откройте: ${CYAN}http://127.0.0.1:$PORT${NC}"
else
  PUB=$(PYTHONPATH="$INSTALL_DIR" python3 -c "from hydra.utils.net import public_ip; print(public_ip())" 2>/dev/null || echo "<server-ip>")
  echo -e "    Откройте: ${CYAN}${SCHEME}://${PUB}:$PORT${NC}"
fi
echo -e "  Логин: ${CYAN}${ADMIN_USER}${NC}"
echo -e "  Управление службой: systemctl {status|restart|stop} hydra-webpanel"
echo -e "  Сменить пароль:  python3 -m hydra.services.webpanel.auth set-password"
