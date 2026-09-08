import asyncio

from app.db.session import AsyncSessionLocal
from app.services.sync_service import sync_us_etf_market_data


async def main():
    async with AsyncSessionLocal() as session:
        res = await sync_us_etf_market_data(session)
        print("Sync complete:", res)


if __name__ == "__main__":
    asyncio.run(main())
