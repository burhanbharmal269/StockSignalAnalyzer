"""Add missing columns to instruments table."""
import asyncio
import asyncpg

async def fix():
    conn = await asyncpg.connect("postgresql://trading:trading@localhost:5432/trading")

    # Get existing columns
    rows = await conn.fetch("""
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_name = 'instruments'
        ORDER BY ordinal_position
    """)
    existing = {r["column_name"] for r in rows}
    print("Existing columns:", sorted(existing))

    needed = {
        "segment":          "ALTER TABLE instruments ADD COLUMN segment VARCHAR(20) NOT NULL DEFAULT ''",
        "underlying_symbol":"ALTER TABLE instruments ADD COLUMN underlying_symbol VARCHAR(30)",
        "option_type":      "ALTER TABLE instruments ADD COLUMN option_type VARCHAR(2)",
        "isin":             "ALTER TABLE instruments ADD COLUMN isin VARCHAR(12)",
        "display_symbol":   "ALTER TABLE instruments ADD COLUMN display_symbol VARCHAR(100) NOT NULL DEFAULT ''",
    }

    for col, sql in needed.items():
        if col not in existing:
            await conn.execute(sql)
            print(f"Added column: {col}")
        else:
            print(f"Column already exists: {col}")

    await conn.close()
    print("Done.")

asyncio.run(fix())
