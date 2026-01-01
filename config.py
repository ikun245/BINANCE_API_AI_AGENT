import os
import json

CONFIG_FILE = "config.json"

def load_config():
    defaults = {
        "BINANCE_API_KEY": "",
        "BINANCE_SECRET_KEY": "",
        "AI_PROVIDER": "deepseek",
        "DEEPSEEK_API_KEY": "",
        "DEEPSEEK_BASE_URL": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "DEEPSEEK_MODEL": "deepseek-v3",
        "DEFAULT_SYMBOLS": ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "ADAUSDT"],
        "KLINE_INTERVAL": "1m",
        "KLINE_LIMIT": 900,
        "DEFAULT_TRADE_AMOUNT": 10.0,
        "PROXY_URL": None
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                user_config = json.load(f)
                defaults.update(user_config)
        except Exception as e:
            print(f"Error loading config: {e}")
    return defaults

def save_config(config_dict):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config_dict, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving config: {e}")

# Load initial config
_current_config = load_config()

BINANCE_API_KEY = _current_config.get("BINANCE_API_KEY")
BINANCE_SECRET_KEY = _current_config.get("BINANCE_SECRET_KEY")

# AI Configuration (Aliyun DashScope DeepSeek)
AI_PROVIDER = _current_config.get("AI_PROVIDER")
DEEPSEEK_API_KEY = _current_config.get("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = _current_config.get("DEEPSEEK_BASE_URL")
DEEPSEEK_MODEL = _current_config.get("DEEPSEEK_MODEL")

# App Settings
DEFAULT_SYMBOLS = _current_config.get("DEFAULT_SYMBOLS")
KLINE_INTERVAL = _current_config.get("KLINE_INTERVAL")
KLINE_LIMIT = _current_config.get("KLINE_LIMIT")
DEFAULT_TRADE_AMOUNT = _current_config.get("DEFAULT_TRADE_AMOUNT", 10.0)

# Proxy Configuration
PROXY_URL = _current_config.get("PROXY_URL")
