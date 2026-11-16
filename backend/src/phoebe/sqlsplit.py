"""Split a SQL script into single statements (the Data API runs one per call).

Understands single-quoted strings (`''` escapes), double-quoted identifiers
(`""` escapes), `$$`/`$tag$` dollar quoting, `--` line comments and nestable
`/* */` block comments. Comments are dropped; empty statements are skipped.
Not handled: backslash escapes in `E'...'` strings and psql meta-commands.
"""

import re

_DOLLAR_TAG = re.compile(r"\$(?:[A-Za-z_]\w*)?\$")


def split_statements(sql: str) -> list[str]:
    statements: list[str] = []
    buf: list[str] = []
    i, n = 0, len(sql)

    def flush() -> None:
        stmt = "".join(buf).strip()
        buf.clear()
        if stmt:
            statements.append(stmt)

    while i < n:
        c = sql[i]
        if c == "-" and sql.startswith("--", i):
            end = sql.find("\n", i)
            i = n if end < 0 else end  # keep the newline
        elif c == "/" and sql.startswith("/*", i):
            depth, i = 1, i + 2
            while i < n and depth:
                if sql.startswith("/*", i):
                    depth, i = depth + 1, i + 2
                elif sql.startswith("*/", i):
                    depth, i = depth - 1, i + 2
                else:
                    i += 1
            buf.append(" ")
        elif c in "'\"":
            j = i + 1
            while j < n:
                if sql[j] == c:
                    if sql.startswith(c, j + 1):  # doubled quote: escape
                        j += 2
                        continue
                    break
                j += 1
            buf.append(sql[i : j + 1])
            i = j + 1
        elif c == "$" and (m := _DOLLAR_TAG.match(sql, i)):
            tag = m.group()
            end = sql.find(tag, m.end())
            j = n if end < 0 else end + len(tag)
            buf.append(sql[i:j])
            i = j
        elif c == ";":
            flush()
            i += 1
        else:
            buf.append(c)
            i += 1
    flush()
    return statements
