from __future__ import annotations

import os
import unittest
from uuid import uuid4

from PySide6.QtNetwork import QLocalServer
from PySide6.QtWidgets import QApplication

import main
from main import _release_instance_lock, claim_single_instance


class SingleInstanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.original_server_name = main.SERVER_NAME
        main.SERVER_NAME = f"{self.original_server_name}.{uuid4().hex}"

    def tearDown(self):
        QLocalServer.removeServer(main.SERVER_NAME)
        main.SERVER_NAME = self.original_server_name

    @unittest.skipUnless(os.name == "nt", "Проверка mutex предназначена для Windows")
    def test_second_launch_forwards_command_to_the_first_instance(self):
        primary, server, lock = claim_single_instance("show")
        self.assertTrue(primary)
        self.assertIsNotNone(server)
        self.assertIsNotNone(lock)
        try:
            received = []

            def handle_connection():
                while server.hasPendingConnections():
                    socket = server.nextPendingConnection()
                    def handle_data(current=socket):
                        received.append(bytes(current.readAll()).decode("utf-8").strip())
                        current.write(b"ok")
                        current.flush()
                        current.disconnectFromServer()
                    socket.readyRead.connect(handle_data)
                    if socket.bytesAvailable():
                        handle_data()

            server.newConnection.connect(handle_connection)
            secondary, secondary_server, secondary_lock = claim_single_instance("create")
            self.assertFalse(secondary)
            self.assertIsNone(secondary_server)
            self.assertIsNone(secondary_lock)
            self.assertEqual(received, ["create"])
        finally:
            server.close()
            _release_instance_lock(lock)


if __name__ == "__main__":
    unittest.main()
