import os
import time
import logging
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Dict, List, Tuple
from dataclasses import dataclass
import requests

try:
    from pybit.unified_trading import HTTP
except ImportError:
    print("pip install pybit pandas numpy requests")
    exit(1)


# ==================== КОМИССИЯ BYBIT ====================
TAKER_FEE = 0.00055  # 0.055% на фьючерсах USDT-M


# ==================== TELEGRAM НОУТИФИКАТОР ====================

class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self.enabled = bool(bot_token and chat_id)
        
    def send(self, message: str):
        if not self.enabled:
            return
        try:
            requests.post(self.base_url, json={
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': 'HTML'
            }, timeout=5)
        except Exception:
            pass
    
    def send_trade(self, symbol: str, side: str, price: float, size: float, score: int, reason: str):
        emoji = "🟢" if side == "Buy" else "🔴"
        side_text = "LONG 📈" if side == "Buy" else "SHORT 📉"
        msg = f"""
{emoji} <b>СДЕЛКА {side.upper()}</b>

<b>{symbol}</b>
{side_text}
💰 Цена: {price:.2f} USDT
📊 Размер: {size:.6f}
🎯 Score: {score}
📝 {reason}

⏰ {datetime.now().strftime('%H:%M:%S')}
"""
        self.send(msg)
    
    def send_close(self, symbol: str, side: str, entry: float, exit: float, pnl: float, pnl_percent: float, reason: str):
        emoji = "✅" if pnl > 0 else "❌"
        msg = f"""
{emoji} <b>СДЕЛКА ЗАКРЫТА</b>

<b>{symbol}</b>
{side}
💰 Вход: {entry:.2f}
💰 Выход: {exit:.2f}
📊 P&L: {pnl:+.2f} USDT ({pnl_percent:+.2f}%)
📝 {reason}

⏰ {datetime.now().strftime('%H:%M:%S')}
"""
        self.send(msg)
    
    def send_status(self, msg: str):
        self.send(f"🤖 {msg}")


# ==================== ОПТИМАЛЬНЫЙ КОНФИГ ====================

@dataclass
class BotConfig:
    # API ключи (из переменных окружения Railway)
    API_KEY: str = os.getenv("API_KEY", "")
    API_SECRET: str = os.getenv("API_SECRET", "")
    
    # Telegram
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
    
    # Монеты для торговли (5 лучших по оптимизации)
    SYMBOLS: List[str] = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
    
    # ========== ОПТИМАЛЬНЫЕ ПАРАМЕТРЫ (результат оптимизации) ==========
    
    # RSI
    RSI_PERIOD: int = 7
    RSI_OVERSOLD: int = 35
    RSI_OVERBOUGHT: int = 65
    RSI_WEIGHT: int = 17
    
    # MACD
    MACD_FAST: int = 8
    MACD_SLOW: int = 17
    MACD_SIGNAL: int = 5
    MACD_WEIGHT: int = 18
    
    # Bollinger Bands
    BB_PERIOD: int = 14
    BB_STD: float = 2.0
    BB_LOWER_THRESHOLD: float = 0.15
    BB_UPPER_THRESHOLD: float = 0.85
    BB_WEIGHT: int = 10
    
    # EMA (Exponential Moving Average)
    EMA_FAST: int = 7
    EMA_SLOW: int = 20
    EMA_WEIGHT: int = 17
    
    # ATR Filter
    ATR_PERIOD: int = 14
    MAX_ATR: float = 2.8
    ATR_WEIGHT: int = 8
    
    # Volume
    VOLUME_PERIOD: int = 14
    VOLUME_THRESHOLD: float = 1.5
    VOLUME_WEIGHT: int = 10
    
    # Risk Management
    LEVERAGE: int = 8
    POSITION_SIZE: float = 10.0  # % от баланса
    STOP_LOSS: float = 2.2  # %
    TAKE_PROFIT: float = 5.5  # %
    ENTRY_THRESHOLD: int = 38  # Минимальный score для входа
    
    # Интервалы
    CHECK_INTERVAL: int = 60
    TIMEFRAME: str = "5"


# ==================== РАСШИРЕННЫЙ АНАЛИЗАТОР ====================

