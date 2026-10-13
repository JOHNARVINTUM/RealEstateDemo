#!/usr/bin/env python3
"""
Convert a SQLite database file `db.sqlite3` into a PostgreSQL-compatible
SQL script `postgres_export.sql` (schema + INSERTs).

Usage: python sqlite_to_postgres.py

This script lives in the project root and expects `db.sqlite3` next to it.
"""
import sqlite3
import re
import os
from datetime import datetime

SRC_DB = os.path.join(os.path.dirname(__file__), "db.sqlite3")
OUT_SQL = os.path.join(os.path.dirname(__file__), "postgres_export.sql")

TYPE_MAP = [
    (re.compile(r"INT", re.I), "INTEGER"),
    (re.compile(r"CHAR|CLOB|TEXT", re.I), "TEXT"),
    (re.compile(r"BLOB", re.I), "BYTEA"),
    (re.compile(r"REAL|FLOA|DOUB", re.I), "DOUBLE PRECISION"),
    (re.compile(r"NUMERIC|DECIMAL", re.I), "NUMERIC"),
]

def pg_type(sqlite_type):
    if not sqlite_type:
        return "TEXT"
    for pattern, pg in TYPE_MAP:
        if pattern.search(sqlite_type):
            return pg
    return "TEXT"

def quote_ident(name):
    return '"' + name.replace('"', '""') + '"'

def quote_value(v):
    if v is None:
        return 'NULL'
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    s = s.replace("'", "''")
    return "'" + s + "'"

def main():
    if not os.path.exists(SRC_DB):
        print(f"Source DB not found: {SRC_DB}")
        return

    conn = sqlite3.connect(SRC_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    tables = []
    cur.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
    for row in cur.fetchall():
        tables.append({'name': row['name'], 'sql': row['sql']})

    lines = []
    lines.append("-- PostgreSQL export generated from SQLite on %s" % datetime.utcnow().isoformat())
    lines.append("BEGIN;")
    lines.append('')

    for t in tables:
        name = t['name']
        cur.execute(f"PRAGMA table_info('{name}')")
        cols = cur.fetchall()
        cur.execute(f"PRAGMA foreign_key_list('{name}')")
        fks = cur.fetchall()

        col_defs = []
        pk_cols = [c['name'] for c in cols if c['pk']]

        for c in cols:
            colname = c['name']
            ctype = c['type'] or ''
            notnull = c['notnull']
            dflt = c['dflt_value']
            is_pk = bool(c['pk'])

            # Detect integer primary key -> SERIAL
            if is_pk and re.search(r"INT", ctype, re.I):
                # Use SERIAL for auto-increment integer PK
                col_def = f"{quote_ident(colname)} SERIAL"
                # If composite PK, don't set SERIAL for all; fallback handled below
                if len(pk_cols) == 1:
                    col_def += " PRIMARY KEY"
            else:
                mapped = pg_type(ctype)
                col_def = f"{quote_ident(colname)} {mapped}"
                if is_pk and len(pk_cols) == 1:
                    col_def += " PRIMARY KEY"

            if notnull and not is_pk:
                col_def += " NOT NULL"
            if dflt is not None:
                # sqlite default may include surrounding parentheses or single quotes
                d = str(dflt)
                d = d.strip()
                # Remove surrounding parens
                if d.startswith('(') and d.endswith(')'):
                    d = d[1:-1]
                col_def += " DEFAULT " + d

            col_defs.append(col_def)

        # Build foreign key constraints
        fk_constraints = []
        for fk in fks:
            # fk tuple: id, seq, table, from, to, on_update, on_delete, match
            ref_table = fk[2]
            from_col = fk[3]
            to_col = fk[4]
            fk_constraints.append(f"FOREIGN KEY ({quote_ident(from_col)}) REFERENCES {quote_ident(ref_table)}({quote_ident(to_col)})")

        all_defs = col_defs + fk_constraints

        lines.append(f"DROP TABLE IF EXISTS {quote_ident(name)} CASCADE;")
        lines.append(f"CREATE TABLE {quote_ident(name)} (")
        for i, d in enumerate(all_defs):
            suffix = ',' if i < len(all_defs)-1 else ''
            lines.append('    ' + d + suffix)
        lines.append(");")
        lines.append('')

    # Data export
    for t in tables:
        name = t['name']
        cur.execute(f"SELECT * FROM '{name}'")
        rows = cur.fetchall()
        if not rows:
            continue
        colnames = rows[0].keys()
        col_list = ', '.join(quote_ident(c) for c in colnames)

        for r in rows:
            vals = [quote_value(r[c]) for c in colnames]
            lines.append(f"INSERT INTO {quote_ident(name)} ({col_list}) VALUES ({', '.join(vals)});")

    lines.append('')
    lines.append("COMMIT;")

    with open(OUT_SQL, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines))

    print(f"Wrote: {OUT_SQL} (tables: {len(tables)})")

if __name__ == '__main__':
    main()
