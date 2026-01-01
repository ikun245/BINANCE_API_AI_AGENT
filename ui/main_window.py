import sys
import pandas as pd
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QLineEdit, QPushButton, QTextEdit, QComboBox, QSpinBox, QCheckBox,
                             QTableWidget, QTableWidgetItem, QCompleter, QHeaderView, QDialog, QFormLayout)
from PyQt5.QtCore import QTimer, Qt, QThread, pyqtSignal, QObject
import pyqtgraph as pg
from binance_client import BinanceDataClient
from ai_client import CryptoAIAdvisor
from trading_engine import SimulatedTradingEngine, BinanceTradingEngine
import config

# 配置对话框
class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("系统配置")
        self.setMinimumWidth(400)
        layout = QFormLayout(self)

        self.api_key = QLineEdit(config.BINANCE_API_KEY)
        self.api_secret = QLineEdit(config.BINANCE_SECRET_KEY)
        self.api_secret.setEchoMode(QLineEdit.Password)
        
        self.ai_key = QLineEdit(config.DEEPSEEK_API_KEY)
        self.ai_key.setEchoMode(QLineEdit.Password)
        self.ai_base_url = QLineEdit(config.DEEPSEEK_BASE_URL)
        self.ai_model = QLineEdit(config.DEEPSEEK_MODEL)
        
        self.proxy = QLineEdit(config.PROXY_URL or "")
        self.proxy.setPlaceholderText("例如: http://127.0.0.1:7890")
        
        self.default_amount = QSpinBox()
        self.default_amount.setRange(5, 10000)
        self.default_amount.setValue(int(config.DEFAULT_TRADE_AMOUNT))
        self.default_amount.setSuffix(" USDT")

        layout.addRow("币安 API Key:", self.api_key)
        layout.addRow("币安 API Secret:", self.api_secret)
        layout.addRow("AI API Key:", self.ai_key)
        layout.addRow("AI Base URL:", self.ai_base_url)
        layout.addRow("AI Model:", self.ai_model)
        layout.addRow("代理地址 (可选):", self.proxy)
        layout.addRow("默认下单金额:", self.default_amount)

        self.save_btn = QPushButton("保存并重启应用")
        self.save_btn.clicked.connect(self.save_and_close)
        layout.addRow(self.save_btn)

    def save_and_close(self):
        new_config = {
            "BINANCE_API_KEY": self.api_key.text(),
            "BINANCE_SECRET_KEY": self.api_secret.text(),
            "DEEPSEEK_API_KEY": self.ai_key.text(),
            "DEEPSEEK_BASE_URL": self.ai_base_url.text(),
            "DEEPSEEK_MODEL": self.ai_model.text(),
            "PROXY_URL": self.proxy.text() if self.proxy.text() else None,
            "DEFAULT_TRADE_AMOUNT": float(self.default_amount.value())
        }
        config.save_config(new_config)
        self.accept()

# 自定义 K 线图形项 (Candlestick)
class CandlestickItem(pg.GraphicsObject):
    def __init__(self, data):
        pg.GraphicsObject.__init__(self)
        self.data = data  # [ (t, open, close, low, high), ... ]
        self.generatePicture()

    def generatePicture(self):
        self.picture = pg.QtGui.QPicture()
        p = pg.QtGui.QPainter(self.picture)
        p.setPen(pg.mkPen('k', width=0.5))
        w = 0.6
        for t, open_val, close_val, low_val, high_val in self.data:
            if open_val > close_val:
                p.setBrush(pg.mkBrush('#f6465d')) # 跌：红色
            else:
                p.setBrush(pg.mkBrush('#2ebd85')) # 涨：绿色
            
            p.drawLine(pg.QtCore.QPointF(t, low_val), pg.QtCore.QPointF(t, high_val))
            p.drawRect(pg.QtCore.QRectF(t - w/2, open_val, w, close_val - open_val))
        p.end()

    def paint(self, p, *args):
        p.drawPicture(0, 0, self.picture)

    def boundingRect(self):
        return pg.QtCore.QRectF(self.picture.boundingRect())

# 异步数据获取工作者
class DataWorker(QThread):
    data_received = pyqtSignal(object)
    error_occurred = pyqtSignal(str)

    def __init__(self, binance_client, symbol):
        super().__init__()
        self.binance = binance_client
        self.symbol = symbol

    def run(self):
        try:
            df = self.binance.get_klines(self.symbol)
            if df is not None:
                self.data_received.emit(df)
            else:
                self.error_occurred.emit("获取数据失败")
        except Exception as e:
            self.error_occurred.emit(str(e))

# 异步 AI 工作者
class AIWorker(QThread):
    response_received = pyqtSignal(str)

    def __init__(self, ai_client, symbol, summary, query):
        super().__init__()
        self.ai = ai_client
        self.symbol = symbol
        self.summary = summary
        self.query = query

    def run(self):
        try:
            advice = self.ai.get_advice(self.symbol, self.summary, self.query)
            self.response_received.emit(advice)
        except Exception as e:
            self.response_received.emit(f"AI 错误: {str(e)}")

