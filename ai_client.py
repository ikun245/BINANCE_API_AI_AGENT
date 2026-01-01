from openai import OpenAI
import config

class CryptoAIAdvisor:
    def __init__(self):
        self.client = OpenAI(
            api_key=config.DEEPSEEK_API_KEY,
            base_url=config.DEEPSEEK_BASE_URL
        )
        self.model = config.DEEPSEEK_MODEL
        self.chat_history = [] # 存储对话记忆

    def get_advice(self, symbol, market_data, user_query):
        """
        根据市场数据和用户问题提供建议
        """
        system_prompt = (
            "你是一位专业的加密货币投资指导师。你拥有深度思考能力，会先分析市场逻辑再给出建议。"
            "你将分析用户提供的市场数据，并结合历史对话记忆给出专业的见解。"
            "请保持客观、专业，并始终提醒用户加密货币投资具有高风险。"
        )
        
        # 构造当前请求的消息
        current_user_msg = f"【当前行情】\n合约币种: {symbol}\n市场数据: {market_data}\n\n【用户问题】\n{user_query}"
        
        # 构造完整的消息列表（包含记忆）
        messages = [{"role": "system", "content": system_prompt}]
        # 只保留最近 10 条记忆，防止上下文过长
        messages.extend(self.chat_history[-10:])
        messages.append({"role": "user", "content": current_user_msg})
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=False
            )
            
            # 尝试获取深度思考内容 (针对 DeepSeek-R1 等模型)
            reasoning = getattr(response.choices[0].message, 'reasoning_content', None)
            answer = response.choices[0].message.content
            
            # 如果有思考过程，将其整合到回答中（或者你可以选择在 UI 中分开显示）
            full_response = answer
            if reasoning:
                full_response = f"【思考过程】\n{reasoning}\n\n【建议】\n{answer}"
            
            # 更新记忆 (记忆中只保留核心对话，不存思考过程以节省 token)
            self.chat_history.append({"role": "user", "content": user_query})
            self.chat_history.append({"role": "assistant", "content": answer})
            
            return full_response
        except Exception as e:
            return f"AI 接口调用失败: {str(e)}"

    def get_trade_decision(self, symbol, market_data):
        """
        让 AI 直接做出交易决策
        返回格式: ACTION:LONG/SHORT/HOLD, TP_CONS:price, SL_CONS:price, TP_AGGR:price, SL_AGGR:price, LEVERAGE:num, MARGIN_MODE:全仓/逐仓, REASON:text
        """
        system_prompt = (
            "你是一个高频量化交易机器人。请分析市场数据并给出即时交易决策。"
            "你必须提供两套止盈止损方案：保守型 (CONS) 和 激进型 (AGGR)。"
            "你必须严格按照以下格式回复，不要有任何多余文字："
            "ACTION:[LONG/SHORT/HOLD], TP_CONS:[价格/NONE], SL_CONS:[价格/NONE], TP_AGGR:[价格/NONE], SL_AGGR:[价格/NONE], LEVERAGE:[1-20], MARGIN_MODE:[全仓/逐仓], REASON:[简短理由]"
            "\n策略提示：止盈止损必须设置合理。保守型止盈较近，激进型止盈较远。"
        )
        
        user_prompt = f"币种: {symbol}\n数据: {market_data}\n请给出决策。"
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3, # 降低随机性
                stream=False
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"ACTION:HOLD, REASON:AI Error {str(e)}"
