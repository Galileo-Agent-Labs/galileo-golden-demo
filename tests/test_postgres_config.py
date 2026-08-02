import os
import unittest
from unittest.mock import patch

from helpers.pgvector_utils import get_postgres_connection_string


class PostgresConfigurationTests(unittest.TestCase):
    def test_full_url_is_normalized_for_psycopg_and_tls(self):
        with patch.dict(
            os.environ,
            {
                "POSTGRES_URL": "postgresql://demo:secret@db.example.com/evercrest",
                "POSTGRES_SSLMODE": "",
            },
            clear=False,
        ):
            connection = get_postgres_connection_string()

        self.assertTrue(connection.startswith("postgresql+psycopg://"))
        self.assertIn("sslmode=require", connection)

    def test_url_takes_precedence_over_local_parts(self):
        with patch.dict(
            os.environ,
            {
                "POSTGRES_URL": "postgresql://demo:secret@db.example.com/evercrest",
                "POSTGRES_HOST": "localhost",
                "POSTGRES_PASSWORD": "local-password",
            },
            clear=False,
        ):
            connection = get_postgres_connection_string()

        self.assertIn("db.example.com", connection)
        self.assertNotIn("localhost", connection)


if __name__ == "__main__":
    unittest.main()
