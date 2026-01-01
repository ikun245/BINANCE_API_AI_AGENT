import uuid
import time
from binance.enums import *

class SimulatedTradingEngine:
    # ... (existing code)
    def __init__(self, initial_balance=10000.0):
        self.balance = initial_balance
        self.positions = [] # List of dicts: {'id', 'symbol', 'side', 'amount', 'entry_price', 'tp', 'sl', 'margin'}
        self.trade_history = []

    def open_position(self, symbol, side, price, amount_usdt, leverage=1, margin_mode="全仓", tp=None, sl=None, owner="用户"):
        """
        side: 'LONG' or 'SHORT'
        amount_usdt: 名义价值 (Position Value)
        leverage: 杠杆倍数
        """
        required_margin = amount_usdt / leverage
        if required_margin > self.balance:
            return False, "余额不足 (保证金不足)"
        
        quantity = amount_usdt / price
        self.balance -= required_margin
        
        pos_id = str(uuid.uuid4())[:8]
        position = {
            'id': pos_id,
            'symbol': symbol,
            'side': side,
            'amount': quantity,
            'entry_price': price,
            'leverage': leverage,
            'margin_mode': margin_mode,
            'tp': tp,
            'sl': sl,
            'margin': required_margin,
            'owner': owner
        }
        self.positions.append(position)
        self.trade_history.append(f"[{owner}] 开仓 {side} {symbol}: 价格 {price}, 杠杆 {leverage}x, 模式 {margin_mode}, 名义价值 {amount_usdt} USDT")
        return True, f"成功开仓 {side} {symbol}"

    def close_position(self, pos_id, current_price):
        for i, pos in enumerate(self.positions):
            if pos['id'] == pos_id:
                # 计算盈亏
                if pos['side'] == 'LONG':
                    pnl = (current_price - pos['entry_price']) * pos['amount']
                else: # SHORT
                    pnl = (pos['entry_price'] - current_price) * pos['amount']
                
                return_amount = pos['margin'] + pnl
                self.balance += return_amount
                
                closed_pos = self.positions.pop(i)
                self.trade_history.append(f"[{closed_pos['owner']}] 平仓 {closed_pos['side']} {closed_pos['symbol']}: 价格 {current_price}, 盈亏 {pnl:.2f}")
                return True, f"成功平仓，盈亏: {pnl:.2f} USDT"
        
        return False, "未找到持仓"

    def check_tp_sl(self, current_prices):
        """检查所有持仓是否触发止盈止损"""
        closed_messages = []
        for pos in list(self.positions):
            symbol = pos['symbol']
            if symbol not in current_prices:
                continue
            
            price = current_prices[symbol]
            trigger = False
            
            if pos['side'] == 'LONG':
                if pos['tp'] and price >= pos['tp']: trigger = True
                if pos['sl'] and price <= pos['sl']: trigger = True
            else: # SHORT
                if pos['tp'] and price <= pos['tp']: trigger = True
                if pos['sl'] and price >= pos['sl']: trigger = True
                
            if trigger:
                success, msg = self.close_position(pos['id'], price)
                closed_messages.append(f"{symbol} 触发止盈止损: {msg}")
        
        return closed_messages

    def get_total_equity(self, current_prices):
        equity = self.balance
        for pos in self.positions:
            symbol = pos['symbol']
            if symbol in current_prices:
                price = current_prices[symbol]
                if pos['side'] == 'LONG':
                    pnl = (price - pos['entry_price']) * pos['amount']
                else:
                    pnl = (pos['entry_price'] - price) * pos['amount']
                equity += pos['margin'] + pnl
        return equity

