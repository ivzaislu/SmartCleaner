import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from smartcleaner import gui


class ConfirmationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_cancel_and_confirm_with_spaces_and_unicode(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "cache тест.tmp"
            path.write_bytes(b"test")
            window = gui.SmartCleanerMainWindow(root)
            self.assertEqual(window.content_stack.count(), window.sidebar.count())

            def respond(role):
                dialog = QApplication.activeModalWidget()
                if isinstance(dialog, QMessageBox):
                    button = next(button for button in dialog.buttons()
                                  if dialog.buttonRole(button) == role)
                    button.click()

            QTimer.singleShot(20, lambda: respond(QMessageBox.ButtonRole.RejectRole))
            self.assertEqual(window._confirm_move([str(path)]), 1)
            self.assertTrue(path.exists())

            QTimer.singleShot(20, lambda: respond(QMessageBox.ButtonRole.AcceptRole))
            with patch.object(QMessageBox, "information"):
                self.assertEqual(window._confirm_move([str(path)]), 0)
            self.assertFalse(path.exists())
            self.assertEqual(len(window.logger.get_quarantine_items()), 1)
            window.close()

    def test_cli_routes_all_arguments_to_confirmation(self):
        files = [str(Path.cwd() / name) for name in ("space one.tmp", "space two.tmp")]
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(gui, "QApplication", return_value=self.app), \
                    patch.object(gui, "user_state_dir", return_value=Path(temp)), \
                    patch.object(gui.SmartCleanerMainWindow, "_confirm_move", return_value=1) as confirm:
                self.assertEqual(gui.main(["--delete", *files]), 1)
            confirm.assert_called_once_with(files)
