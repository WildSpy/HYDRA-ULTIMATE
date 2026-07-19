# Выпуск HYDRA

Релиз создаётся только из проверенного коммита ветки `main`.

1. Перенесите записи из `Unreleased` в секцию новой версии `CHANGELOG.md`.
2. Обновите `hydra.__version__`, заголовок и badge версии в `README.md`.
3. Выполните локальные проверки:

   ```bash
   python -m ruff check main.py hydra tests .github/scripts/release_notes.py
   python -m pytest -q
   ```

4. После зелёного CI создайте и отправьте тег:

   ```bash
   git tag -a vX.Y.Z -m "HYDRA X.Y.Z"
   git push origin vX.Y.Z
   ```

Workflow `Release` проверит тег на Python 3.10–3.13, извлечёт соответствующую секцию из `CHANGELOG.md` и создаст GitHub Release. Несовпадение тега, `hydra.__version__` или changelog останавливает публикацию.
