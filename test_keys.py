import os
import time
import hashlib
import hmac
import requests
from datetime import datetime

TAKER_FEE = 0.00055

class BybitAPI:
    def __init__(self, api_key, api_secret):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = "https://api.bybit.com"
        self.time_offset = 0
        self._sync_time()

    def _sync_time(self):
        try:
            r = requests.get(f"{self.base_url}/v5/market/time", timeout=5)
            if r.status_code == 200:
                server_time = r.json()['result']['timeSecond']
                self.time_offset = (int(server_time) * 1000) - int(time.time() * 1000)
                return True
        except:
            pass
        return False

    def _request(self, endpoint, params=None):
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
        signature = hmac.new(self.api_secret.encode(), param_str.encode(), hashlib.sha256).hexdigest()
        params["sign"] = signature
        
        url = f"{self.base_url}{endpoint}"
        r = requests.get(url, params=params, timeout=10)
        return r.json()

    def get_balance(self):
        result = self._request("/v5/account/wallet-balance")
        if result.get('retCode') == 0:
            for coin in result['result']['list'][0]['coin']:
                if coin['coin'] == 'USDT':
                    return float(coin['walletBalance'])
        return 0


if __name__ == "__main__":
    API_KEY = os.getenv("API_KEY")
    API_SECRET = os.getenv("API_SECRET")
    
    print("=" * 50)
    print("🔍 ПРОВЕРКА КЛЮЧЕЙ")
    print("=" * 50)
    
    if not API_KEY or not API_SECRET:
        print("❌ Ключи не найдены!")
        exit(1)
    
    api = BybitAPI(API_KEY, API_SECRET)
    balance = api.get_balance()
    
    if balance > 0:
        print(f"✅ УСПЕХ! Баланс: {balance:.2f} USDT")
        print("🎉 КЛЮЧИ РАБОТАЮТ!")
    else:
        print(f"❌ Баланс: {balance:.2f}")
        print("\n👉 ПРОВЕРЬ:")
        print("1. Включен ли демо-режим на bybit.com")
        print("2. Ключи созданы ПОСЛЕ включения демо-режима")
        print("3. Включен ли Unified Trading Account")
