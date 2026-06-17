import asyncio
import asyncpg

async def check():
    conn = await asyncpg.connect("postgresql://trading:trading@localhost:5432/trading")
    cols = await conn.fetch("SELECT column_name FROM information_schema.columns WHERE table_name='users' ORDER BY ordinal_position")
    print("Columns:", [r["column_name"] for r in cols])
    row = await conn.fetchrow("SELECT * FROM users LIMIT 1")
    if row:
        print("User:", dict(row))
    await conn.close()

asyncio.run(check())