class SuperAnalyzer:
    def __init__(self, config: BotConfig):
        self.config = config
    
    def rsi(self, prices: np.ndarray) -> float:
        period = self.config.RSI_PERIOD
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
    
    def macd(self, prices: np.ndarray) -> Tuple[float, float, float]:
        fast = self.config.MACD_FAST
        slow = self.config.MACD_SLOW
        signal = self.config.MACD_SIGNAL
        if len(prices) < slow + signal:
            return 0, 0, 0
        exp1 = pd.Series(prices).ewm(span=fast, adjust=False).mean()
        exp2 = pd.Series(prices).ewm(span=slow, adjust=False).mean()
        macd_line = exp1 - exp2
        sig_line = macd_line.ewm(span=signal, adjust=False).mean()
        hist = macd_line.iloc[-1] - sig_line.iloc[-1]
        return macd_line.iloc[-1], sig_line.iloc[-1], hist
    
    def bollinger(self, prices: np.ndarray) -> Tuple[float, float, float, float]:
        period = self.config.BB_PERIOD
        std_mult = self.config.BB_STD
        if len(prices) < period:
            return 0, 0, 0, 0.5
        sma = np.mean(prices[-period:])
        std_dev = np.std(prices[-period:])
        upper = sma + (std_dev * std_mult)
        lower = sma - (std_dev * std_mult)
        position = (prices[-1] - lower) / (upper - lower) if upper != lower else 0.5
        return upper, sma, lower, position
    
    def ema(self, prices: np.ndarray, period: int) -> float:
        if len(prices) < period:
            return prices[-1]
        return pd.Series(prices).ewm(span=period, adjust=False).mean().iloc[-1]
    
    def atr(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> float:
        period = self.config.ATR_PERIOD
        if len(closes) < period + 1:
            return 0
        tr = []
        for i in range(1, len(closes)):
            hl = highs[i] - lows[i]
            hc = abs(highs[i] - closes[i-1])
            lc = abs(lows[i] - closes[i-1])
            tr.append(max(hl, hc, lc))
        return np.mean(tr[-period:])
    
    def analyze(self, df: pd.DataFrame) -> Dict:
        if len(df) < 100:
            return {"signal": "neutral", "score": 0, "price": 0, "reason": "Недостаточно данных"}
        
        closes = df['close'].values
        highs = df['high'].values
        lows = df['low'].values
        volumes = df['volume'].values
        price = closes[-1]
        
        # 1. RSI
        rsi_val = self.rsi(closes)
        rsi_score = 0
        if rsi_val < self.config.RSI_OVERSOLD:
            rsi_score = self.config.RSI_WEIGHT
        elif rsi_val > self.config.RSI_OVERBOUGHT:
            rsi_score = -self.config.RSI_WEIGHT
        
        # 2. MACD
        macd_line, sig_line, hist = self.macd(closes)
        macd_score = 0
        if hist > 0 and macd_line > sig_line:
            macd_score = self.config.MACD_WEIGHT
        elif hist < 0 and macd_line < sig_line:
            macd_score = -self.config.MACD_WEIGHT
        
        # 3. Bollinger Bands
        _, _, _, bb_pos = self.bollinger(closes)
        bb_score = 0
        if bb_pos < self.config.BB_LOWER_THRESHOLD:
            bb_score = self.config.BB_WEIGHT
        elif bb_pos > self.config.BB_UPPER_THRESHOLD:
            bb_score = -self.config.BB_WEIGHT
        
        # 4. EMA Cross
        ema_fast_val = self.ema(closes, self.config.EMA_FAST)
        ema_slow_val = self.ema(closes, self.config.EMA_SLOW)
        ema_score = 0
        if ema_fast_val > ema_slow_val:
            ema_score = self.config.EMA_WEIGHT
        else:
            ema_score = -self.config.EMA_WEIGHT
        
        # 5. ATR Filter
        atr_val = self.atr(highs, lows, closes)
        atr_percent = (atr_val / price) * 100 if price > 0 else 0
        atr_score = 0
        if atr_percent < self.config.MAX_ATR:
            atr_score = self.config.ATR_WEIGHT
        else:
            atr_score = -self.config.ATR_WEIGHT
        
        # 6. Volume
        vol_ma = np.mean(volumes[-self.config.VOLUME_PERIOD:])
        vol_ratio = volumes[-1] / vol_ma if vol_ma > 0 else 1
        vol_score = 0
        if vol_ratio > self.config.VOLUME_THRESHOLD:
            vol_score = self.config.VOLUME_WEIGHT if rsi_score > 0 else -self.config.VOLUME_WEIGHT
        
        # Суммируем все баллы
        total_score = rsi_score + macd_score + bb_score + ema_score + atr_score + vol_score
        
        # Определяем сигнал
        if total_score >= self.config.ENTRY_THRESHOLD:
            signal = "long"
        elif total_score <= -self.config.ENTRY_THRESHOLD:
            signal = "short"
        else:
            signal = "neutral"
        
        return {
            "signal": signal,
            "score": total_score,
            "price": price,
            "rsi": rsi_val,
            "vol_ratio": vol_ratio,
            "atr_percent": atr_percent,
            "reason": f"Score: {total_score}, RSI: {rsi_val:.1f}, Vol: {vol_ratio:.1f}x"
        }


# ==================== ОСНОВНОЙ БОТ ====================

class TradingBot:
    def __init__(self, config: BotConfig):
        self.config = config
        self.setup_logger()
        
        # Инициализация API (демо-режим Bybit)
        self.session = HTTP(
            testnet=False,  # False = реальная биржа (демо-режим в интерфейсе)
            api_key=config.API_KEY,
            api_secret=config.API_SECRET,
        )
        
        # Telegram
        self.notifier = TelegramNotifier(
            config.TELEGRAM_BOT_TOKEN,
            config.TELEGRAM_CHAT_ID
        )
        
        self.analyzer = SuperAnalyzer(config)
        self.positions = {}  # {symbol: position_data}
        self.running = True
        
        # Статистика
        self.stats = {
            'total_trades': 0,
            'winning_trades': 0,
            'total_fees': 0,
            'total_pnl': 0
        }
        
        self.logger.info("=" * 60)
        self.logger.info("🚀 ОПТИМАЛЬНЫЙ ТОРГОВЫЙ БОТ")
        self.logger.info(f"Монеты: {config.SYMBOLS}")
        self.logger.info(f"Плечо: {config.LEVERAGE}x | Позиция: {config.POSITION_SIZE}%")
        self.logger.info(f"Стоп-лосс: {config.STOP_LOSS}% | Тейк-профит: {config.TAKE_PROFIT}%")
        self.logger.info(f"Порог входа: {config.ENTRY_THRESHOLD}")
        self.logger.info(f"Комиссия тейкер: {TAKER_FEE*100:.3f}%")
        self.logger.info("=" * 60)
        
        self.notifier.send_status(
            f"🚀 Бот запущен\n"
            f"Монеты: {', '.join(config.SYMBOLS)}\n"
            f"Плечо: {config.LEVERAGE}x\n"
            f"Порог входа: {config.ENTRY_THRESHOLD}"
        )
    
    def setup_logger(self):
        self.logger = logging.getLogger("TradingBot")
        self.logger.setLevel(logging.INFO)
        ch = logging.StreamHandler()
        ch.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
        self.logger.addHandler(ch)
    
    def get_balance(self) -> float:
        try:
            resp = self.session.get_wallet_balance(accountType="UNIFIED", coin="USDT")
            if resp.get('retCode') == 0:
                data = resp.get('result', {}).get('list', [{}])[0]
                return float(data.get('totalEquity', 0))
            return 0
        except Exception as e:
            self.logger.error(f"Ошибка баланса: {e}")
            return 0
    
    def get_klines(self, symbol: str, limit: int = 100) -> List[Dict]:
        try:
            resp = self.session.get_kline(
                category="linear",
                symbol=symbol,
                interval=self.config.TIMEFRAME,
                limit=limit
            )
            if resp.get('retCode') == 0:
                klines = resp.get('result', {}).get('list', [])
                return [{
                    'close': float(k[4]),
                    'high': float(k[2]),
                    'low': float(k[3]),
                    'volume': float(k[5]),
                    'timestamp': int(k[0])
                } for k in klines]
            return []
        except Exception as e:
            self.logger.error(f"Ошибка свечей {symbol}: {e}")
            return []
    
    def place_order(self, symbol: str, side: str, qty: float, price: float, analysis: Dict) -> bool:
        try:
            resp = self.session.place_order(
                category="linear",
                symbol=symbol,
                side=side,
                orderType="Market",
                qty=str(qty),
                timeInForce="GTC"
            )
            if resp.get('retCode') == 0:
                position_value = qty * price
                fee = position_value * TAKER_FEE
                self.stats['total_fees'] += fee
                
                self.logger.info(f"✅ {side} {symbol} {qty:.6f} @ {price:.2f} | Комиссия: {fee:.4f} USDT")
                self.notifier.send_trade(symbol, side, price, qty, analysis['score'], analysis['reason'])
                return True
            else:
                self.logger.error(f"Ошибка ордера: {resp}")
                return False
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")
            return False
    
    def close_position(self, symbol: str, price: float, reason: str):
        pos = self.positions.get(symbol)
        if not pos:
            return
        
        if pos['side'] == 'Buy':
            pnl = pos['qty'] * (price - pos['entry'])
        else:
            pnl = pos['qty'] * (pos['entry'] - price)
        
        # Комиссия при закрытии
        close_value = pos['qty'] * price
        fee = close_value * TAKER_FEE
        self.stats['total_fees'] += fee
        
        pnl_after_fees = pnl - fee
        pnl_percent = (pnl_after_fees / pos['margin']) * 100 if pos['margin'] > 0 else 0
        
        # Обновляем баланс
        self.stats['total_pnl'] += pnl_after_fees
        if pnl_after_fees > 0:
            self.stats['winning_trades'] += 1
        self.stats['total_trades'] += 1
        
        self.logger.info(f"🔒 {symbol} закрыта | P&L: {pnl_after_fees:+.2f} USDT ({pnl_percent:+.2f}%) | {reason}")
        self.notifier.send_close(symbol, pos['side'], pos['entry'], price, pnl_after_fees, pnl_percent, reason)
        
        del self.positions[symbol]
    
    def check_stop_loss_take_profit(self, symbol: str, price: float):
        pos = self.positions.get(symbol)
        if not pos:
            return
        
        if pos['side'] == 'Buy':
            if price <= pos['entry'] * (1 - self.config.STOP_LOSS / 100):
                self.close_position(symbol, price, f"Stop Loss ({self.config.STOP_LOSS}%)")
            elif price >= pos['entry'] * (1 + self.config.TAKE_PROFIT / 100):
                self.close_position(symbol, price, f"Take Profit ({self.config.TAKE_PROFIT}%)")
        else:
            if price >= pos['entry'] * (1 + self.config.STOP_LOSS / 100):
                self.close_position(symbol, price, f"Stop Loss ({self.config.STOP_LOSS}%)")
            elif price <= pos['entry'] * (1 - self.config.TAKE_PROFIT / 100):
                self.close_position(symbol, price, f"Take Profit ({self.config.TAKE_PROFIT}%)")
    
    def run(self):
        last_check = 0
        balance = self.get_balance()
        
        self.logger.info(f"💰 Начальный баланс: {balance:.2f} USDT")
        
        while self.running:
            try:
                current_time = time.time()
                
                if current_time - last_check >= self.config.CHECK_INTERVAL:
                    balance = self.get_balance()
                    self.logger.info(f"💰 Баланс: {balance:.2f} USDT | Комиссий: {self.stats['total_fees']:.2f} | Сделок: {self.stats['total_trades']}")
                    
                    for symbol in self.config.SYMBOLS:
                        # Получаем свечи
                        klines = self.get_klines(symbol, 100)
                        if not klines:
                            continue
                        
                        # Создаем DataFrame для анализа
                        df = pd.DataFrame(klines)
                        
                        # Анализ
                        analysis = self.analyzer.analyze(df)
                        
                        # Логируем сильные сигналы
                        if analysis['signal'] != 'neutral':
                            self.logger.info(f"📊 {symbol}: {analysis['signal'].upper()} | {analysis['reason']}")
                        
                        # Проверяем стоп-лосс/тейк-профит для открытых позиций
                        if symbol in self.positions:
                            self.check_stop_loss_take_profit(symbol, analysis['price'])
                        
                        # Новый сигнал
                        if analysis['signal'] in ['long', 'short'] and symbol not in self.positions:
                            # Расчет размера позиции
                            position_value = balance * (self.config.POSITION_SIZE / 100)
                            qty = (position_value * self.config.LEVERAGE) / analysis['price']
                            qty = round(qty, 6)
                            
                            if qty > 0:
                                side = "Buy" if analysis['signal'] == 'long' else "Sell"
                                margin = position_value
                                
                                if margin <= balance:
                                    if self.place_order(symbol, side, qty, analysis['price'], analysis):
                                        self.positions[symbol] = {
                                            'side': side,
                                            'entry': analysis['price'],
                                            'qty': qty,
                                            'margin': margin
                                        }
                                        balance -= margin
                    
                    last_check = current_time
                
                time.sleep(10)
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                self.logger.error(f"Ошибка: {e}")
                time.sleep(30)
        
        self.stop()
    
    def stop(self):
        self.running = False
        
        # Закрываем все открытые позиции
        for symbol in list(self.positions.keys()):
            try:
                price = self.get_current_price(symbol)
                self.close_position(symbol, price, "Бот остановлен")
            except:
                pass
        
        final_balance = self.get_balance()
        total_return = (final_balance - 1000) / 1000 * 100
        
        self.logger.info("=" * 60)
        self.logger.info("🛑 БОТ ОСТАНОВЛЕН")
        self.logger.info(f"💰 Финальный баланс: {final_balance:.2f} USDT")
        self.logger.info(f"📈 Общая доходность: {total_return:+.2f}%")
        self.logger.info(f"💸 Всего комиссий: {self.stats['total_fees']:.2f} USDT")
        self.logger.info(f"🎯 Всего сделок: {self.stats['total_trades']}")
        self.logger.info(f"🏆 Прибыльных: {self.stats['winning_trades']}")
        self.logger.info("=" * 60)
        
        self.notifier.send_status(
            f"🛑 Бот остановлен\n"
            f"Финальный баланс: {final_balance:.2f} USDT\n"
            f"Доходность: {total_return:+.2f}%\n"
            f"Сделок: {self.stats['total_trades']}\n"
            f"Комиссий: {self.stats['total_fees']:.2f} USDT"
        )
    
    def get_current_price(self, symbol: str) -> float:
        try:
            resp = self.session.get_tickers(category="linear", symbol=symbol)
            if resp.get('retCode') == 0:
                data = resp.get('result', {}).get('list', [])
                if data:
                    return float(data[0].get('lastPrice', 0))
            return 0
        except:
            return 0


# ==================== ЗАПУСК ====================

if __name__ == "__main__":
    config = BotConfig()
    
    if not config.API_KEY or config.API_KEY == "":
        print("=" * 60)
        print("⚠️  НЕТ API КЛЮЧЕЙ!")
        print("=" * 60)
        print("\nДля работы бота добавьте в Railway Variables:")
        print("  API_KEY = ваш_api_ключ")
        print("  API_SECRET = ваш_секретный_ключ")
        print("  TELEGRAM_BOT_TOKEN = токен_бота (опционально)")
        print("  TELEGRAM_CHAT_ID = ваш_id (опционально)")
        print("\nКак получить API ключи в демо-режиме Bybit:")
        print("  1. Зайдите на bybit.com")
        print("  2. Включите демо-режим (Dual UI)")
        print("  3. Нажмите на аватар → API Management")
        print("  4. Создайте ключ с правами Read-Write, Derivatives Trading")
        print("  5. Скопируйте API Key и API Secret")
        print("=" * 60)
        
        # Демо-режим без API
        print("\n🔄 Запуск в демо-режиме (без торговли)...")
        while True:
            print(f"[{datetime.now()}] Бот активен. Ожидание API ключей...")
            time.sleep(60)
    else:
        bot = TradingBot(config)
        try:
            bot.run()
        except KeyboardInterrupt:
            bot.stop()
