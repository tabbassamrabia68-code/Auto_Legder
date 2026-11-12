from psycopg2 import sql
from psycopg2.extras import RealDictCursor


def insert_ledger_record(connection, table_name: str, id_column: str, values: dict, user_id: int) -> int:
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.user_id', %s, true)", (str(user_id),))
        statement = sql.SQL("INSERT INTO {} ({}) VALUES ({}) RETURNING {}").format(
            sql.Identifier(table_name),
            sql.SQL(", ").join(sql.Identifier(column) for column in values),
            sql.SQL(", ").join(sql.Placeholder() for _ in values),
            sql.Identifier(id_column),
        )
        cursor.execute(statement, list(values.values()))
        return cursor.fetchone()[0]


def get_ledger_record(connection, table_name: str, id_column: str, record_id: int):
    statement = sql.SQL("SELECT * FROM {} WHERE {} = %s").format(
        sql.Identifier(table_name),
        sql.Identifier(id_column),
    )
    with connection.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(statement, (record_id,))
        return cursor.fetchone()


def update_ledger_record(connection, table_name: str, id_column: str, record_id: int, values: dict, user_id: int):
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.user_id', %s, true)", (str(user_id),))
        assignments = sql.SQL(", ").join(
            sql.SQL("{} = {}").format(sql.Identifier(column), sql.Placeholder())
            for column in values
        )
        statement = sql.SQL("UPDATE {} SET {} WHERE {} = %s RETURNING {}").format(
            sql.Identifier(table_name),
            assignments,
            sql.Identifier(id_column),
            sql.Identifier(id_column),
        )
        cursor.execute(statement, [*values.values(), record_id])
        result = cursor.fetchone()
        return result[0] if result else None


def delete_ledger_record(connection, table_name: str, id_column: str, record_id: int, user_id: int):
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.user_id', %s, true)", (str(user_id),))
        statement = sql.SQL("DELETE FROM {} WHERE {} = %s RETURNING {}").format(
            sql.Identifier(table_name),
            sql.Identifier(id_column),
            sql.Identifier(id_column),
        )
        cursor.execute(statement, (record_id,))
        return cursor.fetchone()