class BinanceTradingEngine:
    def __init__(self, binance_client):
        self.binance = binance_client
        self.trade_history = []
        self._last_balance = 0.0
        self._account_cache = None
        self._cache_time = 0

    def _get_account_info(self, force=False):
        """获取并缓存账户信息，减少 API 调用频率"""
        import time
        now = time.time()
        # 缓存 3 秒，除非强制刷新
        if not force and self._account_cache and (now - self._cache_time < 3):
            return self._account_cache
        
        try:
            self._account_cache = self.binance.client.futures_account()
            self._cache_time = now
            return self._account_cache
        except Exception as e:
            print(f"Error fetching account info: {e}")
            return self._account_cache

    def _round_step(self, value, step):
        """根据步长舍入数值"""
        from decimal import Decimal, ROUND_DOWN
        step_str = str(step).rstrip('0')
        return float(Decimal(str(value)).quantize(Decimal(step_str), rounding=ROUND_DOWN))

    @property
    def positions(self):
        """获取实盘当前持仓 (增强版，包含止盈止损显示)"""
        if not self.binance or not self.binance.client:
            return []
        try:
            # 1. 获取所有持仓信息 (使用缓存)
            account = self._get_account_info()
            if not account: return []
            pos_info = account['positions']
            
            # 2. 获取所有挂单信息，用于提取止盈止损价格
            # 增加异常处理和默认值，防止挂单获取失败导致整个持仓列表显示异常
            open_orders = []
            try:
                if not hasattr(self, '_orders_cache') or (time.time() - getattr(self, '_orders_time', 0) > 3):
                    self._orders_cache = self.binance.client.futures_get_open_orders()
                    self._orders_time = time.time()
                open_orders = self._orders_cache or []
            except Exception as e:
                print(f"Warning: Could not fetch open orders: {e}")
                open_orders = getattr(self, '_orders_cache', [])
            
            active_positions = []
            for p in pos_info:
                amt = float(p['positionAmt'])
                if amt != 0:
                    symbol = p['symbol']
                    # 币安双向持仓模式下，p['positionSide'] 会指明是 LONG 还是 SHORT
                    pos_side = p.get('positionSide', 'BOTH')
                    
                    # 如果是单向持仓，根据数量正负判断
                    if pos_side == 'BOTH':
                        side = 'LONG' if amt > 0 else 'SHORT'
                    else:
                        side = pos_side # 'LONG' 或 'SHORT'

                    # 3. 在挂单中寻找该仓位的止盈止损
                    tp_price = None
                    sl_price = None
                    
                    for o in open_orders:
                        if o['symbol'] == symbol:
                            # 检查 positionSide 是否匹配
                            # 在单向持仓模式下，pos_side 是 BOTH，o_pos_side 也是 BOTH
                            # 在双向持仓模式下，pos_side 是 LONG/SHORT，o_pos_side 也是 LONG/SHORT
                            o_pos_side = o.get('positionSide', 'BOTH')
                            if o_pos_side != pos_side:
                                continue
                                
                            o_type = o.get('type', '')
                            o_stop_price = float(o.get('stopPrice', 0))
                            
                            if o_stop_price > 0:
                                # 止盈单
                                if 'TAKE_PROFIT' in o_type:
                                    tp_price = o_stop_price
                                # 止损单
                                elif 'STOP' in o_type:
                                    sl_price = o_stop_price

                    active_positions.append({
                        'id': f"REAL-{symbol}-{side}",
                        'symbol': symbol,
                        'side': side,
                        'amount': abs(amt),
                        'entry_price': float(p['entryPrice']),
                        'leverage': p['leverage'],
                        'margin_mode': '逐仓' if p['isolated'] else '全仓',
                        'tp': tp_price,
                        'sl': sl_price,
                        'owner': '实盘'
                    })
            return active_positions
        except Exception as e:
            print(f"Error fetching real positions: {e}")
            return []

    @property
    def balance(self):
        """获取实盘账户可用余额 (USDT)"""
        if not self.binance or not self.binance.client:
            return 0.0
        try:
            account = self._get_account_info()
            if not account: return self._last_balance
            for asset in account['assets']:
                if asset['asset'] == 'USDT':
                    self._last_balance = float(asset['availableBalance'])
                    return self._last_balance
            return 0.0
        except Exception as e:
            print(f"Error fetching real balance: {e}")
            return self._last_balance

    def get_total_equity(self, current_prices):
        """获取实盘账户总权益"""
        if not self.binance or not self.binance.client:
            return 0.0
        try:
            account = self._get_account_info()
            if not account: return self._last_balance
            return float(account['totalMarginBalance'])
        except:
            return self._last_balance

    def check_tp_sl(self, current_prices):
        """
        实盘模式下，止盈止损由币安服务器处理。
        这里返回空列表以保持接口一致，防止报错。
        """
        return []

    def open_position(self, symbol, side, price, amount_usdt, leverage=1, margin_mode="全仓", tp=None, sl=None, owner="用户"):
        if not self.binance or not self.binance.client:
            return False, "币安客户端未初始化"
        
        try:
            # 获取精度信息
            info = self.binance.get_symbol_info(symbol)
            if not info:
                return False, f"无法获取 {symbol} 的精度信息"
            
            qty_step = 0.001
            price_tick = 0.01
            min_notional = 5.0 
            for f in info['filters']:
                if f['filterType'] == 'LOT_SIZE':
                    qty_step = float(f['stepSize'])
                if f['filterType'] == 'PRICE_FILTER':
                    price_tick = float(f['tickSize'])
                if f['filterType'] == 'MIN_NOTIONAL':
                    min_notional = float(f['notional'])

            # 检查名义价值
            if amount_usdt < min_notional:
                return False, f"下单金额 ({amount_usdt} USDT) 低于该币种最小限制 ({min_notional} USDT)。"

            # 设置杠杆
            try:
                self.binance.client.futures_change_leverage(symbol=symbol, leverage=leverage)
            except Exception as e:
                print(f"Leverage change failed (might be already set): {e}")
            
            # 设置保证金模式
            try:
                target_mode = "ISOLATED" if margin_mode == "逐仓" else "CROSSED"
                self.binance.client.futures_change_margin_type(symbol=symbol, marginType=target_mode)
            except:
                pass 

            # 计算并修正数量精度
            quantity = self._round_step(amount_usdt / price, qty_step)
            if quantity <= 0:
                return False, f"下单数量过小，请增加下单金额"
            
            # 检测持仓模式 (单向/双向)
            mode_info = self.binance.client.futures_get_position_mode()
            is_hedge = mode_info.get('dualSidePosition', False)

            # 下单参数
            order_params = {
                'symbol': symbol,
                'type': ORDER_TYPE_MARKET,
                'quantity': quantity
            }

            if is_hedge:
                # 双向持仓模式
                order_params['side'] = SIDE_BUY if side == 'LONG' else SIDE_SELL
                order_params['positionSide'] = 'LONG' if side == 'LONG' else 'SHORT'
            else:
                # 单向持仓模式
                order_params['side'] = SIDE_BUY if side == 'LONG' else SIDE_SELL

            # 执行开仓
            order = self.binance.client.futures_create_order(**order_params)
            self.trade_history.append(f"[{owner}] 主订单已成交: {side} {symbol} 数量 {quantity}")
            
            # 设置止盈止损
            if tp or sl:
                # 增加延迟，确保主订单在币安撮合引擎中完全成交并生成持仓
                import time
                time.sleep(2.0) 
                
                # 智能方向校验与修正
                if tp and sl:
                    if side == 'LONG':
                        if tp < sl: tp, sl = sl, tp 
                    else:
                        if tp > sl: tp, sl = sl, tp 

                tp_sl_side = SIDE_SELL if side == 'LONG' else SIDE_BUY
                
                # 止盈
                if tp and float(tp) > 0:
                    try:
                        tp_price = self._round_step(tp, price_tick)
                        tp_params = {
                            'symbol': symbol,
                            'side': tp_sl_side,
                            'type': 'TAKE_PROFIT_MARKET',
                            'stopPrice': tp_price,
                            'closePosition': True,
                            'workingType': 'MARK_PRICE', # 手机端默认通常是标记价格触发
                            'priceProtect': True
                        }
                        if is_hedge: tp_params['positionSide'] = 'LONG' if side == 'LONG' else 'SHORT'
                        
                        self.binance.client.futures_create_order(**tp_params)
                        self.trade_history.append(f"[{owner}] 止盈单挂单成功: {tp_price}")
                    except Exception as e:
                        self.trade_history.append(f"[{owner}] 止盈挂单失败: {str(e)}")

                # 在止盈和止损单之间增加一个小延迟，防止请求过快
                time.sleep(0.5)

                # 止损
                if sl and float(sl) > 0:
                    try:
                        sl_price = self._round_step(sl, price_tick)
                        sl_params = {
                            'symbol': symbol,
                            'side': tp_sl_side,
                            'type': 'STOP_MARKET',
                            'stopPrice': sl_price,
                            'closePosition': True,
                            'workingType': 'MARK_PRICE',
                            'priceProtect': True
                        }
                        if is_hedge: sl_params['positionSide'] = 'LONG' if side == 'LONG' else 'SHORT'
                        
                        self.binance.client.futures_create_order(**sl_params)
                        self.trade_history.append(f"[{owner}] 止损单挂单成功: {sl_price}")
                    except Exception as e:
                        self.trade_history.append(f"[{owner}] 止损挂单失败: {str(e)}")

            return True, f"实盘成功开仓 {side} {symbol}"
        except Exception as e:
            return False, f"实盘开仓失败: {str(e)}"

    def close_position(self, symbol, side, quantity, current_price):
        """实盘平仓"""
        if not self.binance or not self.binance.client:
            return False, "币安客户端未初始化"
        try:
            mode_info = self.binance.client.futures_get_position_mode()
            is_hedge = mode_info.get('dualSidePosition', False)

            order_params = {
                'symbol': symbol,
                'type': ORDER_TYPE_MARKET,
                'quantity': quantity
            }

            if is_hedge:
                # 双向持仓平仓：LONG 仓位用 SELL 平，SHORT 仓位用 BUY 平
                order_params['side'] = SIDE_SELL if side == 'LONG' else SIDE_BUY
                order_params['positionSide'] = side # LONG 或 SHORT
            else:
                # 单向持仓平仓：反向市价单
                order_params['side'] = SIDE_SELL if side == 'LONG' else SIDE_BUY
                order_params['reduceOnly'] = True

            self.binance.client.futures_create_order(**order_params)
            self.trade_history.append(f"实盘平仓 {symbol}: 价格 {current_price}")
            return True, "实盘平仓成功"
        except Exception as e:
            return False, f"实盘平仓失败: {str(e)}"
