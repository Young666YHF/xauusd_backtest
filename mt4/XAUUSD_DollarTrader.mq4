//+------------------------------------------------------------------+
//| XAUUSD Dollar Trader EA - MQL4                                   |
//|                                                                  |
//| Dollar Trader 策略 - 三线SMA趋势跟踪                               |
//| 单一文件版本，与Python回测逻辑完全一致                             |
//|                                                                  |
//| 核心逻辑:                                                         |
//|   - 多头开仓: C > SMA_20 > SMA_50 > SMA_200                       |
//|   - 空头开仓: C < SMA_20 < SMA_50 < SMA_200                       |
//|   - 多头平仓: SMA_20 < SMA_50 (死叉)                              |
//|   - 空头平仓: SMA_20 > SMA_50 (金叉)                              |
//|                                                                  |
//| 【关键】使用[1]索引获取上一根K线数据判断，当前K线开盘执行            |
//| 对应Python: prev_bar = df.iloc[current_idx - 1]                   |
//|             entry_price = current_bar['Open']                     |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, Dollar Trader Strategy"
#property link      ""
#property version   "1.00"
#property strict

//+------------------------------------------------------------------+
//| 输入参数                                                          |
//+------------------------------------------------------------------+
input int    InpSMAShort = 20;         // 短期SMA周期
input int    InpSMAMedium = 50;        // 中期SMA周期
input int    InpSMALong = 200;         // 长期SMA周期
input double InpPositionSize = 1.0;    // 固定手数
input int    InpMagicNumber = 202501;  // 魔术号码
input int    InpMaxSpread = 50;        // 最大允许点差(点)

//+------------------------------------------------------------------+
//| 全局变量                                                          |
//+------------------------------------------------------------------+
static datetime g_lastBarTime = 0;     // 上一根K线时间

//+------------------------------------------------------------------+
//| 将周期转换为字符串                                                |
//+------------------------------------------------------------------+
string PeriodToString()
{
   int period = Period();
   switch(period)
   {
      case 1:  return "M1";
      case 5:  return "M5";
      case 15: return "M15";
      case 30: return "M30";
      case 60: return "H1";
      case 240: return "H4";
      case 1440: return "D1";
      default: return "M" + IntegerToString(period);
   }
}

//+------------------------------------------------------------------+
//| EA初始化                                                          |
//+------------------------------------------------------------------+
int OnInit()
{
   Print("=== XAUUSD Dollar Trader EA v1.0 ===");
   Print("策略: 三线SMA趋势跟踪 (", InpSMAShort, "/", InpSMAMedium, "/", InpSMALong, ")");
   Print("周期: ", PeriodToString());
   Print("手数: ", DoubleToString(InpPositionSize, 2));

   // 检查周期
   int tf = Period();
   if(tf != 30 && tf != 60)  // M30=30, H1=60
   {
      Alert("Warning: Dollar Trader策略推荐使用M30或H1周期");
   }

   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| EA反初始化                                                        |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   Print("=== Dollar Trader EA 停止 ===");
}

//+------------------------------------------------------------------+
//| 检查是否为新K线                                                   |
//+------------------------------------------------------------------+
bool IsNewBar()
{
   datetime currentBarTime = Time[0];
   if(currentBarTime != g_lastBarTime)
   {
      g_lastBarTime = currentBarTime;
      return true;
   }
   return false;
}

//+------------------------------------------------------------------+
//| 获取持仓方向                                                      |
//+------------------------------------------------------------------+
int GetPositionDirection()
{
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if(OrderSelect(i, SELECT_BY_POS, MODE_TRADES))
      {
         if(OrderSymbol() == Symbol() && OrderMagicNumber() == InpMagicNumber)
         {
            int orderType = OrderType();
            if(orderType == OP_BUY) return 1;   // 多头
            if(orderType == OP_SELL) return -1; // 空头
         }
      }
   }
   return 0; // 无持仓
}

//+------------------------------------------------------------------+
//| 开仓函数                                                          |
//+------------------------------------------------------------------+
bool OpenPosition(int orderType)
{
   // 【实盘逻辑】使用当前市场报价执行
   // BUY 用 Ask, SELL 用 Bid
   // 记录开盘价用于日志对比Python回测
   double price = (orderType == OP_BUY) ? Ask : Bid;
   double sl = 0;
   double tp = 0;

   string comment = "DollarTrader";
   color clr = (orderType == OP_BUY) ? clrGreen : clrRed;

   int ticket = OrderSend(Symbol(), orderType, InpPositionSize, price, 10, sl, tp, comment, InpMagicNumber, 0, clr);

   if(ticket < 0)
   {
      Print("开仓失败: ", GetLastError(), " 类型=", orderType == OP_BUY ? "BUY" : "SELL", " 价格=", price);
      return false;
   }

   Print("开仓成功: Ticket=", ticket, " 类型=", orderType == OP_BUY ? "BUY" : "SELL", " 价格=", price, " Open=", Open[0]);
   return true;
}

