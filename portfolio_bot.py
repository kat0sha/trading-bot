import os
import time
import hashlib
import hmac
import numpy as np
import pandas as pd
import requests
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from dotenv import load_dotenv

# ==================== ЗАГРУЗКА КЛЮЧЕЙ ====================
load_dotenv("password.env")

API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

print("=" * 60)
print("🔑 ЗАГРУЗКА КЛЮЧЕЙ")
print("=" * 60)
print(f"API_KEY: {API_KEY[:10] if API_KEY else 'НЕ НАЙДЕН'}...")
print(f"API_SECRET: {API_SECRET[:10] if API_SECRET else 'НЕ НАЙДЕН'}...")
print("=" * 60)

# ==================== КОМИССИЯ ====================
TAKER_FEE = 0.00055


# ==================== TELEGRAM НОУТИФИКАТОР ====================

class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.enabled = bool(bot_token and chat_id)

        if self.enabled:
            print(f"✅ Telegram бот инициализирован")

    def send(self, message: str):
        if not self.enabled:
            return
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            data = {"chat_id": self.chat_id, "text": message, "parse_mode": "HTML"}
            response = requests.post(url, json=data, timeout=10)
            if response.status_code != 200:
                print(f"⚠️ Telegram ошибка: {response.status_code}")
        except Exception as e:
            print(f"⚠️ Ошибка Telegram: {e}")

    def send_trade(self, symbol: str, side: str, price: float, size: float,
                   strategy: str, reason: str):
        emoji = "🟢" if side == "Buy" else "🔴"
        side_text = "LONG 📈" if side == "Buy" else "SHORT 📉"
        msg = f"""
{emoji} <b>НОВАЯ СДЕЛКА</b>

<b>{symbol}</b>
{side_text}
🎯 Стратегия: {strategy.upper()}
💰 Цена: {price:.2f} USDT
📊 Размер: {size}
📝 {reason}

⏰ {datetime.now().strftime('%H:%M:%S')}
"""
        self.send(msg)

    def send_close(self, symbol: str, side: str, entry: float, exit: float,
                   pnl: float, pnl_percent: float, strategy: str, reason: str):
        emoji = "✅" if pnl > 0 else "❌"
        msg = f"""
{emoji} <b>СДЕЛКА ЗАКРЫТА</b>

<b>{symbol}</b>
🎯 Стратегия: {strategy.upper()}
💰 Вход: {entry:.2f}
💰 Выход: {exit:.2f}
📊 P&L: {pnl:+.2f} USDT ({pnl_percent:+.2f}%)
📝 {reason}

⏰ {datetime.now().strftime('%H:%M:%S')}
"""
        self.send(msg)

    def send_status(self, msg: str):
        self.send(f"🤖 {msg}")


# ==================== API КЛИЕНТ ====================

