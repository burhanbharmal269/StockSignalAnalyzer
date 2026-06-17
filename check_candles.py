import asyncio
import asyncpg

async def check():
    conn = await asyncpg.connect("postgresql://trading:trading@localhost:5432/trading")

    # Check what symbols have candle data
    rows = await conn.fetch("""
        SELECT symbol, timeframe, COUNT(*) as cnt, MIN(ts) as oldest, MAX(ts) as newest
        FROM historical_candles
        GROUP BY symbol, timeframe
        ORDER BY cnt DESC
        LIMIT 20
    """)
    print("=== Candle data in DB ===")
    for r in rows:
        print(f"  {r['symbol']:20} {r['timeframe']:5} {r['cnt']:5} candles  {r['oldest'].date()} to {r['newest'].date()}")

    # Check what universe symbols are active F&O
    rows2 = await conn.fetch("""
        SELECT symbol, is_fo, is_index, lot_size, instrument_token
        FROM universe_symbols
        WHERE is_active = true AND is_fo = true
        LIMIT 20
    """)
    print("\n=== Active F&O universe symbols (first 20) ===")
    for r in rows2:
        print(f"  {r['symbol']:20} index={r['is_index']} lot={r['lot_size']} token={r['instrument_token']}")

    await conn.close()

asyncio.run(check())
