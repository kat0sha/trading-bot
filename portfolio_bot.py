import os
import time
import hashlib
import hmac
import numpy as np
import pandas as pd
import requests
from datetime import datetime
from typing import Dict, List, Tuple, Optional
import random

# ==================== ДИАГНОСТИКА ПЕРЕМЕННЫХ ====================
print("=" * 60)
print("🔍 ДИАГНОСТИКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ")
print("=" * 60)

API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

print(f"API_KEY: {'✅ НАЙДЕН' if API_KEY else '❌ НЕ НАЙДЕН'} ({API_KEY[:10] if API_KEY else 'None'}...)")
print(f"API_SECRET: {'✅ НАЙДЕН' if API_SECRET else '❌ НЕ НАЙДЕН'} ({API_SECRET[:10] if API_SECRET else 'None'}...)")
print(f"TELEGRAM_TOKEN: {'✅ НАЙДЕН' if TELEGRAM_TOKEN else '❌ НЕ НАЙДЕН'}")
print(f"TELEGRAM_CHAT_ID: {'✅ НАЙДЕН' if TELEGRAM_CHAT_ID else '❌ НЕ НАЙДЕН'}")

if not API_KEY or not API_SECRET:
    print("\n❌ ПЕРЕМЕННЫЕ НЕ НАЙДЕНЫ!")
    print("\n👉 ДОБАВЬТЕ В RAILWAY VARIABLES:")
    print("   API_KEY = ваш_ключ")
    print("   API_SECRET = ваш_секрет")
    exit(1)

print("=" * 60)

# ==================== КОМИССИЯ ====================
TAKER_FEE = 0.00055

# ==================== СПИСОК ПРОКСИ ДЛЯ ОБХОДА БЛОКИРОВКИ ====================
# Бесплатные прокси (обновляются автоматически)
PROXY_LIST = [
    None,  # Прямое подключение (пробуем сначала)
    "http://45.138.75.20:8080",
    "http://185.222.58.195:8080",
    "http://5.8.72.34:8080",
    "http://45.86.236.2:8080",
    "http://91.211.248.254:8080",
    "socks5://45.138.75.20:1080",
    "socks5://185.222.58.195:1080",
    "socks5://5.8.72.34:1080",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Connection": "keep-alive"
}


# ==================== TELEGRAM ====================

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
            requests.post(url, json=data, timeout=15, headers=HEADERS)
        except Exception:
            pass

    def send_trade(self, symbol: str, side: str, price: float, size: float,
                   strategy: str, reason: str):
        emoji = "🟢" if side == "Buy" else "🔴"
        side_text = "LONG 📈" if side == "Buy" else "SHORT 📉"
        msg = f"""{emoji} <b>НОВАЯ СДЕЛКА</b>\n\n<b>{symbol}</b>\n{side_text}\n💰 Цена: {price:.2f} USDT\n📊 Размер: {size}\n📝 {reason}"""
        self.send(msg)

    def send_close(self, symbol: str, side: str, entry: float, exit: float,
                   pnl: float, pnl_percent: float, strategy: str, reason: str):
        emoji = "✅" if pnl > 0 else "❌"
        msg = f"""{emoji} <b>СДЕЛКА ЗАКРЫТА</b>\n\n<b>{symbol}</b>\n💰 Вход: {entry:.2f}\n💰 Выход: {exit:.2f}\n📊 P&L: {pnl:+.2f} USDT ({pnl_percent:+.2f}%)\n📝 {reason}"""
        self.send(msg)

    def send_status(self, msg: str):
        self.send(f"🤖 {msg}")


# ==================== API КЛИЕНТ С ПРОКСИ ====================

