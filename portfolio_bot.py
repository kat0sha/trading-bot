import os
import time
import hashlib
import hmac
import numpy as np
import pandas as pd
import requests
from datetime import datetime
from typing import Dict, List, Tuple, Optional

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
     def __init__(self, api_key: str, api_secret: str, testnet: bool = False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = "https://api.bybit.com" if not testnet else "https://api-demo.bybit.com"

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

class TradingBot:
    def __init__(self, api_key: str, api_secret: str, testnet: bool = True,
                 telegram_token: str = None, telegram_chat_id: str = None):

        self.api = BybitAPI(api_key, api_secret, testnet)
        self.telegram = TelegramNotifier(telegram_token, telegram_chat_id)
        self.analyzer = Analyzer()

        # Настройки
        self.symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
        self.position_size_percent = 20
        self.stop_loss_percent = 2.0
        self.take_profit_percent = 5.5
        self.leverage = 10

        self.positions = {}
        self.running = False
        self.total_pnl = 0
        self.total_fees = 0
        self.total_trades = 0
        self.winning_trades = 0

        print("=" * 60)
        print("🚀 ТОРГОВЫЙ БОТ (SL/TP ЧЕРЕЗ API)")
        print(f"📊 Монеты: {self.symbols}")
        print(f"⚡ Плечо: {self.leverage}x")
        print(f"🎯 Риск: {self.position_size_percent}% от баланса")
        print(f"🛑 Стоп-лосс: {self.stop_loss_percent}%")
        print(f"🎯 Тейк-профит: {self.take_profit_percent}%")
        print("=" * 60)

        if self.telegram.enabled:
            self.telegram.send_status(
                f"🚀 Бот запущен\n"
                f"Монеты: {', '.join(self.symbols)}\n"
                f"Плечо: {self.leverage}x\n"
                f"SL: {self.stop_loss_percent}% | TP: {self.take_profit_percent}%"
            )

    def get_balance(self) -> float:
        balance = self.api.get_balance()
        print(f"💰 Баланс: {balance:.2f} USDT")
        return balance

    def calculate_position_size(self, balance: float, price: float) -> float:
        position_value = balance * (self.position_size_percent / 100)
        qty = (position_value * self.leverage) / price
        qty = round(qty, 6)
        return max(qty, 0.001)

    def check_signal(self, symbol: str) -> Tuple[Optional[str], Optional[Dict]]:
        df_data = self.api.get_klines(symbol, 100)
        if not df_data:
            return None, None

        df = pd.DataFrame(df_data)
        analysis = self.analyzer.analyze(df)

        if analysis['signal'] != 'neutral':
            print(f"📊 {symbol}: {analysis['signal']} | Score: {analysis['score']} | RSI: {analysis['rsi']:.1f}")
            return analysis['signal'], analysis
        return None, None

    def open_position(self, symbol: str, side: str, analysis: Dict):
        balance = self.api.get_balance()
        if balance < 10:
            print("❌ Недостаточно средств")
            return False

        price = analysis['price']
        qty = self.calculate_position_size(balance, price)

        if qty <= 0:
            print("❌ Размер позиции слишком мал")
            return False

        if side == "Buy":
            stop_loss = round(price * (1 - self.stop_loss_percent / 100), 2)
            take_profit = round(price * (1 + self.take_profit_percent / 100), 2)
        else:
            stop_loss = round(price * (1 + self.stop_loss_percent / 100), 2)
            take_profit = round(price * (1 - self.take_profit_percent / 100), 2)

        print(f"\n🚀 {symbol}: Открываем {side} позицию...")
        print(f"   📊 Размер: {qty}")
        print(f"   💰 Цена: {price:.2f}")
        print(f"   🛑 SL: {stop_loss:.2f} ({self.stop_loss_percent}%)")
        print(f"   🎯 TP: {take_profit:.2f} ({self.take_profit_percent}%)")

        success = self.api.place_order(symbol, side, qty)

        if not success:
            print(f"❌ Не удалось открыть позицию")
            return False

        time.sleep(1)

        sl_success = self.api.set_stop_loss_take_profit(symbol, side, stop_loss, take_profit)

        if sl_success:
            print(f"✅ SL/TP установлены")
        else:
            print(f"⚠️ Не удалось установить SL/TP")

        self.positions[symbol] = {
            'side': side,
            'entry': price,
            'qty': qty,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'score': analysis['score']
        }

        self.total_trades += 1

        if self.telegram.enabled:
            self.telegram.send_trade(
                symbol, side, price, qty, 'hybrid',
                f"Score: {analysis['score']}, SL: {stop_loss}, TP: {take_profit}"
            )

        return True

    def close_position(self, symbol: str, price: float, reason: str):
        pos = self.positions.get(symbol)
        if not pos:
            return

        if pos['side'] == "Buy":
            pnl = pos['qty'] * (price - pos['entry'])
        else:
            pnl = pos['qty'] * (pos['entry'] - price)

        close_value = pos['qty'] * price
        fee = close_value * TAKER_FEE
        self.total_fees += fee

        pnl_after_fees = pnl - fee
        pnl_percent = (pnl_after_fees / (pos['entry'] * pos['qty'] / self.leverage)) * 100

        self.total_pnl += pnl_after_fees
        if pnl_after_fees > 0:
            self.winning_trades += 1

        print(f"\n🔒 {symbol} ЗАКРЫТА | {reason}")
        print(f"   P&L: {pnl_after_fees:+.2f} USDT ({pnl_percent:+.2f}%)")

        if self.telegram.enabled:
            self.telegram.send_close(
                symbol, pos['side'], pos['entry'], price,
                pnl_after_fees, pnl_percent, 'hybrid', reason
            )

        del self.positions[symbol]

    def check_positions(self):
        for symbol in list(self.positions.keys()):
            current_price = self.api.get_current_price(symbol)
            if current_price <= 0:
                continue

            pos = self.positions[symbol]

            if pos['side'] == "Buy":
                if current_price <= pos['stop_loss']:
                    self.close_position(symbol, current_price, "Stop Loss")
                elif current_price >= pos['take_profit']:
                    self.close_position(symbol, current_price, "Take Profit")
            else:
                if current_price >= pos['stop_loss']:
                    self.close_position(symbol, current_price, "Stop Loss")
                elif current_price <= pos['take_profit']:
                    self.close_position(symbol, current_price, "Take Profit")

    def run(self, interval: int = 30):
        """Основной цикл бота - ЗДЕСЬ БЫЛО ПРОПУЩЕНО!"""
        self.running = True
        print("\n🚀 Бот запущен, начинаем торговлю...\n")

        try:
            while self.running:
                balance = self.get_balance()
                self.check_positions()

                for symbol in self.symbols:
                    if symbol in self.positions:
                        continue

                    signal, analysis = self.check_signal(symbol)
                    if signal and analysis:
                        self.open_position(symbol, signal, analysis)

                time.sleep(interval)

        except KeyboardInterrupt:
            print("\n🛑 Остановка бота...")
            self.running = False

            for symbol in list(self.positions.keys()):
                price = self.api.get_current_price(symbol)
                self.close_position(symbol, price, "Бот остановлен")

            print("\n" + "=" * 60)
            print("📊 ИТОГОВАЯ СТАТИСТИКА")
            print("=" * 60)
            print(f"💰 Общий P&L: {self.total_pnl:.2f} USDT")
            print(f"💸 Комиссий: {self.total_fees:.2f} USDT")
            print(f"🎯 Всего сделок: {self.total_trades}")
            print(f"🏆 Прибыльных: {self.winning_trades}")
            if self.total_trades > 0:
                print(f"📈 Win Rate: {self.winning_trades / self.total_trades * 100:.1f}%")
            print("=" * 60)


# ==================== ЗАПУСК ====================

if __name__ == "__main__":
    API_KEY = os.getenv("API_KEY", "YOUR_API_KEY")
    API_SECRET = os.getenv("API_SECRET", "YOUR_API_SECRET")
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

    print("=" * 60)
    print("🔍 ПРОВЕРКА ПОДКЛЮЧЕНИЯ")
    print("=" * 60)

    if API_KEY == "YOUR_API_KEY":
        print("⚠️ ВНИМАНИЕ: Используются тестовые ключи!")
        print("Добавьте в Railway Variables:")
        print("  API_KEY = ваш_ключ")
        print("  API_SECRET = ваш_секрет")
        print("\nДля демо-режима Bybit:")
        print("1. Включите демо-режим на bybit.com")
        print("2. Создайте API ключи в демо-режиме")
        print("3. Добавьте их в Variables")

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