//+------------------------------------------------------------------+
//| 平仓函数                                                          |
//+------------------------------------------------------------------+
bool ClosePosition(string reason)
{
   bool result = true;
   bool anyClosed = false;

   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if(OrderSelect(i, SELECT_BY_POS, MODE_TRADES))
      {
         if(OrderSymbol() == Symbol() && OrderMagicNumber() == InpMagicNumber)
         {
            int orderType = OrderType();
            int ticket = OrderTicket();
            double lots = OrderLots();

            // 【实盘逻辑】使用当前市场报价平仓
            // BUY 用 Bid 平仓, SELL 用 Ask 平仓
            double closePrice = (orderType == OP_BUY) ? Bid : Ask;

            bool closed = false;
            if(orderType == OP_BUY)
               closed = OrderClose(ticket, lots, closePrice, 10, clrRed);
            else if(orderType == OP_SELL)
               closed = OrderClose(ticket, lots, closePrice, 10, clrRed);

            if(closed)
            {
               Print("平仓成功: Ticket=", ticket, " 原因=", reason, " 价格=", closePrice, " Open=", Open[0]);
               anyClosed = true;
            }
            else
            {
               Print("平仓失败: Ticket=", ticket, " 错误=", GetLastError(), " 价格=", closePrice);
               result = false;
            }
         }
      }
   }

   return result || anyClosed;
}

//+------------------------------------------------------------------+
//| 每个Tick处理                                                      |
//+------------------------------------------------------------------+
void OnTick()
{
   // 点差过滤
   double currentSpread = MarketInfo(Symbol(), MODE_SPREAD);
   if(currentSpread > InpMaxSpread) return;

   // 【关键】只在新的K线开盘时执行一次，与Python回测逻辑一致
   if(!IsNewBar()) return;

   // 【关键】使用上一根K线(已收盘)的数据判断信号
   // 对应Python: prev_bar = df.iloc[current_idx - 1]
   double prevClose = Close[1];
   double prevSMA_S = iMA(NULL, 0, InpSMAShort, 0, MODE_SMA, PRICE_CLOSE, 1);
   double prevSMA_M = iMA(NULL, 0, InpSMAMedium, 0, MODE_SMA, PRICE_CLOSE, 1);
   double prevSMA_L = iMA(NULL, 0, InpSMALong, 0, MODE_SMA, PRICE_CLOSE, 1);

   // 前两根K线的SMA值(用于判断交叉)
   double prev2SMA_S = iMA(NULL, 0, InpSMAShort, 0, MODE_SMA, PRICE_CLOSE, 2);
   double prev2SMA_M = iMA(NULL, 0, InpSMAMedium, 0, MODE_SMA, PRICE_CLOSE, 2);

   // 检查指标有效性
   if(prevSMA_S == 0 || prevSMA_M == 0 || prevSMA_L == 0) return;

   // === 趋势判断 (基于上一根K线) ===
   // 多头排列: C > SMA_S > SMA_M > SMA_L
   bool isBullish = (prevClose > prevSMA_S) && (prevSMA_S > prevSMA_M) && (prevSMA_M > prevSMA_L);

   // 空头排列: C < SMA_S < SMA_M < SMA_L
   bool isBearish = (prevClose < prevSMA_S) && (prevSMA_S < prevSMA_M) && (prevSMA_M < prevSMA_L);

   // === 交叉判断 (用于出场) ===
   // 短期下穿中期(死叉) - 多头平仓信号
   bool smaBearishCross = (prev2SMA_S >= prev2SMA_M) && (prevSMA_S < prevSMA_M);

   // 短期上穿中期(金叉) - 空头平仓信号
   bool smaBullishCross = (prev2SMA_S <= prev2SMA_M) && (prevSMA_S > prevSMA_M);

   // 获取当前持仓方向
   int position = GetPositionDirection();

   // === 出场逻辑 ===
   if(position == 1 && smaBearishCross)  // 持有多头，死叉平仓
   {
      ClosePosition("SMA死叉平仓");
      position = 0;

      // 平仓后如果趋势转空，立即开空仓
      if(isBearish)
      {
         OpenPosition(OP_SELL);
         return;
      }
   }
   else if(position == -1 && smaBullishCross)  // 持有空头，金叉平仓
   {
      ClosePosition("SMA金叉平仓");
      position = 0;

      // 平仓后如果趋势转多，立即开多仓
      if(isBullish)
      {
         OpenPosition(OP_BUY);
         return;
      }
   }

   // === 入场逻辑 ===
   if(position == 0)  // 无持仓
   {
      if(isBullish)
      {
         OpenPosition(OP_BUY);
         return;
      }
      else if(isBearish)
      {
         OpenPosition(OP_SELL);
         return;
      }
   }
   else if(position == 1 && isBearish)  // 持有多头，趋势转空，反向做空
   {
      ClosePosition("多转空反向");
      OpenPosition(OP_SELL);
      return;
   }
   else if(position == -1 && isBullish)  // 持有空头，趋势转多，反向做多
   {
      ClosePosition("空转多反向");
      OpenPosition(OP_BUY);
      return;
   }
}
//+------------------------------------------------------------------+