# 异步账户信息获取工作者
class AccountWorker(QThread):
    account_data_received = pyqtSignal(dict)

    def __init__(self, trading_engine, current_prices):
        super().__init__()
        self.trading = trading_engine
        self.current_prices = current_prices

    def run(self):
        try:
            # 在后台线程获取所有账户数据，避免阻塞 UI
            data = {
                'balance': self.trading.balance,
                'equity': self.trading.get_total_equity(self.current_prices),
                'positions': self.trading.positions
            }
            self.account_data_received.emit(data)
        except Exception as e:
            print(f"AccountWorker Error: {e}")

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Bianlance - 币安合约监控与AI助手 (专业版)")
        self.setGeometry(100, 100, 1500, 950)

        self.binance = BinanceDataClient()
        self.ai = CryptoAIAdvisor()
        self.sim_trading = SimulatedTradingEngine()
        self.real_trading = BinanceTradingEngine(self.binance)
        self.trading = self.sim_trading # 默认使用模拟交易
        
        self.current_symbol = config.DEFAULT_SYMBOLS[0]
        self.all_symbols = []
        self.last_df = None
        self.ai_auto_trade = False
        self.last_ai_signal = None # 存储最新的 AI 信号
        
        # 缓存绘图对象，避免 clear() 导致 UI 闪烁和输入法中断
        self.candlestick_item = None
        self.ma_line_item = None
        
        self.init_ui()
        self.load_symbols()
        
        # 定时器更新数据
        self.timer = QTimer()
        self.timer.timeout.connect(self.refresh_data)
        self.timer.start(2000) # 增加到 2 秒，减少 API 压力

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        # 左侧：K线图和交易
        left_panel = QVBoxLayout()
        
        # 搜索和选择
        search_layout = QHBoxLayout()
        self.symbol_input = QLineEdit()
        self.symbol_input.setPlaceholderText("搜索合约 (如 BTCUSDT)...")
        self.symbol_input.returnPressed.connect(self.on_search_symbol)
        
        self.search_btn = QPushButton("切换")
        self.search_btn.clicked.connect(self.on_search_symbol)
        
        self.settings_btn = QPushButton("⚙ 系统设置")
        self.settings_btn.clicked.connect(self.open_settings)
        
        self.reset_view_btn = QPushButton("重置视图")
        self.reset_view_btn.clicked.connect(self.reset_chart_view)
        
        search_layout.addWidget(QLabel("合约搜索:"))
        search_layout.addWidget(self.symbol_input)
        search_layout.addWidget(self.search_btn)
        search_layout.addWidget(self.settings_btn)
        search_layout.addWidget(self.reset_view_btn)
        left_panel.addLayout(search_layout)

        # K线图
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('w')
        self.plot_widget.showGrid(x=True, y=True)
        self.plot_widget.setFocusPolicy(Qt.NoFocus) # 防止抢占焦点
        left_panel.addWidget(self.plot_widget)

        # 实时价格大字显示
        self.price_display = QLabel("加载中...")
        self.price_display.setStyleSheet("font-size: 28px; font-weight: bold; color: #2ebd85; margin: 5px;")
        self.price_display.setAlignment(Qt.AlignCenter)
        self.price_display.setFocusPolicy(Qt.NoFocus)
        left_panel.addWidget(self.price_display)
        
        # 交易控制面板
        trade_panel = QVBoxLayout()
        
        # 交易模式切换
        mode_layout = QHBoxLayout()
        self.trade_mode_combo = QComboBox()
        self.trade_mode_combo.addItems(["模拟交易", "实盘交易"])
        self.trade_mode_combo.currentIndexChanged.connect(self.on_trade_mode_changed)
        mode_layout.addWidget(QLabel("交易模式:"))
        mode_layout.addWidget(self.trade_mode_combo)
        trade_panel.addLayout(mode_layout)

        # 第一行：金额和方向
        row1 = QHBoxLayout()
        self.amount_input = QLineEdit()
        self.amount_input.setPlaceholderText("总价值 (USDT)")
        self.amount_input.setText(str(config.DEFAULT_TRADE_AMOUNT)) # 设置默认初始值
        
        self.long_btn = QPushButton("看涨 (做多)")
        self.long_btn.setStyleSheet("background-color: #2ebd85; color: white; font-weight: bold; padding: 10px;")
        self.long_btn.clicked.connect(lambda: self.handle_trade('LONG'))
        
        self.short_btn = QPushButton("看跌 (做空)")
        self.short_btn.setStyleSheet("background-color: #f6465d; color: white; font-weight: bold; padding: 10px;")
        self.short_btn.clicked.connect(lambda: self.handle_trade('SHORT'))
        
        row1.addWidget(QLabel("下单总价值:"))
        row1.addWidget(self.amount_input)
        row1.addWidget(self.long_btn)
        row1.addWidget(self.short_btn)
        trade_panel.addLayout(row1)
        
        # 第二行：止盈止损
        row2 = QHBoxLayout()
        self.tp_input = QLineEdit()
        self.tp_input.setPlaceholderText("止盈价格 (可选)")
        self.sl_input = QLineEdit()
        self.sl_input.setPlaceholderText("止损价格 (可选)")
        
        row2.addWidget(QLabel("止盈价格:"))
        row2.addWidget(self.tp_input)
        row2.addWidget(QLabel("止损价格:"))
        row2.addWidget(self.sl_input)
        trade_panel.addLayout(row2)

        # 杠杆和模式
        row_leverage = QHBoxLayout()
        self.leverage_input = QSpinBox()
        self.leverage_input.setRange(1, 125)
        self.leverage_input.setValue(10)
        
        self.margin_mode_input = QComboBox()
        self.margin_mode_input.addItems(["全仓", "逐仓"])
        
        row_leverage.addWidget(QLabel("杠杆倍数:"))
        row_leverage.addWidget(self.leverage_input)
        row_leverage.addWidget(QLabel("保证金模式:"))
        row_leverage.addWidget(self.margin_mode_input)
        trade_panel.addLayout(row_leverage)
        
        # 第三行：AI 自动交易控制
        row3 = QHBoxLayout()
        self.ai_toggle_btn = QPushButton("开启 AI 自动跟单交易")
        self.ai_toggle_btn.setStyleSheet("background-color: #f39c12; color: white; font-weight: bold; padding: 10px;")
        self.ai_toggle_btn.setCheckable(True)
        self.ai_toggle_btn.toggled.connect(self.toggle_ai_trade)
        
        self.ai_strategy_combo = QComboBox()
        self.ai_strategy_combo.addItems(["保守型 (CONS)", "激进型 (AGGR)"])
        self.ai_strategy_combo.setToolTip("选择 AI 自动交易或跟单时使用的止盈止损策略")
        
        self.ai_fill_checkbox = QCheckBox("AI 自动填入止盈止损")
        self.ai_fill_checkbox.setChecked(True) # 默认开启
        self.ai_fill_checkbox.setStyleSheet("font-weight: bold; color: #8e44ad;")
        
        self.ai_status_label = QLabel("AI 状态: 休息中")
        self.ai_profit_label = QLabel("账户总盈亏: 0.00 USDT")
        self.ai_profit_label.setStyleSheet("font-weight: bold; color: #2980b9;")
        
        row3.addWidget(self.ai_toggle_btn)
        row3.addWidget(QLabel("AI策略:"))
        row3.addWidget(self.ai_strategy_combo)
        row3.addWidget(self.ai_fill_checkbox)
        row3.addWidget(self.ai_status_label)
        row3.addWidget(self.ai_profit_label)
        trade_panel.addLayout(row3)

        # 第四行：AI 信号手动操作
        row4 = QHBoxLayout()
        self.follow_btn = QPushButton("一键跟单 (AI信号)")
        self.follow_btn.setEnabled(False)
        self.follow_btn.setStyleSheet("background-color: #8e44ad; color: white; font-weight: bold; padding: 8px;")
        self.follow_btn.clicked.connect(self.handle_follow_ai)
        
        self.reverse_btn = QPushButton("一键反买 (对冲AI)")
        self.reverse_btn.setEnabled(False)
        self.reverse_btn.setStyleSheet("background-color: #d35400; color: white; font-weight: bold; padding: 8px;")
        self.reverse_btn.clicked.connect(self.handle_reverse_ai)
        
        row4.addWidget(self.follow_btn)
        row4.addWidget(self.reverse_btn)
        trade_panel.addLayout(row4)
        
        left_panel.addLayout(trade_panel)

        # 账户与持仓
        info_layout = QHBoxLayout()
        self.balance_label = QLabel(f"可用余额: {self.trading.balance:.2f} USDT")
        self.balance_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #333;")
        self.equity_label = QLabel(f"账户权益: {self.trading.balance:.2f} USDT")
        self.equity_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #2980b9;")
        
        info_layout.addWidget(self.balance_label)
        info_layout.addWidget(self.equity_label)
        left_panel.addLayout(info_layout)

        self.position_table = QTableWidget(0, 7)
        self.position_table.setHorizontalHeaderLabels(["ID", "币种", "方向", "数量", "入场价", "止盈/止损", "操作"])
        self.position_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.position_table.setFocusPolicy(Qt.NoFocus) # 防止抢占焦点
        left_panel.addWidget(QLabel("当前持仓 (双向持仓支持):"))
        left_panel.addWidget(self.position_table)

        # 右侧：AI 助手与决策日志
        right_panel = QVBoxLayout()
        
        # 上半部分：AI 对话
        right_panel.addWidget(QLabel("AI 加密货币指导师 (对话)"))
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_display.setFocusPolicy(Qt.NoFocus) # 防止抢占焦点
        self.chat_display.setStyleSheet("background-color: #f9f9f9; border: 1px solid #ddd; font-family: 'Microsoft YaHei';")
        right_panel.addWidget(self.chat_display, 2) # 权重为 2
        
        self.chat_input = QLineEdit()
        self.chat_input.setPlaceholderText("向AI提问...")
        self.chat_input.setAttribute(Qt.WA_InputMethodEnabled) # 显式启用输入法
        self.chat_input.returnPressed.connect(self.handle_ai_chat)
        self.send_btn = QPushButton("发送")
        self.send_btn.clicked.connect(self.handle_ai_chat)
        
        chat_input_layout = QHBoxLayout()
        chat_input_layout.addWidget(self.chat_input)
        chat_input_layout.addWidget(self.send_btn)
        right_panel.addLayout(chat_input_layout)

        # 下半部分：AI 决策与交易日志
        right_panel.addWidget(QLabel("AI 决策与交易日志"))
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setFocusPolicy(Qt.NoFocus) # 防止抢占焦点
        self.log_display.setStyleSheet("background-color: #2c3e50; color: #ecf0f1; border: 1px solid #34495e; font-family: 'Consolas'; font-size: 12px;")
        right_panel.addWidget(self.log_display, 1) # 权重为 1

        # 底部免责声明
        disclaimer = QLabel("本产品仅供学习，加密市场风险高，切勿用于真实交易")
        disclaimer.setStyleSheet("color: #95a5a6; font-size: 10px; margin-top: 5px;")
        disclaimer.setAlignment(Qt.AlignRight)
        right_panel.addWidget(disclaimer)

        main_layout.addLayout(left_panel, 3)
        main_layout.addLayout(right_panel, 1)

    def load_symbols(self):
        if not self.binance.client:
            self.log_display.append("系统错误: 无法连接到币安服务器。")
            return
        self.all_symbols = self.binance.get_all_symbols()
        if self.all_symbols:
            completer = QCompleter(self.all_symbols)
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            completer.setFilterMode(Qt.MatchContains)
            self.symbol_input.setCompleter(completer)

    def on_search_symbol(self):
        raw_symbol = self.symbol_input.text().upper().replace(":", "").replace("/", "")
        if "USDT" in raw_symbol:
            symbol = raw_symbol.split("USDT")[0] + "USDT"
        else:
            symbol = raw_symbol

        if symbol in self.all_symbols or not self.all_symbols:
            self.current_symbol = symbol
            self.refresh_data()
            self.log_display.append(f"系统: 已切换至 {symbol}")
            self.reset_chart_view()
        else:
            self.log_display.append(f"系统: 未找到交易对 {symbol}")

    def reset_chart_view(self):
        if self.last_df is not None:
            self.plot_widget.setXRange(0, len(self.last_df))
            y_min = self.last_df['low'].min() * 0.998
            y_max = self.last_df['high'].max() * 1.002
            self.plot_widget.setYRange(y_min, y_max)

    def refresh_data(self):
        if not self.binance.client: return
        if hasattr(self, 'data_worker') and self.data_worker.isRunning():
            return
        self.data_worker = DataWorker(self.binance, self.current_symbol)
        self.data_worker.data_received.connect(self.on_data_received)
        self.data_worker.start()

    def on_data_received(self, df):
        self.last_df = df
        self.plot_klines(df)
        price = df['close'].iloc[-1]
        
        # 更新价格显示
        prev_price_text = self.price_display.text().replace(" USDT", "")
        try:
            prev_price = float(prev_price_text)
            color = "#2ebd85" if price >= prev_price else "#f6465d"
            # 只有颜色变化时才更新样式表，减少重绘开销
            if not hasattr(self, '_last_price_color') or self._last_price_color != color:
                self.price_display.setStyleSheet(f"font-size: 28px; font-weight: bold; color: {color}; margin: 5px;")
                self._last_price_color = color
        except:
            pass
        self.price_display.setText(f"{price} USDT")
        
        # 异步获取账户和持仓信息，不再阻塞 UI 线程
        if not hasattr(self, 'account_worker') or not self.account_worker.isRunning():
            self.account_worker = AccountWorker(self.trading, {self.current_symbol: price})
            self.account_worker.account_data_received.connect(self.on_account_data_received)
            self.account_worker.start()
        
        # 检查止盈止损 (仅模拟模式需要本地检查)
        if self.trading == self.sim_trading:
            msgs = self.trading.check_tp_sl({self.current_symbol: price})
            for m in msgs:
                self.log_display.append(f"系统: {m}")
        
        self.run_ai_auto_logic(df)

    def on_account_data_received(self, data):
        """处理异步返回的账户数据并更新 UI"""
        self._last_known_positions = data['positions'] # 缓存持仓数据用于安全检查
        
        self.balance_label.setText(f"可用余额: {data['balance']:.2f} USDT")
        equity = data['equity']
        self.equity_label.setText(f"账户权益: {equity:.2f} USDT")
        
        # 计算盈亏显示
        if self.trading == self.sim_trading:
            total_profit = equity - 10000.0
            self.ai_profit_label.setText(f"模拟总盈亏: {total_profit:.2f} USDT")
            self.ai_profit_label.setStyleSheet(f"font-weight: bold; color: {'#2ebd85' if total_profit >= 0 else '#f6465d'};")
        else:
            self.ai_profit_label.setText(f"实盘模式 (API 已连接)")
            self.ai_profit_label.setStyleSheet("font-weight: bold; color: #2980b9;")
        
        # 更新持仓表格
        self.position_table.blockSignals(True)
        self.position_table.setRowCount(0)
        for pos in data['positions']:
            self.add_position_row(pos)
        self.position_table.blockSignals(False)

    def plot_klines(self, df):
        # 移除旧对象而不是 clear() 全局，减少对 UI 线程的冲击
        if self.candlestick_item:
            self.plot_widget.removeItem(self.candlestick_item)
        if self.ma_line_item:
            self.plot_widget.removeItem(self.ma_line_item)

        data = []
        for i in range(len(df)):
            data.append((i, df['open'].iloc[i], df['close'].iloc[i], df['low'].iloc[i], df['high'].iloc[i]))
        
        self.candlestick_item = CandlestickItem(data)
        self.plot_widget.addItem(self.candlestick_item)
        
        ma5 = df['close'].rolling(window=5).mean()
        self.ma_line_item = self.plot_widget.plot(range(len(ma5)), ma5.values, pen=pg.mkPen('#2980b9', width=1.5))

    def handle_trade(self, side):
        try:
            amount_str = self.amount_input.text().strip()
            amount = float(amount_str) if amount_str else config.DEFAULT_TRADE_AMOUNT
            
            price = self.binance.get_ticker_price(self.current_symbol)
            
            tp_str = self.tp_input.text().strip()
            sl_str = self.sl_input.text().strip()
            tp = float(tp_str) if tp_str else None
            sl = float(sl_str) if sl_str else None
            
            leverage = self.leverage_input.value()
            margin_mode = self.margin_mode_input.currentText()
            
            # 异步执行交易，防止 UI 卡死
            self.log_display.append(f"系统: 正在提交 {side} 订单...")
            
            class TradeWorker(QThread):
                finished = pyqtSignal(bool, str)
                def __init__(self, engine, symbol, side, price, amount, leverage, margin_mode, tp, sl):
                    super().__init__()
                    self.engine = engine
                    self.symbol = symbol
                    self.side = side
                    self.price = price
                    self.amount = amount
                    self.leverage = leverage
                    self.margin_mode = margin_mode
                    self.tp = tp
                    self.sl = sl
                def run(self):
                    success, msg = self.engine.open_position(
                        self.symbol, self.side, self.price, self.amount, 
                        leverage=self.leverage, margin_mode=self.margin_mode, tp=self.tp, sl=self.sl
                    )
                    self.finished.emit(success, msg)

            self.trade_worker = TradeWorker(self.trading, self.current_symbol, side, price, amount, leverage, margin_mode, tp, sl)
            self.trade_worker.finished.connect(lambda success, msg: self.on_trade_finished(success, msg, price))
            self.trade_worker.start()
            
        except ValueError:
            self.log_display.append("系统: 请输入有效的数值 (下单金额/止盈/止损)")

    def on_trade_finished(self, success, msg, price):
        self.log_display.append(f"系统: {msg}")
        self.refresh_account_info(price)

    def refresh_account_info(self, price):
        if not hasattr(self, 'account_worker') or not self.account_worker.isRunning():
            self.account_worker = AccountWorker(self.trading, {self.current_symbol: price})
            self.account_worker.account_data_received.connect(self.on_account_data_received)
            self.account_worker.start()

    def update_account_ui(self, current_prices):
        try:
            balance = self.trading.balance
            self.balance_label.setText(f"可用余额: {balance:.2f} USDT")
            equity = self.trading.get_total_equity(current_prices)
            self.equity_label.setText(f"账户权益: {equity:.2f} USDT")
            
            # 计算盈亏
            if self.trading == self.sim_trading:
                total_profit = equity - 10000.0
                self.ai_profit_label.setText(f"模拟总盈亏: {total_profit:.2f} USDT")
            else:
                # 实盘盈亏逻辑可以更复杂，这里简单显示
                self.ai_profit_label.setText(f"实盘模式 (API 已连接)")
                total_profit = 0 # 实盘不显示相对于 10000 的盈亏
                
            self.ai_profit_label.setStyleSheet(f"font-weight: bold; color: {'#2ebd85' if total_profit >= 0 else '#f6465d'};")
        except Exception as e:
            print(f"UI Update Error: {e}")
        
        self.position_table.blockSignals(True)
        self.position_table.setRowCount(0)
        # 显示所有持仓
        for pos in self.trading.positions:
            self.add_position_row(pos)
        self.position_table.blockSignals(False)

    def add_position_row(self, pos):
        row = self.position_table.rowCount()
        self.position_table.insertRow(row)
        owner = pos.get('owner', '用户')
        self.position_table.setItem(row, 0, QTableWidgetItem(f"{owner}-{pos['id']}"))
        
        symbol_text = f"{pos['symbol']} ({pos.get('leverage', 1)}x {pos.get('margin_mode', '全仓')})"
        self.position_table.setItem(row, 1, QTableWidgetItem(symbol_text))
        
        side_item = QTableWidgetItem(pos['side'])
        side_item.setForeground(pg.mkColor('#2ebd85' if pos['side'] == 'LONG' else '#f6465d'))
        self.position_table.setItem(row, 2, side_item)
        
        self.position_table.setItem(row, 3, QTableWidgetItem(f"{pos['amount']:.4f}"))
        self.position_table.setItem(row, 4, QTableWidgetItem(f"{pos['entry_price']:.6f}".rstrip('0').rstrip('.')))
        
        # 优化止盈止损显示格式
        tp_val = pos.get('tp')
        sl_val = pos.get('sl')
        tp_text = f"{tp_val:.6f}".rstrip('0').rstrip('.') if tp_val else "-"
        sl_text = f"{sl_val:.6f}".rstrip('0').rstrip('.') if sl_val else "-"
        self.position_table.setItem(row, 5, QTableWidgetItem(f"止盈:{tp_text} / 止损:{sl_text}"))
        
        close_btn = QPushButton("平仓")
        close_btn.clicked.connect(lambda checked, p_id=pos['id']: self.handle_close(p_id))
        self.position_table.setCellWidget(row, 6, close_btn)

    def handle_close(self, pos_id):
        price = self.binance.get_ticker_price(self.current_symbol)
        
        # 区分模拟和实盘平仓
        if self.trading == self.sim_trading:
            success, msg = self.trading.close_position(pos_id, price)
        else:
            # 实盘平仓需要从表格中获取 symbol, side, amount
            for row in range(self.position_table.rowCount()):
                if self.position_table.item(row, 0).text().endswith(pos_id):
                    symbol_full = self.position_table.item(row, 1).text()
                    symbol = symbol_full.split(' ')[0]
                    side = self.position_table.item(row, 2).text()
                    amount = float(self.position_table.item(row, 3).text())
                    success, msg = self.trading.close_position(symbol, side, amount, price)
                    break
            else:
                success, msg = False, "未找到实盘持仓数据"

        self.log_display.append(f"系统: {msg}")
        self.refresh_account_info(price)

    def toggle_ai_trade(self, enabled):
        self.ai_auto_trade = enabled
        if enabled:
            self.ai_toggle_btn.setText("关闭 AI 自动跟单交易")
            self.ai_toggle_btn.setStyleSheet("background-color: #7f8c8d; color: white; font-weight: bold; padding: 10px;")
            self.ai_status_label.setText("AI 状态: 正在扫描行情...")
            self.log_display.append("系统: AI 自动交易已开启，AI 将根据行情自主决策。")
        else:
            self.ai_toggle_btn.setText("开启 AI 自动跟单交易")
            self.ai_toggle_btn.setStyleSheet("background-color: #f39c12; color: white; font-weight: bold; padding: 10px;")
            self.ai_status_label.setText("AI 状态: 休息中")
            self.log_display.append("系统: AI 自动交易已关闭。")

    def run_ai_auto_logic(self, df):
        # 即使不开启自动交易，也每 30 秒获取一次 AI 信号供手动跟单
        
        # 避免过于频繁的 AI 请求
        if not hasattr(self, 'last_ai_decision_time'):
            self.last_ai_decision_time = 0
        
        import time
        current_time = time.time()
        if current_time - self.last_ai_decision_time < 30:
            return
            
        self.last_ai_decision_time = current_time
        self.ai_status_label.setText("AI 状态: 正在获取信号...")
        
        price = df['close'].iloc[-1]
        ma5 = df['close'].rolling(5).mean().iloc[-1]
        volatility = df['high'].max() - df['low'].min()
        summary = f"当前价格: {price}, MA5: {ma5:.6f}, 波动率: {volatility:.6f}"
        
        # 异步获取 AI 决策
        class AIDecisionWorker(QThread):
            decision_received = pyqtSignal(str)
            def __init__(self, ai_client, symbol, data):
                super().__init__()
                self.ai = ai_client
                self.symbol = symbol
                self.data = data
            def run(self):
                res = self.ai.get_trade_decision(self.symbol, self.data)
                self.decision_received.emit(res)

        self.decision_worker = AIDecisionWorker(self.ai, self.current_symbol, summary)
        self.decision_worker.decision_received.connect(self.process_ai_decision)
        self.decision_worker.start()

    def process_ai_decision(self, res):
        # 解析格式: ACTION:LONG/SHORT/HOLD, TP_CONS:price, SL_CONS:price, TP_AGGR:price, SL_AGGR:price, LEVERAGE:num, MARGIN_MODE:全仓/逐仓, REASON:text
        try:
            parts = {p.split(':')[0].strip(): p.split(':')[1].strip() for p in res.split(',')}
            action = parts.get('ACTION', 'HOLD')
            reason = parts.get('REASON', '无')
            
            self.ai_status_label.setText(f"AI 信号: {action}")
            self.log_display.append(f"[{self.current_symbol}] AI 信号: {action} | 理由: {reason}")
            
            if action in ['LONG', 'SHORT']:
                # 根据选择的策略提取止盈止损
                is_aggr = "AGGR" in self.ai_strategy_combo.currentText()
                tp_key = 'TP_AGGR' if is_aggr else 'TP_CONS'
                sl_key = 'SL_AGGR' if is_aggr else 'SL_CONS'
                
                tp_val = parts.get(tp_key, 'NONE')
                sl_val = parts.get(sl_key, 'NONE')

                # 存储信号供手动操作
                self.last_ai_signal = {
                    'side': action,
                    'tp': float(tp_val) if tp_val != 'NONE' else None,
                    'sl': float(sl_val) if sl_val != 'NONE' else None,
                    'tp_cons': float(parts.get('TP_CONS', 0)) if parts.get('TP_CONS', 'NONE') != 'NONE' else None,
                    'sl_cons': float(parts.get('SL_CONS', 0)) if parts.get('SL_CONS', 'NONE') != 'NONE' else None,
                    'tp_aggr': float(parts.get('TP_AGGR', 0)) if parts.get('TP_AGGR', 'NONE') != 'NONE' else None,
                    'sl_aggr': float(parts.get('SL_AGGR', 0)) if parts.get('SL_AGGR', 'NONE') != 'NONE' else None,
                    'leverage': self.leverage_input.value(),
                    'margin_mode': self.margin_mode_input.currentText()
                }
                self.follow_btn.setEnabled(True)
                self.reverse_btn.setEnabled(True)
                self.follow_btn.setText(f"一键跟单 ({action})")
                self.reverse_btn.setText(f"一键反买 ({'SHORT' if action == 'LONG' else 'LONG'})")

                # 智能填入止盈止损到输入框 (仅当勾选了自动填入时)
                if self.ai_fill_checkbox.isChecked():
                    if self.last_ai_signal['tp']:
                        self.tp_input.setText(str(self.last_ai_signal['tp']))
                    if self.last_ai_signal['sl']:
                        self.sl_input.setText(str(self.last_ai_signal['sl']))

                # 如果开启了自动交易，则直接执行
                if self.ai_auto_trade:
                    # --- 安全检查：防止重复开仓 ---
                    # 1. 获取最新持仓（从最近一次 AccountWorker 更新的数据中获取）
                    # 如果数据还没回来，为了安全，我们假设有持仓，不进行自动交易
                    if not hasattr(self, '_last_known_positions'):
                        self.log_display.append("AI 系统: 正在等待账户数据同步，暂不执行自动开仓。")
                        return
                    
                    current_pos = self._last_known_positions
                    # 检查该币种是否已有任何方向的持仓
                    existing_pos = [p for p in current_pos if p['symbol'] == self.current_symbol]
                    
                    if existing_pos:
                        self.log_display.append(f"AI 系统: {self.current_symbol} 已有持仓，跳过自动开仓以防止重仓。")
                        return

                    self.log_display.append(f"AI 系统: 正在为 {self.current_symbol} 执行自动开仓...")
                    price = self.binance.get_ticker_price(self.current_symbol)
                    
                    try:
                        amount = float(self.amount_input.text())
                    except:
                        amount = config.DEFAULT_TRADE_AMOUNT

                    # 自动交易也使用异步 Worker
                    class AutoTradeWorker(QThread):
                        finished = pyqtSignal(bool, str)
                        def __init__(self, engine, symbol, side, price, amount, leverage, margin_mode, tp, sl):
                            super().__init__()
                            self.engine = engine
                            self.symbol = symbol
                            self.side = side
                            self.price = price
                            self.amount = amount
                            self.leverage = leverage
                            self.margin_mode = margin_mode
                            self.tp = tp
                            self.sl = sl
                        def run(self):
                            success, msg = self.engine.open_position(
                                self.symbol, self.side, self.price, self.amount, 
                                leverage=self.leverage, margin_mode=self.margin_mode, 
                                tp=self.tp, sl=self.sl, owner="AI"
                            )
                            self.finished.emit(success, msg)

                    self.auto_trade_worker = AutoTradeWorker(
                        self.trading, self.current_symbol, action, price, amount, 
                        self.last_ai_signal['leverage'], self.last_ai_signal['margin_mode'], 
                        self.last_ai_signal['tp'], self.last_ai_signal['sl']
                    )
                    self.auto_trade_worker.finished.connect(lambda success, msg: self.on_trade_finished(success, msg, price))
                    self.auto_trade_worker.start()
            else:
                self.last_ai_signal = None
                self.follow_btn.setEnabled(False)
                self.reverse_btn.setEnabled(False)
                self.follow_btn.setText("一键跟单 (无信号)")
                self.reverse_btn.setText("一键反买 (无信号)")

        except Exception as e:
            print(f"AI Decision Parse Error: {e}, Raw: {res}")

    def handle_follow_ai(self):
        if not self.last_ai_signal: return
        price = self.binance.get_ticker_price(self.current_symbol)
        
        try:
            amount_str = self.amount_input.text().strip()
            amount = float(amount_str) if amount_str else config.DEFAULT_TRADE_AMOUNT
        except:
            amount = config.DEFAULT_TRADE_AMOUNT
            
        # 优先使用输入框中的止盈止损
        try:
            tp_str = self.tp_input.text().strip()
            sl_str = self.sl_input.text().strip()
            tp = float(tp_str) if tp_str else None
            sl = float(sl_str) if sl_str else None
        except:
            tp = None
            sl = None

        # 如果输入框为空，则回退到 AI 建议
        if tp is None: tp = self.last_ai_signal['tp']
        if sl is None: sl = self.last_ai_signal['sl']

        self.log_display.append(f"系统: 正在提交 AI 跟单订单 ({self.last_ai_signal['side']})...")
        
        class TradeWorker(QThread):
            finished = pyqtSignal(bool, str)
            def __init__(self, engine, symbol, side, price, amount, leverage, margin_mode, tp, sl, owner):
                super().__init__()
                self.engine = engine
                self.symbol = symbol
                self.side = side
                self.price = price
                self.amount = amount
                self.leverage = leverage
                self.margin_mode = margin_mode
                self.tp = tp
                self.sl = sl
                self.owner = owner
            def run(self):
                success, msg = self.engine.open_position(
                    self.symbol, self.side, self.price, self.amount, 
                    leverage=self.leverage, margin_mode=self.margin_mode, tp=self.tp, sl=self.sl,
                    owner=self.owner
                )
                self.finished.emit(success, msg)

        self.trade_worker = TradeWorker(
            self.trading, self.current_symbol, self.last_ai_signal['side'], price, amount, 
            self.last_ai_signal['leverage'], self.last_ai_signal['margin_mode'], tp, sl, "用户(跟单)"
        )
        self.trade_worker.finished.connect(lambda success, msg: self.on_trade_finished(success, msg, price))
        self.trade_worker.start()

    def handle_reverse_ai(self):
        if not self.last_ai_signal: return
        price = self.binance.get_ticker_price(self.current_symbol)
        reverse_side = 'SHORT' if self.last_ai_signal['side'] == 'LONG' else 'LONG'
        
        try:
            amount_str = self.amount_input.text().strip()
            amount = float(amount_str) if amount_str else config.DEFAULT_TRADE_AMOUNT
        except:
            amount = config.DEFAULT_TRADE_AMOUNT

        # 优先使用输入框中的止盈止损
        try:
            tp_str = self.tp_input.text().strip()
            sl_str = self.sl_input.text().strip()
            tp = float(tp_str) if tp_str else None
            sl = float(sl_str) if sl_str else None
        except:
            tp = None
            sl = None

        if tp is None and sl is None:
            # 反买逻辑：将 AI 的止损设为反买的止盈，AI 的止盈设为反买的止损
            tp = self.last_ai_signal['sl']
            sl = self.last_ai_signal['tp']
            
            # 更新 UI 显示
            if tp: self.tp_input.setText(str(tp))
            if sl: self.sl_input.setText(str(sl))

        self.log_display.append(f"系统: 正在提交 AI 反买订单 ({reverse_side})...")
        
        class TradeWorker(QThread):
            finished = pyqtSignal(bool, str)
            def __init__(self, engine, symbol, side, price, amount, leverage, margin_mode, tp, sl, owner):
                super().__init__()
                self.engine = engine
                self.symbol = symbol
                self.side = side
                self.price = price
                self.amount = amount
                self.leverage = leverage
                self.margin_mode = margin_mode
                self.tp = tp
                self.sl = sl
                self.owner = owner
            def run(self):
                success, msg = self.engine.open_position(
                    self.symbol, self.side, self.price, self.amount, 
                    leverage=self.leverage, margin_mode=self.margin_mode, tp=self.tp, sl=self.sl,
                    owner=self.owner
                )
                self.finished.emit(success, msg)

        self.trade_worker = TradeWorker(
            self.trading, self.current_symbol, reverse_side, price, amount, 
            self.last_ai_signal['leverage'], self.last_ai_signal['margin_mode'], tp, sl, "用户(反买)"
        )
        self.trade_worker.finished.connect(lambda success, msg: self.on_trade_finished(success, msg, price))
        self.trade_worker.start()

    def open_settings(self):
        dialog = SettingsDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            self.log_display.append("系统: 配置已保存，请手动重启程序以应用新设置。")

    def on_trade_mode_changed(self, index):
        if index == 0:
            self.trading = self.sim_trading
            self.log_display.append("系统: 已切换至 模拟交易 模式")
        else:
            self.trading = self.real_trading
            self.log_display.append("系统: 已切换至 实盘交易 模式 (请确保 API Key 有效)")

    def handle_ai_chat(self):
        query = self.chat_input.text()
        if not query: return
        self.chat_display.append(f"你: {query}")
        self.chat_input.clear()
        self.chat_display.append("AI: 正在思考...")
        
        # 获取最新的行情数据摘要
        market_summary = ""
        if self.last_df is not None:
            df = self.last_df
            price = df['close'].iloc[-1]
            ma5 = df['close'].rolling(5).mean().iloc[-1]
            high_24h = df['high'].max()
            low_24h = df['low'].min()
            market_summary = (f"当前价格: {price}, 24h最高: {high_24h}, 24h最低: {low_24h}, "
                              f"MA5: {ma5:.6f}, 波动率: {high_24h - low_24h:.6f}")
        else:
            market_summary = "正在获取实时行情..."

        # 获取账户状态和最近交易历史
        recent_history = "\n".join(self.trading.trade_history[-5:]) # 最近5条记录
        account_summary = (f"可用余额: {self.trading.balance:.2f} USDT, "
                           f"当前持仓数: {len(self.trading.positions)}, "
                           f"最近操作历史: {recent_history}")

        full_summary = f"【市场数据】: {market_summary}\n【账户状态】: {account_summary}"

        self.ai_worker = AIWorker(self.ai, self.current_symbol, full_summary, query)
        self.ai_worker.response_received.connect(self.on_ai_response)
        self.ai_worker.start()

    def on_ai_response(self, advice):
        cursor = self.chat_display.textCursor()
        cursor.movePosition(cursor.End)
        cursor.select(cursor.LineUnderCursor)
        cursor.removeSelectedText()
        self.chat_display.append(f"AI: {advice}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