class BybitAPI:
    def __init__(self, api_key: str, api_secret: str, testnet: bool = True):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = "https://api-demo.bybit.com" if testnet else "https://api.bybit.com"
        self.time_offset = 0
        self.sync_time()

    def sync_time(self):
        try:
            response = requests.get(f"{self.base_url}/v5/market/time")
            if response.status_code == 200:
                server_time = response.json()['result']['timeSecond']
                server_timestamp = int(server_time) * 1000
                local_timestamp = int(time.time() * 1000)
                self.time_offset = server_timestamp - local_timestamp
                return True
        except Exception:
            pass
        return False

    def _request(self, method="GET", endpoint="", params=None):
        timestamp = int(time.time() * 1000) + self.time_offset
        recv_window = 10000

        if params is None:
            params = {}

        if endpoint == "/v5/account/wallet-balance" and "accountType" not in params:
            params["accountType"] = "UNIFIED"

        sign_params = {
            "api_key": self.api_key,
            "timestamp": timestamp,
            "recv_window": recv_window
        }
        sign_params.update(params)

        sorted_keys = sorted(sign_params.keys())
        param_pairs = []

        for key in sorted_keys:
            value = sign_params[key]
            if isinstance(value, bool):
                value = "true" if value else "false"
            else:
                value = str(value)
            param_pairs.append(f"{key}={value}")

        param_str = '&'.join(param_pairs)
        signature = hmac.new(
            bytes(self.api_secret, 'utf-8'),
            bytes(param_str, 'utf-8'),
            hashlib.sha256
        ).hexdigest()

        if method.upper() == "GET":
            sign_params["sign"] = signature
            url = f"{self.base_url}{endpoint}"
            response = requests.get(url, params=sign_params, timeout=10)
        else:
            sign_params["sign"] = signature
            url = f"{self.base_url}{endpoint}"
            response = requests.post(url, json=sign_params, timeout=10)

        if response.status_code == 200:
            result = response.json()
            if result.get('retCode') == 10002:
                self.sync_time()
                return self._request(method, endpoint, params)
            return result
        else:
            return {"retCode": response.status_code, "retMsg": response.text}

    def get_balance(self) -> float:
        result = self._request(method="GET", endpoint="/v5/account/wallet-balance")

        if result.get('retCode') == 0:
            try:
                if 'result' in result and 'list' in result['result']:
                    for coin in result['result']['list'][0]['coin']:
                        if coin.get('coin') == 'USDT':
                            return float(coin.get('walletBalance', 0))
            except Exception:
                pass
        return 0

    def get_klines(self, symbol: str, limit: int = 100) -> List[Dict]:
        result = self._request(
            method="GET",
            endpoint="/v5/market/kline",
            params={"category": "linear", "symbol": symbol, "interval": "5", "limit": limit}
        )

        data = []
        if result.get('retCode') == 0:
            for candle in result['result']['list']:
                data.append({
                    'timestamp': int(candle[0]),
                    'open': float(candle[1]),
                    'high': float(candle[2]),
                    'low': float(candle[3]),
                    'close': float(candle[4]),
                    'volume': float(candle[5])
                })
            return sorted(data, key=lambda x: x['timestamp'])
        return []

    def get_current_price(self, symbol: str) -> float:
        result = self._request(
            method="GET",
            endpoint="/v5/market/tickers",
            params={"category": "linear", "symbol": symbol}
        )
        if result.get('retCode') == 0:
            return float(result['result']['list'][0]['markPrice'])
        return 0

    def place_order(self, symbol: str, side: str, qty: float) -> bool:
        """Размещение рыночного ордера"""
        qty_str = str(int(qty)) if qty == int(qty) else f"{qty:.3f}"
        result = self._request(
            method="POST",
            endpoint="/v5/order/create",
            params={
                "category": "linear",
                "symbol": symbol,
                "side": side,
                "orderType": "Market",
                "qty": qty_str,
                "timeInForce": "GTC",
                "positionIdx": 0
            }
        )
        return result.get('retCode') == 0

    def set_stop_loss_take_profit(self, symbol: str, side: str,
                                  stop_loss: float, take_profit: float) -> bool:
        """
        Установка стоп-лосса и тейк-профита через API Bybit
        Это встроенные ордера биржи, срабатывают мгновенно даже если бот выключен
        """
        result = self._request(
            method="POST",
            endpoint="/v5/position/trading-stop",
            params={
                "category": "linear",
                "symbol": symbol,
                "stopLoss": str(round(stop_loss, 2)),
                "takeProfit": str(round(take_profit, 2)),
                "positionIdx": 0
            }
        )
        return result.get('retCode') == 0


# ==================== АНАЛИЗАТОР ====================

class Analyzer:
    def rsi(self, prices, period=7):
        if len(prices) < period + 1:
            return 50
        delta = np.diff(prices)
        gain = delta.clip(min=0)
        loss = -delta.clip(max=0)
        avg_gain = np.mean(gain[-period:])
        avg_loss = np.mean(loss[-period:])
        if avg_loss == 0:
            return 100
        return 100 - (100 / (1 + avg_gain / avg_loss))

    def analyze(self, df: pd.DataFrame) -> Dict:
        if len(df) < 50:
            return {"signal": "neutral", "score": 0, "price": 0}

        closes = df['close'].values
        volumes = df['volume'].values
        price = closes[-1]

        rsi_val = self.rsi(closes)

        score = 0
        if rsi_val < 35:
            score += 30
        elif rsi_val > 65:
            score -= 30

        vol_ma = np.mean(volumes[-10:])
        vol_ratio = volumes[-1] / vol_ma if vol_ma > 0 else 1
        if vol_ratio > 1.5:
            if score > 0:
                score += 20
            else:
                score -= 20

        if score >= 35:
            signal = "Buy"
        elif score <= -35:
            signal = "Sell"
        else:
            signal = "neutral"

        return {
            "signal": signal,
            "score": score,
            "price": price,
            "rsi": rsi_val,
            "vol_ratio": vol_ratio
        }


