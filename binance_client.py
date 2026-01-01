from binance.client import Client
from binance.enums import *
import pandas as pd
import config

class BinanceDataClient:
    def __init__(self):
        requests_params = {}
        if config.PROXY_URL:
            requests_params['proxies'] = {
                'http': config.PROXY_URL,
                'https': config.PROXY_URL
            }
        
        try:
            # 增加 timeout 设置，防止初始化卡死
            requests_params['timeout'] = 10
            self.client = Client(config.BINANCE_API_KEY, config.BINANCE_SECRET_KEY, requests_params=requests_params)
            
            # 自动同步服务器时间，解决 recvWindow 错误
            res = self.client.get_server_time()
            import time
            self.client.timestamp_offset = res['serverTime'] - int(time.time() * 1000)
            
        except Exception as e:
            print(f"Binance Client Init Error: {e}")
            self.client = None

    def get_klines(self, symbol, interval=config.KLINE_INTERVAL, limit=config.KLINE_LIMIT):
        """获取K线数据 (优先尝试期货，失败则尝试现货)"""
        if not self.client: return None
        try:
            # 尝试获取期货K线
            try:
                klines = self.client.futures_klines(symbol=symbol, interval=interval, limit=limit)
            except:
                # 失败则尝试现货K线
                klines = self.client.get_klines(symbol=symbol, interval=interval, limit=limit)
                
            df = pd.DataFrame(klines, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_asset_volume', 'number_of_trades',
                'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
            ])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
            return df
        except Exception as e:
            print(f"Error fetching klines for {symbol}: {e}")
            return None

    def get_ticker_price(self, symbol):
        """获取当前价格 (优先期货)"""
        if not self.client: return None
        try:
            try:
                ticker = self.client.futures_symbol_ticker(symbol=symbol)
            except:
                ticker = self.client.get_symbol_ticker(symbol=symbol)
            return float(ticker['price'])
        except Exception as e:
            print(f"Error fetching price for {symbol}: {e}")
            return None

    def get_all_symbols(self):
        """获取所有交易对 (包含现货和期货)"""
        if not self.client: return []
        symbols = set()
        try:
            # 获取现货
            spot_info = self.client.get_exchange_info()
            for s in spot_info['symbols']:
                if s['status'] == 'TRADING':
                    symbols.add(s['symbol'])
            
            # 获取期货
            futures_info = self.client.futures_exchange_info()
            for s in futures_info['symbols']:
                if s['status'] == 'TRADING':
                    symbols.add(s['symbol'])
                    
            return sorted(list(symbols))
        except Exception as e:
            print(f"Error fetching symbols: {e}")
            return list(symbols)

    def get_symbol_info(self, symbol):
        """获取交易对的精度信息"""
        if not self.client: return None
        try:
            info = self.client.futures_exchange_info()
            for s in info['symbols']:
                if s['symbol'] == symbol:
                    return s
            return None
        except:
            return None
