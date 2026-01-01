本项目使用python进行构建
主要的目的用于监控币安中多种合约的k线数据，进行综合分析
币安的API密钥
BINANCE_API_KEY=YOUR_BINANCE_API_KEY
BINANCE_SECRET_KEY=YOUR_BINANCE_SECRET_KEY
使用pyqt5构建现代化界面
留出丰富的接口，用于拓展后续功能
首先实现的功能
同时监控5+个合约币的涨幅k线数据
始终确保所有的数据来源于币安api的数据，禁止使用自己编纂的数据
流出ai的接口，可以指定合约的数据，和ai进行对话，ai作为加密货币指导师
# AI 配置 (阿里百炼 DeepSeek)
AI_PROVIDER=deepseek
DEEPSEEK_API_KEY=YOUR_DEEPSEEK_API_KEY
DEEPSEEK_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DEEPSEEK_MODEL=deepseek-v3.2
交易功能
本地模拟交易，买入卖出平仓，看根据k线如何交易可以快速盈利