class BybitAPI:
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = "https://api.bybit.com"
        self.time_offset = 0
        self.proxy_index = 0
        self.current_proxy = None
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self._find_working_proxy()

    def _find_working_proxy(self):
        """Находит работающий прокси"""
        print("\n🔍 ПОИСК РАБОТАЮЩЕГО ПРОКСИ...")
        
        for i, proxy in enumerate(PROXY_LIST):
            try:
                proxies = {'http': proxy, 'https': proxy} if proxy else None
                r = self.session.get(
                    f"{self.base_url}/v5/market/time",
                    proxies=proxies,
                    timeout=8
                )
                if r.status_code == 200:
                    self.current_proxy = proxy
                    self.proxy_index = i
                    print(f"✅ Найден работающий прокси: {proxy if proxy else 'ПРЯМОЕ ПОДКЛЮЧЕНИЕ'}")
                    self._sync_time()
                    return True
                else:
                    print(f"   ❌ {proxy if proxy else 'ПРЯМОЕ'} - HTTP {r.status_code}")
            except Exception as e:
                print(f"   ❌ {proxy if proxy else 'ПРЯМОЕ'} - {str(e)[:50]}")
        
        print("\n⚠️ НЕ НАЙДЕНО РАБОТАЮЩИХ ПРОКСИ!")
        print("   Railway IP может быть заблокирован Bybit")
        print("   Попробуйте позже или используйте VPN на локальном компьютере")
        return False

    def _get_proxies(self):
        """Возвращает текущий прокси"""
        if self.current_proxy:
            return {'http': self.current_proxy, 'https': self.current_proxy}
        return None

    def _sync_time(self):
        try:
            proxies = self._get_proxies()
            r = self.session.get(
                f"{self.base_url}/v5/market/time",
                proxies=proxies,
                timeout=10
            )
            if r.status_code == 200:
                data = r.json()
                if data.get('retCode') == 0:
                    server_time = data['result']['timeSecond']
                    self.time_offset = (int(server_time) * 1000) - int(time.time() * 1000)
                    print(f"✅ Время синхронизировано (смещение: {self.time_offset} мс)")
                    return True
        except Exception as e:
            print(f"⚠️ Ошибка синхронизации: {e}")
        return False

    def _request(self, endpoint: str, params: dict = None) -> dict:
        timestamp = int(time.time() * 1000) + self.time_offset
        if params is None:
            params = {}
        
        if endpoint == "/v5/account/wallet-balance":
            params["accountType"] = "UNIFIED"
        
        params["api_key"] = self.api_key
        params["timestamp"] = timestamp
        params["recv_window"] = 10000
        
        sorted_keys = sorted(params.keys())
        param_str = '&'.join([f"{k}={params[k]}" for k in sorted_keys])
        signature = hmac.new(
            self.api_secret.encode(),
            param_str.encode(),
            hashlib.sha256
        ).hexdigest()
        params["sign"] = signature
        
        url = f"{self.base_url}{endpoint}"
        proxies = self._get_proxies()
        
        try:
            r = self.session.get(url, params=params, proxies=proxies, timeout=15)
            
            if r.status_code == 200:
                return r.json()
            else:
                print(f"⚠️ HTTP {r.status_code}")
                return {"retCode": r.status_code, "retMsg": f"HTTP {r.status_code}"}
                
        except Exception as e:
            print(f"⚠️ Ошибка: {e}")
            return {"retCode": -1, "retMsg": str(e)}

    def get_balance(self) -> float:
        result = self._request("/v5/account/wallet-balance")
        
        if result.get('retCode') == 0:
            try:
                for coin in result['result']['list'][0]['coin']:
                    if coin['coin'] == 'USDT':
                        balance = float(coin['walletBalance'])
                        print(f"💰 Баланс: {balance:.2f} USDT")
                        return balance
            except Exception as e:
                print(f"❌ Ошибка парсинга: {e}")
        else:
            print(f"❌ Ошибка: {result.get('retMsg')}")
        
        return 0

    def get_klines(self, symbol: str, limit: int = 100) -> List[Dict]:
        result = self._request(
            "/v5/market/kline",
            {"category": "linear", "symbol": symbol, "interval": "5", "limit": limit}
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
        result = self._request("/v5/market/tickers", {"category": "linear", "symbol": symbol})
        if result.get('retCode') == 0:
            return float(result['result']['list'][0]['markPrice'])
        return 0

    def place_order(self, symbol: str, side: str, qty: float) -> bool:
        qty_str = str(int(qty)) if qty == int(qty) else f"{qty:.3f}"
        result = self._request("/v5/order/create", {
            "category": "linear",
            "symbol": symbol,
            "side": side,
            "orderType": "Market",
            "qty": qty_str,
            "timeInForce": "GTC",
            "positionIdx": 0
        })
        return result.get('retCode') == 0

    def set_stop_loss_take_profit(self, symbol: str, side: str,
                                   stop_loss: float, take_profit: float) -> bool:
        result = self._request("/v5/position/trading-stop", {
            "category": "linear",
            "symbol": symbol,
            "stopLoss": str(round(stop_loss, 2)),
            "takeProfit": str(round(take_profit, 2)),
            "positionIdx": 0
        })
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
    def __init__(self, api_key: str, api_secret: str,
                 telegram_token: str = None, telegram_chat_id: str = None):

        self.api = BybitAPI(api_key, api_secret)
        self.telegram = TelegramNotifier(telegram_token, telegram_chat_id)
        self.analyzer = Analyzer()

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
        print("🚀 ТОРГОВЫЙ БОТ (ДЕМО-РЕЖИМ)")
        print(f"📊 Монеты: {self.symbols}")
        print(f"⚡ Плечо: {self.leverage}x")
        print("=" * 60)

    def get_balance(self) -> float:
        return self.api.get_balance()

    def calculate_position_size(self, balance: float, price: float) -> float:
        position_value = balance * (self.position_size_percent / 100)
        qty = (position_value * self.leverage) / price
        return round(qty, 6)

    def check_signal(self, symbol: str):
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
            return False

        price = analysis['price']
        qty = self.calculate_position_size(balance, price)

        if qty <= 0:
            return False

        if side == "Buy":
            stop_loss = round(price * 0.98, 2)
            take_profit = round(price * 1.055, 2)
        else:
            stop_loss = round(price * 1.02, 2)
            take_profit = round(price * 0.945, 2)

        print(f"🚀 {symbol}: {side} {qty} @ {price:.2f}")

        success = self.api.place_order(symbol, side, qty)
        if not success:
            return False

        time.sleep(1)
        self.api.set_stop_loss_take_profit(symbol, side, stop_loss, take_profit)

        self.positions[symbol] = {
            'side': side, 'entry': price, 'qty': qty,
            'stop_loss': stop_loss, 'take_profit': take_profit
        }
        self.total_trades += 1

        if self.telegram.enabled:
            self.telegram.send_trade(symbol, side, price, qty, 'hybrid', f"Score: {analysis['score']}")
        return True

    def close_position(self, symbol: str, price: float, reason: str):
        pos = self.positions.get(symbol)
        if not pos:
            return

        if pos['side'] == "Buy":
            pnl = pos['qty'] * (price - pos['entry'])
        else:
            pnl = pos['qty'] * (pos['entry'] - price)

        fee = pos['qty'] * price * TAKER_FEE
        pnl_after_fees = pnl - fee
        pnl_percent = (pnl_after_fees / (pos['entry'] * pos['qty'] / self.leverage)) * 100

        self.total_pnl += pnl_after_fees
        self.total_fees += fee
        if pnl_after_fees > 0:
            self.winning_trades += 1

        print(f"🔒 {symbol} | P&L: {pnl_after_fees:+.2f} USDT ({pnl_percent:+.2f}%) | {reason}")

        if self.telegram.enabled:
            self.telegram.send_close(symbol, pos['side'], pos['entry'], price,
                                      pnl_after_fees, pnl_percent, 'hybrid', reason)

        del self.positions[symbol]

    def check_positions(self):
        for symbol in list(self.positions.keys()):
            price = self.api.get_current_price(symbol)
            if price <= 0:
                continue
            pos = self.positions[symbol]
            if pos['side'] == "Buy":
                if price <= pos['stop_loss']:
                    self.close_position(symbol, price, "Stop Loss")
                elif price >= pos['take_profit']:
                    self.close_position(symbol, price, "Take Profit")
            else:
                if price >= pos['stop_loss']:
                    self.close_position(symbol, price, "Stop Loss")
                elif price <= pos['take_profit']:
                    self.close_position(symbol, price, "Take Profit")

    def run(self, interval: int = 30):
        self.running = True
        print("\n🚀 Бот запущен\n")

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
            print("\n🛑 Остановка...")
            for symbol in list(self.positions.keys()):
                price = self.api.get_current_price(symbol)
                self.close_position(symbol, price, "Бот остановлен")

            print(f"\n💰 ИТОГ: P&L: {self.total_pnl:.2f} USDT | Комиссий: {self.total_fees:.2f} | Сделок: {self.total_trades}")


# ==================== ЗАПУСК ====================

if __name__ == "__main__":
    print("\n🔍 ПРОВЕРКА ПОДКЛЮЧЕНИЯ К BYBIT...")
    
    test_api = BybitAPI(API_KEY, API_SECRET)
    balance = test_api.get_balance()

    if balance > 0:
        print(f"\n✅ УСПЕХ! Баланс: {balance:.2f} USDT")
        print("\n🚀 ЗАПУСК БОТА...")
        bot = TradingBot(API_KEY, API_SECRET, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID)
        bot.run()
    else:
        print(f"\n❌ ОШИБКА! Баланс: {balance:.2f}")
