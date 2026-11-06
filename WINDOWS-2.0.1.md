# SmartCleaner 2.0.1 для Windows

Подключены разделы анализа места, дубликатов, крупных и старых файлов, кеша известных приложений, возможных остатков, драйверов, физических накопителей, автозагрузки, программ, истории, диагностики и планировщика. Настройки можно экспортировать и импортировать.

- Анализ места показывает размеры и доли до 50 элементов выбранной папки. Двойной щелчок по папке запускает вложенный анализ.
- Список кешей ограничен известными папками Discord, VS Code, классического Teams и NVIDIA. Кандидаты на остатки определяются по отсутствию записи об известной программе. Их можно просмотреть.
- Автозагрузка, удаление приложений и обновление драйверов управляются в соответствующих разделах Windows. SmartCleaner отображает данные инвентаризации и открывает эти разделы.
- Диагностика вызывает SFC /verifyonly, DISM /CheckHealth и CHKDSK без флагов исправления. Кнопки показывают вывод и код завершения. Windows может потребовать повышенные права. [SFC](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/sfc), [CHKDSK](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/chkdsk), [DISM](https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/repair-a-windows-image)
- Данные SSD/HDD зависят от контроллера и поставщика хранилища. [Get-PhysicalDisk](https://learn.microsoft.com/en-us/powershell/module/storage/get-physicaldisk)
- Планировщик выполняет анализ при открытом SmartCleaner. Выбранные для очистки файлы проходят прежние проверки и подтверждение карантина. Карантин не освобождает место и работает в пределах одного тома.
- Состояние установленной версии находится в %LOCALAPPDATA%\SmartCleaner. Портативная версия использует SmartCleaner-data рядом с EXE. При обновлении портативной версии оставьте её рядом с новым файлом.

## Сборка Windows

После установки зависимостей проекта и PyInstaller выполните из корня исходников в чистой среде, где PATH не содержит сторонних Qt или ICU:

    python -m PyInstaller --noconfirm smartcleaner.spec
    iscc installers\windows\smartcleaner.iss
    python -m PyInstaller --noconfirm --name SmartCleaner-2.0.1-Portable --windowed --onefile --noupx portable_entry.py

Тесты выполняются командой `python -m pytest -q`. В Windows 10 x64 прошли 46 тестов. Три теста пропущены из-за отсутствия разрешения на создание символических ссылок. Реальная инвентаризация драйверов, автозагрузки, программ и физических дисков проверена. Запуск SFC, DISM и CHKDSK на реальном диске в этот прогон не входил.
