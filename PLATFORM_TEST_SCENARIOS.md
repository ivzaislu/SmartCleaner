# SmartCleaner 2.0 — Platform Testing Scenarios

Reproducible test scenarios for Windows 10, Windows 11, Ubuntu, Debian, Fedora, and Linux Mint.
Tests are NOT marked as passed unless executed on the target platform.

## Common Test Categories

### A. Installation
1. Clean install from Windows Setup.exe / DEB / RPM.
2. First launch after installation.
3. Update over previous version.
4. Uninstall and verify removal of shortcuts, context menus, and registry entries.
5. Verify no privileged background components remain after uninstall.

### B. GUI
1. All 19 sections open without errors.
2. Theme switching (light/dark) works.
3. Language switching (RU/EN) works.
4. File tree with checkboxes supports partial selection.
5. Browser profiles selectable individually.
6. Individual file exclusion works.
7. Partial folder selection works.
8. Clean preview shows real sizes and counts.
9. Progress indicators work during scan/clean.
10. Cancellation stops operations gracefully.

### C. Safe Cleaning
1. Browser passwords, cookies, sessions, bookmarks preserved after cache clean.
2. User exclusions respected recursively.
3. System files protected from deletion.
4. Symlink attacks blocked.
5. Path traversal blocked.
6. Protected file types (documents, media, keys) not deleted automatically.

### D. Disk Analysis
1. Treemap renders folder sizes correctly.
2. Duplicate finder identifies SHA-256 duplicates.
3. Hard links handled correctly.
4. Large file finder filters by size/extension/date.

### E. SmartCleaner Delete
1. Context menu entry appears in Windows Explorer / Nautilus / Dolphin / Nemo / Thunar.
2. Separate window opens with object list.
3. Lock/permission diagnostics shown.
4. Confirmation required before deletion.
5. Long paths handled.
6. Blocked files skipped with error message.

### F. Drivers
1. Windows Update driver check works.
2. OEM provider links shown when no supported mechanism exists.
3. APT/DNF driver updates work on Linux.
4. fwupd firmware updates detected.
5. Incompatible drivers not installed.
6. Unsigned packages rejected.

### G. System Diagnostics
1. SMART/NVMe data read via smartctl.
2. SFC/DISM status shown on Windows.
3. dpkg-query / rpm -Va verification on Linux.
4. CHKDSK / fsck warnings shown before execution.

### H. Startup & Installed Apps
1. Startup items detected (Windows Startup folder, Linux XDG Autostart).
2. Disable and restore works.
3. System services not disabled automatically.
4. Installed applications listed with version/publisher.
5. Native uninstaller launched on request.

### I. History & Recovery
1. Operations logged to SQLite.
2. Quarantine items recoverable.
3. Name conflicts handled.
4. Insufficient space errors shown.

---

## Platform-Specific Scenarios

### Windows 10 x64
- [ ] Installer runs as administrator.
- [ ] Context menu registered in Explorer.
- [ ] SFC /scannow and DISM available.
- [ ] Windows Update driver check via WUA API.
- [ ] Startup folder and Run/RunOnce keys detected.

### Windows 11 x64
- [ ] Context menu appears in "Show more options" (additional parameters).
- [ ] Windows 11-specific driver sources checked.
- [ ] Dark theme renders correctly.

### Ubuntu LTS
- [ ] DEB package installs via dpkg/apt.
- [ ] Nautilus context menu action registered.
- [ ] APT cache cleaning works.
- [ ] fwupd firmware updates detected.
- [ ] XDG Autostart entries managed.

### Debian Stable
- [ ] DEB package installs via dpkg/apt.
- [ ] dpkg-query package verification works.
- [ ] XFCE / GNOME desktop integration tested.

### Fedora
- [ ] RPM package installs via dnf.
- [ ] DNF cache cleaning works.
- [ ] fwupd firmware updates detected.
- [ ] GNOME desktop integration tested.

### Linux Mint
- [ ] DEB package installs via apt.
- [ ] Cinnamon desktop integration tested.
- [ ] Nemo context menu action registered.

---

## Test Execution Instructions

1. Deploy SmartCleaner 2.0 source to target machine.
2. Install dependencies: `pip install -r requirements.txt`
3. Run GUI: `python3 -m smartcleaner.gui`
4. Execute each scenario above and record:
   - Date
   - OS version
   - Result (Pass/Fail/Blocked)
   - Issues found
