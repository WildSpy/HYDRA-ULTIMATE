"""hydra.services.webpanel — веб-панель управления HYDRA.

Дополнительный компонент, устанавливаемый поверх готовой инсталляции HYDRA.
Работает как отдельная systemd-служба (`hydra-webpanel`) и переиспользует
существующее ядро (state / orchestrator / registry / singbox / systemd) — то же
самое, что использует TUI. Панель и TUI разделяют /var/lib/hydra/state.json и
файловую блокировку, поэтому могут использоваться взаимозаменяемо.
"""

__all__ = ["__version__"]

__version__ = "1.0.0"
