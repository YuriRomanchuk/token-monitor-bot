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

IGNORED_TOKENS = {
    '0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2',
    '0xdac17f958d2ee523a2206206994597c13d831ec7',
    '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48',
    '0x6b175474e89094c44da98b954eedeac495271d0f',
    '0x2260fac5e5542a773aa44fbcfedf7c193bc2c599',
    '0xae78736cd615f374d3085123a210448e74fc6393',
    '0x514910771af9ca656af840dff83e8264ecf986ca',
    '0x7f39c581f595b53c5cb19bd0b3f8da6c935e2ca0',
    '0x45804880de22913dafe09f4980848ece6ecbaf78',
    '0x68749665ff8d2d112fa859aa293f07a622782f38',
}

IGNORED_SYMBOLS = {
    'WETH', 'USDT', 'USDC', 'DAI', 'WBTC', 'WSTETH', 'LINK',
    'AAVE', 'UNI', 'LDO', 'CRV', 'MKR', 'SNX', 'COMP',
    'PAXG', 'XAUT', 'WBETH', 'STETH', 'RETH', 'SWETH',
}

QUERY_NEW_TOKENS = """
{
  ethereum(network: ethereum) {
    dexTrades(
      options: {desc: "block.timestamp.time", limit: 20}
      exchangeName: {is: "Uniswap"}
      date: {since: "%DATE%"}
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
      amount: tradeAmount(in: USD)
      transaction {
        hash
      }
    }
  }
}
"""

TOKENS_SEEN = set()


def get_today_date() -> str:
    return datetime.utcnow().strftime('%Y-%m-%d')


def format_alert(trade: dict) -> str:
    symbol = trade.get('baseCurrency', {}).get('symbol', 'N/A')
    name = trade.get('baseCurrency', {}).get('name', 'N/A')
    address = trade.get('baseCurrency', {}).get('address', 'N/A')
    quote = trade.get('quoteCurrency', {}).get('symbol', 'N/A')
    amount = trade.get('amount', 0)
    tx_hash = trade.get('transaction', {}).get('hash', 'N/A')
    timestamp = trade.get('block', {}).get('timestamp', {}).get('time', 'N/A')

    if not amount or amount < 1000:
        return None

    etherscan_link = f"https://etherscan.io/token/{address}"
    uniswap_link = f"https://app.uniswap.org/swap?outputCurrency={address}"
    dexscreener_link = f"https://dexscreener.com/ethereum/{address}"
    tx_link = f"https://etherscan.io/tx/{tx_hash}"

    return f"""
🚨 <b>НОВИЙ ТОКЕН НА UNISWAP</b>

🪙 <b>Символ:</b> {symbol}
📛 <b>Назва:</b> {name}
💰 <b>Обсяг:</b> ${amount:,.0f}
💵 <b>Котирування:</b> {quote}
🔗 <b>Контракт:</b>
<code>{address}</code>

📊 <b>Посилання:</b>
• <a href="{dexscreener_link}">DexScreener</a>
• <a href="{etherscan_link}">Etherscan</a>
• <a href="{uniswap_link}">Купити</a>
• <a href="{tx_link}">Транзакція</a>

⏰ {timestamp}
""".strip()


async def fetch_new_tokens() -> list:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {BITQUERY_API_KEY}"
    }

    today = get_today_date()
    query = QUERY_NEW_TOKENS.replace("%DATE%", today)

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                BITQUERY_URL,
                json={"query": query},
                headers=headers,
                timeout=30
            )
            response.raise_for_status()
            data = response.json()

            if 'errors' in data:
                logger.error(f"API помилка: {data['errors']}")
                return []

            return data.get('data', {}).get('ethereum', {}).get('dexTrades', []) or []
        except Exception as e:
            logger.error(f"Помилка API: {e}")
            return []


async def monitor_loop(bot: Bot):
    global TOKENS_SEEN
    logger.info("Запуск моніторингу нових токенів...")

    while True:
        try:
            trades = await fetch_new_tokens()
            sent_count = 0

            for trade in trades:
                token_addr = trade.get('baseCurrency', {}).get('address', '')
                symbol = trade.get('baseCurrency', {}).get('symbol', '')
                amount = trade.get('amount', 0)

                if token_addr.lower() in IGNORED_TOKENS:
                    continue
                if symbol.upper() in IGNORED_SYMBOLS:
                    continue

                if token_addr and token_addr not in TOKENS_SEEN and amount and amount >= 1000:
                    TOKENS_SEEN.add(token_addr)

                    alert_text = format_alert(trade)
                    if alert_text:
                        await bot.send_message(
                            chat_id=CHANNEL_ID,
                            text=alert_text,
                            parse_mode='HTML',
                            disable_web_page_preview=True
                        )
                        logger.info(f"Алерт: {symbol} (${amount:,.0f})")
                        sent_count += 1

                    if len(TOKENS_SEEN) > 2000:
                        TOKENS_SEEN = set(list(TOKENS_SEEN)[-1000:])

            if sent_count == 0:
                logger.info("Нових токенів не знайдено...")

            await asyncio.sleep(30)

        except Exception as e:
            logger.error(f"Помилка: {e}")
            await asyncio.sleep(60)


async def start_bot():
    if not all([TELEGRAM_TOKEN, CHANNEL_ID, BITQUERY_API_KEY]):
        logger.error("Не задані змінні середовища!")
        return

    bot = Bot(token=TELEGRAM_TOKEN)
    logger.info("Бот запускається...")
    await monitor_loop(bot)


if __name__ == '__main__':
    asyncio.run(start_bot())
