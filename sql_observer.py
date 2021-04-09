import sqlite3
import logging


class SQL:
    def __init__(self, path):
        self.path = path
        self._connection = None

        self.connect()
        self.create_database()

    def connect(self, path=""):
        logging.info("SQL.connect()")
        if path:
            self._connection = sqlite3.connect(path, check_same_thread=False)
        else:
            self._connection = sqlite3.connect(self.path, check_same_thread=False)

    def close(self):
        logging.info("SQL.close()")
        self._connection.close()

    def create_database(self):
        logging.info("SQL.create_database()")
        cursor = self._connection.cursor()

        def create_stats():
            cursor.execute("""CREATE TABLE "stats" (
                            "timestamp"	INTEGER,
                            "base"	TEXT,
                            "rates"	TEXT
                            )""")

        cursor.execute("SELECT name FROM sqlite_master")
        data = cursor.fetchall()
        if not data:
            create_stats()
        else:
            tables = [i[0] for i in data]
            if "stats" not in tables:
                create_stats()

        cursor.close()
        # self._connection.close()

    def save_rates(self, timestamp, base, rates):
        logging.info("SQL.save_rates()")
        cursor = self._connection.cursor()

        cursor.execute("""
                INSERT INTO 'stats' ("timestamp", "base", "rates")
                VALUES ({timestamp}, "{base}", "{rates}")
                """.format(timestamp=timestamp, base=base, rates=rates))
        self._connection.commit()

        cursor.close()

    def get_last_rates(self, timestamp):
        logging.info("SQL.get_last_rates()")
        cur = self._connection.cursor()

        cur.execute(f"""SELECT max(timestamp), base, rates FROM stats WHERE "timestamp" > {timestamp}""")
        _parameters = cur.fetchall()
        self._connection.commit()
        cur.close()
        return _parameters[0][2]

    def set_sql(self, sql_request):
        logging.info("SQL.set_sql()")
        cursor = self._connection.cursor()

        cursor.execute(sql_request)
        self._connection.commit()

        cursor.close()

    def get_sql(self, sql_request):
        logging.info("SQL.get_sql()")
        cur = self._connection.cursor()

        cur.execute(sql_request)
        _parameters = cur.fetchall()
        self._connection.commit()

        cur.close()
        return _parameters

