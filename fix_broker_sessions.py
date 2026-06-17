"""Fix broker_sessions.user_id NOT NULL constraint."""
import asyncio
import asyncpg

async def fix():
    conn = await asyncpg.connect("postgresql://trading:trading@localhost:5432/trading")

    # Check current nullability
    row = await conn.fetchrow("""
        SELECT is_nullable, column_default
        FROM information_schema.columns
        WHERE table_name='broker_sessions' AND column_name='user_id'
    """)
    print("Current user_id nullable:", row["is_nullable"], "default:", row["column_default"])

    # Make user_id nullable
    await conn.execute("ALTER TABLE broker_sessions ALTER COLUMN user_id DROP NOT NULL")
    print("user_id is now nullable")

    # Verify
    row = await conn.fetchrow("""
        SELECT is_nullable FROM information_schema.columns
        WHERE table_name='broker_sessions' AND column_name='user_id'
    """)
    print("After fix - nullable:", row["is_nullable"])

    await conn.close()

asyncio.run(fix())
