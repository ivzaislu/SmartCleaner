Name: smartcleaner
Version: 2.0.0
Release: 1%{?dist}
Summary: SmartCleaner file cleanup and disk analysis
License: MIT
Source0: smartcleaner-2.0.0.tar.gz
BuildArch: noarch
BuildRequires: python3-devel
Requires: python3 >= 3.12
Requires: python3-pyside6
Requires: python3-psutil
Requires: python3-cryptography >= 42

%description
SmartCleaner provides disk analysis and moves selected files to a reversible quarantine.

%prep
%autosetup

%install
install -Dm755 installers/linux/smartcleaner %{buildroot}%{_bindir}/smartcleaner
install -Dm644 smartcleaner.desktop %{buildroot}%{_datadir}/applications/smartcleaner.desktop
install -d %{buildroot}%{_datadir}/smartcleaner/smartcleaner
install -m644 smartcleaner/*.py %{buildroot}%{_datadir}/smartcleaner/smartcleaner/
install -Dm755 "installers/linux/rpm/nautilus-scripts/Delete via SmartCleaner" "%{buildroot}%{_datadir}/smartcleaner/nautilus/Delete via SmartCleaner"

%files
%{_bindir}/smartcleaner
%{_datadir}/smartcleaner/
%{_datadir}/applications/smartcleaner.desktop
