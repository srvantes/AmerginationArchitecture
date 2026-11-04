import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch


SPEC = importlib.util.spec_from_file_location("restore_database", Path(__file__).parents[1] / "deploy" / "restore_database.py")
database = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(database)
SUFFIX = "a" * 32
STAGING, PREVIOUS = database.STAGING_PREFIX + SUFFIX, database.PREVIOUS_PREFIX + SUFFIX


class Transaction:
    def __init__(self, connection, *, fail_commit=False):
        self.connection = connection
        self.fail_commit = fail_commit

    async def __aenter__(self):
        self.connection.in_transaction = True

    async def __aexit__(self, kind, error, trace):
        self.connection.in_transaction = False
        if self.fail_commit and kind is None:
            raise ConnectionError("ambiguous commit")
        return False


class Connection:
    def __init__(self, *, owner="app-user", fail_second_rename=False, fail_commit=False, switched_names=False):
        self.in_transaction = False
        self.operations = []
        self.fetchrow = AsyncMock(side_effect=lambda query, name: {
            "oid": 100 if name == 'app"db' else 200, "datname": name, "datallowconn": True, "owner": owner,
        })
        self.fetchval = AsyncMock(return_value=False)
        self.fetch = AsyncMock(side_effect=lambda query, args: [] if "pg_terminate_backend" in query else [
            {"oid": 100, "datname": PREVIOUS if switched_names else 'app"db'},
            {"oid": 200, "datname": 'app"db' if switched_names else STAGING},
        ])
        self.transaction = lambda: Transaction(self, fail_commit=fail_commit)

        async def execute(query):
            self.operations.append((query, self.in_transaction))
            if fail_second_rename and query.startswith(f'ALTER DATABASE "{STAGING}" RENAME'):
                raise RuntimeError("second rename failed")

        self.execute = AsyncMock(side_effect=execute)


class RestoreDatabaseTests(unittest.IsolatedAsyncioTestCase):
    def test_identifiers_are_quoted_as_a_whole_and_long_or_nul_names_are_refused(self):
        self.assertEqual(database.identifier('db";DROP DATABASE target;--'), '"db"";DROP DATABASE target;--"')
        for value in ["", "x\0y", "x" * 64, "я" * 32]:
            with self.subTest(value=value), self.assertRaises(database.RestoreError):
                database.identifier(value)

    def test_restore_can_only_target_compose_application_database(self):
        for name in ["postgres", "template0", "template1"]:
            with patch.dict(os.environ, {"POSTGRES_DB": name, "POSTGRES_USER": "app-user", "POSTGRES_HOST": "postgres"}, clear=True):
                with self.assertRaises(database.RestoreError):
                    database.configured_target()
        with patch.dict(os.environ, {"POSTGRES_DB": "app", "POSTGRES_USER": "app-user", "POSTGRES_HOST": "external.example"}, clear=True):
            with self.assertRaises(database.RestoreError):
                database.configured_target()

    async def test_prepare_uses_pristine_template_and_never_drops_current_database(self):
        connection = Connection()
        staging, previous = await database.prepare(connection, 'app"db', "app-user")
        self.assertRegex(staging, r"^amergination_restore_[a-f0-9]{32}$")
        self.assertEqual(previous, database.PREVIOUS_PREFIX + staging.removeprefix(database.STAGING_PREFIX))
        query = connection.operations[0][0]
        self.assertIn('TEMPLATE template0 OWNER "app-user"', query)
        self.assertFalse(any("DROP " in query for query, _ in connection.operations))

    async def test_switch_blocks_connections_then_renames_both_databases_in_one_transaction(self):
        connection = Connection()
        await database.switch(connection, 'app"db', "app-user", STAGING, PREVIOUS)
        self.assertEqual(connection.operations[0], ('ALTER DATABASE "app""db" ALLOW_CONNECTIONS false', False))
        self.assertEqual(connection.operations[1], (f'ALTER DATABASE "{STAGING}" ALLOW_CONNECTIONS false', False))
        renames = [(query, inside) for query, inside in connection.operations if "RENAME TO" in query]
        self.assertEqual(len(renames), 2)
        self.assertTrue(all(inside for _, inside in renames))
        self.assertIn(f'RENAME TO "{PREVIOUS}"', renames[0][0])
        self.assertIn('RENAME TO "app""db"', renames[1][0])
        self.assertEqual(connection.operations[-1], ('ALTER DATABASE "app""db" ALLOW_CONNECTIONS true', True))
        query, names = connection.fetch.await_args.args
        self.assertIn("datname = ANY($1::text[])", query)
        self.assertEqual(names, ['app"db', STAGING])
        self.assertFalse(any("DROP " in query for query, _ in connection.operations))

    async def test_sql_failure_recovers_initial_connection_flags_when_oid_names_are_unchanged(self):
        connection = Connection(fail_second_rename=True)
        with self.assertRaisesRegex(RuntimeError, "second rename"):
            await database.switch(connection, 'app"db', "app-user", STAGING, PREVIOUS)
        self.assertEqual(connection.operations[-2:], [
            ('ALTER DATABASE "app""db" ALLOW_CONNECTIONS true', False),
            (f'ALTER DATABASE "{STAGING}" ALLOW_CONNECTIONS true', False),
        ])

    async def test_ambiguous_commit_never_changes_flags_by_a_reused_database_name(self):
        connection = Connection(fail_commit=True, switched_names=True)
        with self.assertRaisesRegex(ConnectionError, "ambiguous commit"):
            await database.switch(connection, 'app"db', "app-user", STAGING, PREVIOUS)
        self.assertEqual(sum(query == 'ALTER DATABASE "app""db" ALLOW_CONNECTIONS true' for query, _ in connection.operations), 1)
        self.assertFalse(any(query == f'ALTER DATABASE "{STAGING}" ALLOW_CONNECTIONS true' for query, _ in connection.operations))

    async def test_foreign_owner_or_invalid_generated_pair_cannot_mutate_a_database(self):
        for connection, staging, previous in [(Connection(owner="other"), STAGING, PREVIOUS),
                                              (Connection(), "unrelated_database", PREVIOUS),
                                              (Connection(), STAGING, "other_rollback")]:
            with self.assertRaises(database.RestoreError):
                await database.switch(connection, 'app"db', "app-user", staging, previous)
            connection.execute.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
