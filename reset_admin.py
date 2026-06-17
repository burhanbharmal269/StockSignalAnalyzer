import asyncio
import asyncpg
from argon2 import PasswordHasher

async def reset():
    ph = PasswordHasher()
    new_pass = "Admin@1234"
    hashed = ph.hash(new_pass)

    conn = await asyncpg.connect("postgresql://trading:trading@localhost:5432/trading")
    result = await conn.execute(
        "UPDATE users SET hashed_password=$1, force_change=false WHERE username='admin'",
        hashed
    )
    print("Updated:", result)
    print("New hash:", hashed[:40], "...")
    await conn.close()

asyncio.run(reset())