# ==================== ОСНОВНОЙ БОТ ====================

# ==================== ПАРАМЕТРЫ ДЛЯ МАЛОГО ДЕПОЗИТА (10 USDT) ====================

class TradingBot:
    def __init__(self, api_key: str, api_secret: str, testnet: bool = True,
                 telegram_token: str = None, telegram_chat_id: str = None):
        
        self.api = BybitAPI(api_key, api_secret, testnet)
        self.telegram = TelegramNotifier(telegram_token, telegram_chat_id)
        self.analyzer = Analyzer()
        
        # 👇 НАСТРОЙКИ ДЛЯ 10 USDT
        self.symbols = ["XRPUSDT", "SOLUSDT", "BNBUSDT"]  # Только монеты с малым лотом
        self.positions = {}
        self.running = False
        self.total_pnl = 0
        self.total_fees = 0
        self.total_trades = 0
        self.winning_trades = 0
        
        # Торговые параметры
        self.position_size_percent = 50   # 50% от баланса (5 USDT на сделку)
        self.stop_loss_percent = 3.0      # Стоп-лосс 3%
        self.take_profit_percent = 6.0    # Тейк-профит 6%
        self.leverage = 10                # Плечо 10x
        
        # Защита от слишком маленьких ордеров
        self.min_position_value = 10      # Минимум 10 USDT с плечом
        
        print("=" * 60)
        print("🚀 ТОРГОВЫЙ БОТ (МАЛЫЙ ДЕПОЗИТ - 10 USDT)")
        print(f"📊 Монеты: {self.symbols}")
        print(f"⚡ Плечо: {self.leverage}x")
        print(f"🎯 Риск: {self.position_size_percent}% от баланса")
        print(f"🛑 Стоп-лосс: {self.stop_loss_percent}%")
        print(f"🎯 Тейк-профит: {self.take_profit_percent}%")
        print("=" * 60)
        
        if self.telegram.enabled:
            self.telegram.send_status(
                f"🚀 Бот запущен (10 USDT режим)\n"
                f"Монеты: {', '.join(self.symbols)}\n"
                f"Плечо: {self.leverage}x\n"
                f"SL: {self.stop_loss_percent}% | TP: {self.take_profit_percent}%"
            )
    
    def calculate_position_size(self, balance: float, price: float) -> float:
        """Расчет размера позиции с проверкой минимального размера"""
        position_value = balance * (self.position_size_percent / 100)
        
        # Проверяем минимальную позицию
        if position_value * self.leverage < self.min_position_value:
            print(f"⚠️ Позиция слишком мала: {position_value * self.leverage:.2f} USDT < {self.min_position_value}")
            return 0
        
        qty = (position_value * self.leverage) / price
        
        # Округляем в зависимости от монеты
        if 'XRP' in symbol:
            qty = round(qty, 1)  # XRP можно 0.1
        elif 'SOL' in symbol:
            qty = round(qty, 2)  # SOL с 2 знаками
        else:
            qty = round(qty, 3)
        
        return max(qty, 0.001)
    
    # ... остальной код без изменений ...


# ==================== ЗАПУСК ====================

if __name__ == "__main__":
    if not API_KEY or not API_SECRET:
        print("\n❌ ОШИБКА: API ключи не найдены!")
        print("Проверьте файл password.env")
        print("Должно быть:\nAPI_KEY=ваш_ключ\nAPI_SECRET=ваш_секрет")
        exit(1)

    print("\n🔍 ПРОВЕРКА ПОДКЛЮЧЕНИЯ...")
    test_api = BybitAPI(API_KEY, API_SECRET, testnet=True)
    test_balance = test_api.get_balance()

    if test_balance > 0:
        print(f"✅ Подключение успешно! Баланс: {test_balance:.2f} USDT")
        print("\n🚀 Запускаем бота...")

        bot = TradingBot(
            api_key=API_KEY,
            api_secret=API_SECRET,
            testnet=False,
            telegram_token=TELEGRAM_TOKEN,
            telegram_chat_id=TELEGRAM_CHAT_ID
        )
        bot.run(interval=30)
    else:
        print(f"❌ Ошибка подключения. Баланс: {test_balance:.2f}")
        print("\nПроверьте:")
        print("1. Включен ли демо-режим на Bybit")
        print("2. Созданы ли ключи в демо-режиме")
        print("3. Включен ли Unified Trading Account")
