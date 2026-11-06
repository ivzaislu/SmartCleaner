# Сборка пакетов SmartCleaner 2.0

Команды выполняются из корня исходного проекта. Используйте отдельную среду Python 3.12+.

## Windows

```powershell
python -m pip install -e .
python -m pip install pyinstaller
python -m PyInstaller --clean smartcleaner.spec
iscc installers\windows\smartcleaner.iss
```

Inno Setup 6 берёт EXE из `dist` и помещает установщик в `installers/windows/output`. Опциональная команда Проводника работает для одного файла. CLI принимает несколько абсолютных путей, каждый как отдельный аргумент в кавычках. Authenticode и сертификат издателя не входят в эту сборку.

## Debian 13

```sh
sh installers/linux/build-deb.sh
dpkg-deb --info smartcleaner_2.0.0_all.deb
dpkg-deb --contents smartcleaner_2.0.0_all.deb
```

Для запуска нужны пакеты из `DEBIAN/control`, в том числе QtWidgets для PySide6. Другие дистрибутивы семейства Debian могут поставлять PySide6 под другим именем.

## Fedora

Скопируйте исходное дерево без кешей и сборочных файлов в каталог `smartcleaner-2.0.0`, затем из его родительского каталога выполните:

```sh
mkdir -p ~/rpmbuild/SOURCES
tar -czf ~/rpmbuild/SOURCES/smartcleaner-2.0.0.tar.gz smartcleaner-2.0.0/
rpmbuild -bb smartcleaner-2.0.0/installers/linux/rpm/smartcleaner.spec
```

## Linux и файловый менеджер

Пакеты поставляют команду `smartcleaner` и меню запуска. Пример скрипта Nautilus находится в `/usr/share/smartcleaner/nautilus`. Его можно разместить в пользовательском каталоге скриптов Nautilus вручную. Он принимает только отдельные аргументы, поэтому при запуске без них безопасно завершится. Автоматической регистрации в Nautilus или других файловых менеджерах нет.

```sh
smartcleaner --delete "/absolute/path/file one.tmp" "/absolute/path/file two.tmp"
```

Удаление пакета средствами ОС оставляет пользовательское состояние в каталоге профиля. При обновлении с прежней версии старые интеграции, созданные вне учёта пакетов, нужно проверять отдельно.

`python installers/validate_installers.py` проверяет согласованность исходных шаблонов. Сборка пакетов и сценарии установки и деинсталляции проверяются отдельно на целевых ОС.
