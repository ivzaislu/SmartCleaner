# SmartCleaner

SmartCleaner — утилита для анализа дисков, обратимой очистки файлов и диагностики Windows. Текущая версия исходников — **2.0.2**.

- Анализ использования места, поиск дубликатов, больших и старых файлов.
- Просмотр кеша браузеров и поддерживаемых приложений, исключения, карантин и восстановление.
- Инвентаризация устройств, драйверов и программ, проверка предложений Windows Update для текущего оборудования.

Выбранные файлы перемещаются в карантин после подтверждения. Карантин остаётся на том же томе, а восстановление сохраняет файл, уже находящийся по исходному пути.

## Запуск из исходников на Windows

Откройте PowerShell в корне репозитория. Требуется Python 3.12 или новее.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m smartcleaner.gui
```

## Тесты

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m pytest -q
```

Тесты очистки используют временные файлы. Предложения Windows Update в тестах имитируются.

## Сборка Windows EXE

Установите PyInstaller в ту же среду. Для сборки используйте PATH без сторонних библиотек Qt и ICU. Для создания установщика требуется Inno Setup.

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm smartcleaner.spec
iscc installers\windows\smartcleaner.iss
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --name SmartCleaner-2.0.2-Portable --windowed --onefile --noupx portable_entry.py
```

Установленная версия хранит данные в `%LOCALAPPDATA%\SmartCleaner`, портативная — в `SmartCleaner-data` рядом с EXE. Подробности о проверке обновлений описаны в [заметках о версии 2.0.2](WINDOWS-2.0.2.md).
