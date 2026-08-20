"""跨方言类型别名

BigInt: 主键用的 BIGINT，在 PostgreSQL 是 8 字节，在 SQLite 自动降级为 INTEGER
（让 SQLite 走 ROWID 自增；同时不破坏 PG 端的大数主键能力）
"""

from sqlalchemy import BigInteger, Integer

BigInt = BigInteger().with_variant(Integer, "sqlite")
