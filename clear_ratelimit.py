import redis

r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True, protocol=2)

# Find and delete all rate limit / auth related keys
keys = r.keys("*")
print(f"Total keys: {len(keys)}")

deleted = 0
for k in keys:
    print(f"  {k}")
    if any(x in k.lower() for x in ["rate", "login", "auth", "limit", "throttle", "fail", "block"]):
        r.delete(k)
        deleted += 1
        print(f"    ^ DELETED")

print(f"\nDeleted {deleted} keys")

# Also just FLUSHDB to clear everything (safe for dev)
# r.flushdb()
# print("Flushed entire Redis DB")
