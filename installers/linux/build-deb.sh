#!/bin/sh
# Run from the source root on Debian. Only stages files in a new temp directory.
set -eu
stage=$(mktemp -d)
trap 'rm -rf -- "$stage"' EXIT
install -Dm644 installers/linux/debian/DEBIAN/control "$stage/DEBIAN/control"
install -Dm755 installers/linux/smartcleaner "$stage/usr/bin/smartcleaner"
install -Dm644 smartcleaner.desktop "$stage/usr/share/applications/smartcleaner.desktop"
install -d "$stage/usr/share/smartcleaner/smartcleaner"
install -m644 smartcleaner/*.py "$stage/usr/share/smartcleaner/smartcleaner/"
install -Dm755 "installers/linux/rpm/nautilus-scripts/Delete via SmartCleaner" "$stage/usr/share/smartcleaner/nautilus/Delete via SmartCleaner"
chmod 0755 "$stage"
dpkg-deb --root-owner-group --build "$stage" "${1:-smartcleaner_2.0.0_all.deb}"
