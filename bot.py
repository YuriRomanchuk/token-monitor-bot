import os
import asyncio
import logging
from datetime import datetime
from telegram import Bot
import httpx

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
CHANNEL_ID = os.getenv('CHANNEL_ID')
BITQUERY_API_KEY = os.getenv('BITQUERY_API_KEY')

BITQUERY_URL = "https://graphql.bitquery.io"

QUERY_NEW_TOKENS = """
{
  ethereum(network: ethereum) {
    dexTrades(
      options: {desc: "block.timestamp.time", limit: 5}
      exchangeName: {is: "Uniswap"}
      tradeAmountUsd: {gt: 1000}
    ) {
      block {
        timestamp {
          time
        }
      }
      baseCurrency {
        symbol
        address
        name
      }
      quoteCurrency {
        symbol
      }
      tradeAmount-usd
      exchange {
        fullName
      }
      transaction {
        hash
      }
    }
  }
}
"""

TOKENS_SEEN = set()


def format_alert(trade: dict) -> str:
    symbol = trade.get('baseCurrency', {}).get('symbol', 'N/A')
    name = trade.get('baseCurrency', {}).get('name', 'N/A')
    address = trade.get('baseCurrency', {}).get('address', 'N/A')
    quote = trade.get('quoteCurrency', {}).get('symbol', 'N/A')
    amount = trade.get('tradeAmount-usd', 0)
    tx_hash = trade.get('transaction', {}).get('hash', 'N/A')
    timestamp = trade.get('block', {}).get('timestamp', {}).get('time', 'N/A')

    short_addr = f"{address[:6]}...{address[-4:]}" if len(address) > 10 else address
    short_tx = f"{tx_hash[:10]}..." if len(tx_hash) > 10 else tx_hash

    etherscan_link = f"https://etherscan.io/token/{address}"
    uniswap_link = f"https://app.uniswap.org/swap?outputCurrency={address}"
    tx_link = f"https://etherscan.io/tx/{tx_hash}"

    return f"""
🚨 <b>НОВИЙ ТОКЕН НА UNISWAP</b>

🪙 <b>Символ:</b> {symbol}
📛 <b>Назва:</b> {name}
💰 <b>Ліквідність:</b> ${amount:,.0f}
💵 <b>Котирування:</b> {quote}
🔗 <b>Контракт:</b> <code>{address}</code>

📊 <b>Посилання:</b>
• <a href="{etherscan_link}">Etherscan</a>
• <a href="{uniswap_link}">Купити на Uniswap</a>
• <a href="{tx_link}">Транзакція</a>

⏰ {timestamp}
""".strip()


async def fetch_new_tokens() -> list:
    headers = {
        "Content-Type": "application/json",
        "X-API-KEY": BITQUERY_API_KEY
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                BITQUERY_URL,
                json={"query": QUERY_NEW_TOKENS},
                headers=headers,
                timeout=30
            )
            response.raise_for_status()
            data = response.json()
            return data.get('data', {}).get('ethereum', {}).get('dexTrades', [])
        except Exception as e:
            logger.error(f"Помилка API: {e}")
            return []


async def monitor_loop(bot: Bot):
    global TOKENS_SEEN
    logger.info("Запуск моніторингу нових токенів...")

    while True:
        try:
            trades = await fetch_new_tokens()

            for trade in trades:
                token_addr = trade.get('baseCurrency', {}).get('address', '')
                amount = trade.get('tradeAmount-usd', 0)

                if token_addr and token_addr not in TOKENS_SEEN and amount >= 1000:
                    TOKENS_SEEN.add(token_addr)

                    alert_text = format_alert(trade)

                    await bot.send_message(
                        chat_id=CHANNEL_ID,
                        text=alert_text,
                        parse_mode='HTML',
                        disable_web_page_preview=True
                    )
                    logger.info(f"Надіслано алерт: {trade.get('baseCurrency', {}).get('symbol', 'N/A')}")

                    if len(TOKENS_SEEN) > 1000:
                        TOKENS_SEEN = set(list(TOKENS_SEEN)[-500:])

            await asyncio.sleep(30)

        except Exception as e:
            logger.error(f"Помилка в циклі моніторингу: {e}")
            await asyncio.sleep(60)


async def start_bot():
    if not all([TELEGRAM_TOKEN, CHANNEL_ID, BITQUERY_API_KEY]):
        logger.error("Не задані змінні середовища!")
        logger.error("Потрібно: TELEGRAM_TOKEN, CHANNEL_ID, BITQUERY_API_KEY")
        return

    bot = Bot(token=TELEGRAM_TOKEN)

    logger.info("Бот запускається...")
    await monitor_loop(bot)


if __name__ == '__main__':
    asyncio.run(start_bot())
