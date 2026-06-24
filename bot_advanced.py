import os
import asyncio
import json
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
PAID_CHANNEL_ID = os.getenv('PAID_CHANNEL_ID')

BITQUERY_URL = "https://graphql.bitquery.io"

QUERY_NEW_TOKENS = """
{
  ethereum(network: ethereum) {
    dexTrades(
      options: {desc: "block.timestamp.time", limit: 10}
      exchangeName: {is: "Uniswap"}
      tradeAmountUsd: {gt: 500}
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
CONFIG_FILE = "config.json"


def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {
        "min_liquidity": 1000,
        "free_delay_seconds": 300,
        "tracked_tokens": []
    }


def save_config(config: dict):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)


def format_free_alert(trade: dict) -> str:
    symbol = trade.get('baseCurrency', {}).get('symbol', 'N/A')
    name = trade.get('baseCurrency', {}).get('name', 'N/A')
    address = trade.get('baseCurrency', {}).get('address', 'N/A')
    amount = trade.get('tradeAmount-usd', 0)
    timestamp = trade.get('block', {}).get('timestamp', {}).get('time', 'N/A')

    uniswap_link = f"https://app.uniswap.org/swap?outputCurrency={address}"

    return f"""
🔔 <b>НОВИЙ ТОКЕН</b>

🪙 {symbol} ({name})
💰 Ліквідність: ${amount:,.0f}
🔗 <a href="{uniswap_link}">Купити</a>

⏰ {timestamp}
""".strip()


def format_paid_alert(trade: dict) -> str:
    symbol = trade.get('baseCurrency', {}).get('symbol', 'N/A')
    name = trade.get('baseCurrency', {}).get('name', 'N/A')
    address = trade.get('baseCurrency', {}).get('address', 'N/A')
    quote = trade.get('quoteCurrency', {}).get('symbol', 'N/A')
    amount = trade.get('tradeAmount-usd', 0)
    tx_hash = trade.get('transaction', {}).get('hash', 'N/A')
    timestamp = trade.get('block', {}).get('timestamp', {}).get('time', 'N/A')

    etherscan_link = f"https://etherscan.io/token/{address}"
    uniswap_link = f"https://app.uniswap.org/swap?outputCurrency={address}"
    dexscreener_link = f"https://dexscreener.com/ethereum/{address}"
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
• <a href="{uniswap_link}">Uniswap</a>
• <a href="{dexscreener_link}">DexScreener</a>
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
    config = load_config()
    min_liquidity = config.get('min_liquidity', 1000)

    logger.info(f"Запуск моніторингу (мін. ліквідність: ${min_liquidity})...")

    while True:
        try:
            trades = await fetch_new_tokens()

            for trade in trades:
                token_addr = trade.get('baseCurrency', {}).get('address', '')
                amount = trade.get('tradeAmount-usd', 0)

                if token_addr and token_addr not in TOKENS_SEEN and amount >= min_liquidity:
                    TOKENS_SEEN.add(token_addr)

                    if PAID_CHANNEL_ID:
                        paid_text = format_paid_alert(trade)
                        await bot.send_message(
                            chat_id=PAID_CHANNEL_ID,
                            text=paid_text,
                            parse_mode='HTML',
                            disable_web_page_preview=True
                        )

                    free_text = format_free_alert(trade)
                    await bot.send_message(
                        chat_id=CHANNEL_ID,
                        text=free_text,
                        parse_mode='HTML',
                        disable_web_page_preview=True
                    )

                    logger.info(f"Алерт: {trade.get('baseCurrency', {}).get('symbol', 'N/A')} (${amount:,.0f})")

                    if len(TOKENS_SEEN) > 2000:
                        TOKENS_SEEN = set(list(TOKENS_SEEN)[-1000:])

            await asyncio.sleep(30)

        except Exception as e:
            logger.error(f"Помилка: {e}")
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
