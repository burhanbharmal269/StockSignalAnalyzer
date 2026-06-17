import asyncio, sys, pathlib, os, base64
sys.path.insert(0, 'D:/StockSignalAnalyzer/src')
from dotenv import load_dotenv
load_dotenv(pathlib.Path('D:/StockSignalAnalyzer/.env'))

import asyncpg
from kiteconnect import KiteConnect
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from datetime import datetime, timedelta


async def main():
    conn = await asyncpg.connect('postgresql://trading:trading@localhost:5432/trading')
    session = await conn.fetchrow(
        "SELECT encrypted_access_token FROM broker_sessions WHERE broker_name='kite' AND is_active=true LIMIT 1"
    )
    if not session:
        print('No active Kite session found!')
        await conn.close()
        return

    enc = session['encrypted_access_token']
    key = bytes.fromhex(os.environ['BROKER_TOKEN_ENCRYPTION_KEY'])
    raw = base64.urlsafe_b64decode(enc.encode())
    nonce = raw[:12]
    cipher = raw[12:]
    aesgcm = AESGCM(key)
    access_token = aesgcm.decrypt(nonce, cipher, None).decode()
    print('Access token prefix:', access_token[:10], '...')

    kite = KiteConnect(api_key='wonpxy8eqpk49lv6')
    kite.set_access_token(access_token)

    to_dt = datetime.now()
    from_dt = to_dt - timedelta(days=3)

    # RELIANCE instrument token on NSE
    try:
        data = kite.historical_data(738561, from_dt, to_dt, '15minute')
        print(f'Got {len(data)} candles for RELIANCE')
        if data:
            print('Latest candle:', data[-1])
    except Exception as e:
        print('Kite historical_data error:', type(e).__name__, e)

    # Also test LTP
    try:
        ltp = kite.ltp('NSE:RELIANCE')
        print('LTP:', ltp)
    except Exception as e:
        print('LTP error:', e)

    await conn.close()


asyncio.run(main())
