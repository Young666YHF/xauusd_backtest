//+------------------------------------------------------------------+
//| XAUUSD Dual Strategy EA - MQL4 Implementation                    |
//|                                                                  |
//| 策略说明:                                                        |
//|   策略A - 均值回归 (亚盘 06:00-14:00 北京时间)                    |
//|   策略B - 动量突破 (欧美盘 15:00-00:00 北京时间)                  |
//|                                                                  |
//| 2026-03-21 重构:                                                 |
//|   - 完全重写为标准 MQL4 语法 (原代码混用 MQL5)                   |
//|   - 增加时区参数 InpBrokerUTCOffset                              |
//|   - VWAP 改为按日锚定                                            |
//|   - 消除前视偏差                                                 |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, XAUUSD Dual Strategy"
#property link      ""
#property version   "4.00"
#property strict

//+------------------------------------------------------------------+
//| 输入参数 (贝叶斯优化 - Optuna TPE 200次)                          |
//+------------------------------------------------------------------+
// 布林带参数
input int    InpBBPeriod = 13;           // 布林带周期
input double InpBBStd = 1.62;            // 布林带标准差倍数

// 肯特纳通道参数
input int    InpKCPeriod = 25;           // 肯特纳周期
input double InpKCATRMult = 1.30;        // 肯特纳ATR倍数

// ATR参数
input int    InpATRPeriod = 19;          // ATR周期

// RSI参数
input int    InpRSIPeriod = 21;          // RSI周期
input int    InpRSIOversold = 23;        // RSI超卖阈值
input int    InpRSIOverbought = 77;      // RSI超买阈值

// EMA参数 (策略B)
input int    InpEMAFast = 17;            // EMA快线周期
input int    InpEMASlow = 32;            // EMA慢线周期

// 策略A参数
input double InpSLATRMultA = 1.36;       // 策略A止损ATR倍数
input int    InpMaxHoldBarsA = 7;        // 策略A最大持仓K线数

// 策略B参数
input double InpSLATRMultB = 1.69;       // 策略B止损ATR倍数
input double InpTrailingATRMult = 4.54;  // 策略B追踪止损ATR倍数

// 波动率过滤器
input double InpSqueezeThreshold = 0.96; // 波动率挤压阈值

// Module 1 & 2 高级参数
input double InpATRTimeStopBase = 2.71;     // ATR时间止损基础K线数
input double InpATRTimeStopMult = 0.76;     // ATR时间止损倍数
input int    InpVolatilityFilterPeriod = 14; // 波动率过滤周期
input double InpVolatilityFilterMult = 1.79; // 波动率过滤倍数
input int    InpPullbackBars = 3;           // 回踩确认K线数
input double InpEMAMomentumThreshold = 0.00082; // EMA动能阈值

// 【任务1.4 新增】时区参数
input int    InpBrokerUTCOffset = 2;     // 券商服务器UTC时区 (冬令时通常为2, 夏令时为3)
input int    InpAsianStartBJ = 6;        // 亚盘开始小时 (北京时间 UTC+8)
input int    InpAsianEndBJ = 14;         // 亚盘结束小时 (北京时间 UTC+8)
input int    InpEuropeanStartBJ = 15;    // 欧美盘开始小时 (北京时间 UTC+8)
input int    InpEuropeanEndBJ = 0;       // 欧美盘结束小时 (北京时间 UTC+8, 0表示次日0点)

// 【修复1.4 新增】最大点差过滤 (防止结算期点差飙升)
input double InpMaxSpread = 50.0;        // 最大允许点差 (点值, XAUUSD典型点差约30-50)

// 交易设置
input double InpLotSize = 1.0;           // 交易手数
input int    InpSlippage = 30;           // 滑点 (点)
input int    InpMagicNumber = 20260101;  // 魔术数字
input string InpTradeComment = "XAUUSD_DualStrategy";  // 交易注释

// 策略开关
input bool   InpEnableStrategyA = true;  // 启用策略A
input bool   InpEnableStrategyB = true;  // 启用策略B

//+------------------------------------------------------------------+
//| 全局变量                                                          |
//+------------------------------------------------------------------+
// 持仓状态
string g_currentStrategy = "";           // 当前策略 "A" 或 "B"
int g_barsHeld = 0;                      // 持仓K线数
datetime g_entryTime = 0;                // 入场时间
double g_entryPrice = 0;                 // 入场价格
double g_fixedStopLoss = 0;              // 固定止损
double g_highestSinceEntry = 0;          // 入场后最高价
double g_lowestSinceEntry = 1000000;     // 入场后最低价
double g_avgATR = 0;                     // 入场时平均ATR (用于动态时间止损)

// 策略B待确认状态 (Tick级挂单入场)
bool g_pendingConfirmation = false;
int g_pendingDirection = 0;               // 1=多, -1=空
double g_pendingBreakoutHigh = 0;        // 突破K线最高价 (挂单触发价)
double g_pendingBreakoutLow = 0;         // 突破K线最低价 (挂单触发价)
double g_pendingATR = 0;
double g_pendingPrevLow = 0;
double g_pendingPrevHigh = 0;
int g_confirmationBarsLeft = 0;

//+------------------------------------------------------------------+
//| EA初始化                                                          |
//+------------------------------------------------------------------+
int OnInit()
{
   Print("=== XAUUSD Dual Strategy EA v4.0 (MQL4 标准语法) ===");
   Print("【时区设置】券商UTC偏移: ", InpBrokerUTCOffset, " 小时");
   Print("【时区转换】北京时间亚盘: ", InpAsianStartBJ, "-", InpAsianEndBJ);
   Print("【时区转换】北京时间欧美盘: ", InpEuropeanStartBJ, "-次日", InpEuropeanEndBJ);

   LoadPositionState();
   Print("=== 初始化完成 ===");
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| EA反初始化                                                        |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   Print("=== XAUUSD Dual Strategy EA 停止 ===");
}

//+------------------------------------------------------------------+
//| 每个Tick处理 (MQL4 标准语法)                                      |
//+------------------------------------------------------------------+
void OnTick()
{
   // ═══════════════════════════════════════════════════════════════════
   // 【修复1.4】最大点差过滤 (防止结算期点差飙升)
   // ═══════════════════════════════════════════════════════════════════
   double currentSpread = MarketInfo(Symbol(), MODE_SPREAD);
   if(currentSpread > InpMaxSpread)
   {
      // 点差过大，拒绝交易
      return;
   }

   // 检查新K线形成
   static datetime lastBarTime = 0;
   datetime currentBarTime = iTime(NULL, PERIOD_M15, 0);
   bool newBar = (currentBarTime != lastBarTime);

   // 【MQL4 原生方式】获取指标值 - 使用当前K线的前一根已收盘K线 (索引1)
   // 消除前视偏差：所有指标使用索引1，而非索引0
   double bbUpper = iBands(NULL, PERIOD_M15, InpBBPeriod, 0, InpBBStd, PRICE_CLOSE, MODE_UPPER, 1);
   double bbLower = iBands(NULL, PERIOD_M15, InpBBPeriod, 0, InpBBStd, PRICE_CLOSE, MODE_LOWER, 1);
   double bbMiddle = iBands(NULL, PERIOD_M15, InpBBPeriod, 0, InpBBStd, PRICE_CLOSE, MODE_MAIN, 1);

   double atr = iATR(NULL, PERIOD_M15, InpATRPeriod, 1);
   double rsi = iRSI(NULL, PERIOD_M15, InpRSIPeriod, PRICE_CLOSE, 1);

   double emaFast = iMA(NULL, PERIOD_M15, InpEMAFast, 0, MODE_EMA, PRICE_CLOSE, 1);
   double emaSlow = iMA(NULL, PERIOD_M15, InpEMASlow, 0, MODE_EMA, PRICE_CLOSE, 1);

   // 计算肯特纳通道 (使用 EMA + ATR)
   double kcMiddle = iMA(NULL, PERIOD_M15, InpKCPeriod, 0, MODE_EMA, PRICE_CLOSE, 1);
   double kcUpper = kcMiddle + InpKCATRMult * atr;
   double kcLower = kcMiddle - InpKCATRMult * atr;

   // 获取当前价格 (实时价格用于出场检查)
   double close = iClose(NULL, PERIOD_M15, 0);
   double high = iHigh(NULL, PERIOD_M15, 0);
   double low = iLow(NULL, PERIOD_M15, 0);

   // 【任务1.4 修复】时区转换后的交易时段判断
   bool isAsian = IsAsianSession();
   bool isEuropean = IsEuropeanSession();

   // 计算波动率指标
   double squeezeRatio = CalculateSqueezeRatio(bbUpper, bbLower, bbMiddle, kcUpper, kcLower);
   bool isTrend = (squeezeRatio >= InpSqueezeThreshold);
   bool squeezeRelease = CheckSqueezeRelease();

   // 【任务1.5 修复】获取按日锚定的 VWAP
   double vwap = GetDailyVWAP();

   // ═══════════════════════════════════════════════════════════════════
   // 【MQL4 原生持仓遍历】检查是否有当前货币对+魔术数字的持仓
   // ═══════════════════════════════════════════════════════════════════
   int totalOrders = OrdersTotal();
   bool hasPosition = false;
   int positionTicket = -1;
   double positionSize = 0;
   int positionType = -1;
   double positionSL = 0;
   double positionOpenPrice = 0;

   for(int i = totalOrders - 1; i >= 0; i--)
   {
      if(OrderSelect(i, SELECT_BY_POS, MODE_TRADES))
      {
         if(OrderSymbol() == Symbol() && OrderMagicNumber() == InpMagicNumber)
         {
            hasPosition = true;
            positionTicket = OrderTicket();
            positionSize = OrderLots();
            positionType = OrderType();
            positionSL = OrderStopLoss();
            positionOpenPrice = OrderOpenPrice();
            break;
         }
      }
   }

   // ═══════════════════════════════════════════════════════════════════
   // 持仓出场检查 - 每Tick实时执行
   // ═══════════════════════════════════════════════════════════════════
   if(hasPosition)
   {
      // 更新持仓统计
      UpdatePositionStats(high, low);

      // 出场检查
      CheckExitConditions(positionType, positionSL, positionOpenPrice, atr, vwap);

      // 只在新K线时更新持仓K线数
      if(newBar)
      {
         g_barsHeld++;
      }
   }
   else
   {
      // 没有持仓，重置状态
      if(g_currentStrategy != "")
      {
         ResetPositionState();
      }

      // 策略B挂单入场检测
      if(g_pendingConfirmation)
      {
         CheckPendingEntryEveryTick(atr);
      }

      // 入场信号检查 (只在 newBar 时检测新信号)
      if(newBar)
      {
         // ═══════════════════════════════════════════════════════════════════
         // 【修复1.1】挂单幽灵内存泄漏 - 每根新K线递减确认倒计时
         // ═══════════════════════════════════════════════════════════════════
         if(g_pendingConfirmation)
         {
            g_confirmationBarsLeft--;
            Print("【挂单倒计时】剩余K线: ", g_confirmationBarsLeft);

            if(g_confirmationBarsLeft < 0)
            {
               Print("【挂单过期】趋势失效，重置挂单状态");
               ResetPullbackState();
            }
         }

         // 策略A检查 - 均值回归
         if(InpEnableStrategyA && isAsian && !g_pendingConfirmation)
         {
            CheckStrategyAEntry(close, bbUpper, bbLower, rsi, atr, high, low);
         }

         // 策略B检查 - 动量突破
         if(InpEnableStrategyB && isEuropean && !g_pendingConfirmation)
         {
            CheckStrategyBEntry(close, bbUpper, bbLower, bbMiddle,
                               kcUpper, kcLower, emaFast, emaSlow,
                               isTrend, squeezeRelease, atr, high, low);
         }
      }
   }

   if(newBar) lastBarTime = currentBarTime;
}

//+------------------------------------------------------------------+
//| 【任务1.4 修复】检查是否为亚盘时段 (时区转换版)                   |
//| 北京时间 -> 券商服务器时间                                        |
//+------------------------------------------------------------------+
bool IsAsianSession()
{
   // 北京时间 UTC+8, 券商服务器时间 = UTC + InpBrokerUTCOffset
   // 北京时间 = 服务器时间 + (8 - InpBrokerUTCOffset)
   int serverHour = TimeHour(TimeCurrent());
   int beijingHour = serverHour + (8 - InpBrokerUTCOffset);

   // 处理跨日
   if(beijingHour >= 24) beijingHour -= 24;
   if(beijingHour < 0) beijingHour += 24;

   return (beijingHour >= InpAsianStartBJ && beijingHour < InpAsianEndBJ);
}

//+------------------------------------------------------------------+
//| 【任务1.4 修复】检查是否为欧美盘时段 (时区转换版)                 |
//+------------------------------------------------------------------+
bool IsEuropeanSession()
{
   int serverHour = TimeHour(TimeCurrent());
   int beijingHour = serverHour + (8 - InpBrokerUTCOffset);

   if(beijingHour >= 24) beijingHour -= 24;
   if(beijingHour < 0) beijingHour += 24;

   if(InpEuropeanEndBJ == 0)
      return (beijingHour >= InpEuropeanStartBJ);
   else
      return (beijingHour >= InpEuropeanStartBJ || beijingHour < InpEuropeanEndBJ);
}

//+------------------------------------------------------------------+
//| 【修复1.2】动态、无状态的 VWAP 计算 (消除前视偏差)                |
//| 只计算已收盘K线 (i>=1)，排除当前未收盘K线 (i=0)                   |
//+------------------------------------------------------------------+
double GetDailyVWAP()
{
   datetime currentDate = iTime(NULL, PERIOD_D1, 0);
   double dailyTPV = 0, dailyVolume = 0;

   // 【关键修复】从 i=1 (已收盘K线) 开始遍历，排除 i=0 (当前未收盘K线)
   // 这消除了前视偏差：当前K线的TPV会随Tick跳动剧烈漂移
   for(int i = 1; i < 96; i++)
   {
      datetime barTime = iTime(NULL, PERIOD_M15, i);
      if(barTime < currentDate) break;  // 超出当日范围

      double typicalPrice = (iHigh(NULL, PERIOD_M15, i) + iLow(NULL, PERIOD_M15, i) + iClose(NULL, PERIOD_M15, i)) / 3.0;
      double vol = (double)iVolume(NULL, PERIOD_M15, i);
      dailyTPV += typicalPrice * vol;
      dailyVolume += vol;
   }

   return (dailyVolume > 0) ? (dailyTPV / dailyVolume) : iClose(NULL, PERIOD_M15, 1);
}

//+------------------------------------------------------------------+
//| 计算波动率挤压比率                                                |
//+------------------------------------------------------------------+
double CalculateSqueezeRatio(double bbUpper, double bbLower, double bbMiddle,
                              double kcUpper, double kcLower)
{
   if(bbMiddle == 0) return 0;
   double bbWidth = (bbUpper - bbLower) / bbMiddle;
   double kcWidth = (kcUpper - kcLower) / bbMiddle;
   if(kcWidth == 0) return 0;
   return bbWidth / kcWidth;
}

//+------------------------------------------------------------------+
//| 检查波动率挤压释放 (MQL4 原生)                                    |
//+------------------------------------------------------------------+
bool CheckSqueezeRelease()
{
   // 当前 K 线的布林带和肯特纳通道
   double bbUpper0 = iBands(NULL, PERIOD_M15, InpBBPeriod, 0, InpBBStd, PRICE_CLOSE, MODE_UPPER, 1);
   double bbLower0 = iBands(NULL, PERIOD_M15, InpBBPeriod, 0, InpBBStd, PRICE_CLOSE, MODE_LOWER, 1);

   double atr0 = iATR(NULL, PERIOD_M15, InpATRPeriod, 1);
   double kcMiddle0 = iMA(NULL, PERIOD_M15, InpKCPeriod, 0, MODE_EMA, PRICE_CLOSE, 1);
   double kcUpper0 = kcMiddle0 + InpKCATRMult * atr0;
   double kcLower0 = kcMiddle0 - InpKCATRMult * atr0;

   // 前一根 K 线的布林带
   double bbUpper1 = iBands(NULL, PERIOD_M15, InpBBPeriod, 0, InpBBStd, PRICE_CLOSE, MODE_UPPER, 2);
   double bbLower1 = iBands(NULL, PERIOD_M15, InpBBPeriod, 0, InpBBStd, PRICE_CLOSE, MODE_LOWER, 2);

   bool releaseUp = (bbUpper0 > kcUpper0) && (bbUpper1 <= kcUpper0);
   bool releaseDown = (bbLower0 < kcLower0) && (bbLower1 >= kcLower0);

   return releaseUp || releaseDown;
}

//+------------------------------------------------------------------+
//| 检查异常波动                                                      |
//+------------------------------------------------------------------+
bool CheckAbnormalVolatility(double currentHigh, double currentLow, double atr)
{
   double currentRange = currentHigh - currentLow;
   double avgATR = CalculateAverageATR();

   if(avgATR > 0 && currentRange > avgATR * InpVolatilityFilterMult)
      return true;

   return false;
}

//+------------------------------------------------------------------+
//| 计算ATR动态时间止损                                               |
//+------------------------------------------------------------------+
int CalculateDynamicTimeStop(double entryATR, double avgATR)
{
   int baseBars = (int)InpATRTimeStopBase;
   if(avgATR <= 0) return baseBars;

   double atrRatio = entryATR / avgATR;
   int adjustment = (int)((atrRatio - 1.0) * InpATRTimeStopMult * baseBars);
   int dynamicBars = baseBars - adjustment;

   if(dynamicBars < 3) dynamicBars = 3;
   if(dynamicBars > 15) dynamicBars = 15;

   return dynamicBars;
}

//+------------------------------------------------------------------+
//| 计算平均ATR (MQL4 原生)                                           |
//+------------------------------------------------------------------+
double CalculateAverageATR()
{
   double sum = 0;
   int count = 0;
   for(int i = 1; i <= InpVolatilityFilterPeriod; i++)
   {
      double atr = iATR(NULL, PERIOD_M15, InpATRPeriod, i);
      if(atr > 0) { sum += atr; count++; }
   }
   return (count > 0) ? sum / count : 0;
}

//+------------------------------------------------------------------+
//| 策略A入场检查                                                     |
//+------------------------------------------------------------------+
void CheckStrategyAEntry(double close, double bbUpper, double bbLower,
                         double rsi, double atr, double high, double low)
{
   if(CheckAbnormalVolatility(high, low, atr))
   {
      Print("策略A: 异常波动，跳过信号");
      return;
   }

   // 做多条件
   if(close <= bbLower && rsi < InpRSIOversold)
   {
      double slAnchor = MathMin(close, bbLower);
      double sl = slAnchor - InpSLATRMultA * atr;
      double vwap = GetDailyVWAP();

      g_avgATR = CalculateAverageATR();
      Print("策略A做多: 止损锚定=", slAnchor, " 止损=", sl);

      // 【MQL4 原生下单】
      if(OpenPositionMQL4(OP_BUY, sl, vwap, "A"))
      {
         g_currentStrategy = "A";
         g_entryPrice = Ask;
         g_fixedStopLoss = sl;
         g_barsHeld = 0;
         g_highestSinceEntry = Ask;
         g_lowestSinceEntry = Ask;
         SavePositionState();
      }
      return;
   }

   // 做空条件
   if(close >= bbUpper && rsi > InpRSIOverbought)
   {
      double slAnchor = MathMax(close, bbUpper);
      double sl = slAnchor + InpSLATRMultA * atr;
      double vwap = GetDailyVWAP();

      g_avgATR = CalculateAverageATR();
      Print("策略A做空: 止损锚定=", slAnchor, " 止损=", sl);

      if(OpenPositionMQL4(OP_SELL, sl, vwap, "A"))
      {
         g_currentStrategy = "A";
         g_entryPrice = Bid;
         g_fixedStopLoss = sl;
         g_barsHeld = 0;
         g_highestSinceEntry = Bid;
         g_lowestSinceEntry = Bid;
         SavePositionState();
      }
   }
}

//+------------------------------------------------------------------+
//| 策略B入场检查 (设置待确认状态)                                    |
//+------------------------------------------------------------------+
void CheckStrategyBEntry(double close, double bbUpper, double bbLower, double bbMiddle,
                         double kcUpper, double kcLower,
                         double emaFast, double emaSlow,
                         bool isTrend, bool squeezeRelease, double atr, double high, double low)
{
   if(CheckAbnormalVolatility(high, low, atr))
   {
      Print("策略B: 异常波动，跳过信号");
      return;
   }

   if(!isTrend && !squeezeRelease) return;

   // 做多条件
   if(close > bbUpper && bbUpper > kcUpper && emaFast > emaSlow)
   {
      double prevLow = iLow(NULL, PERIOD_M15, 1);
      double prevHigh = iHigh(NULL, PERIOD_M15, 1);

      SetPullbackState(1, high, low, atr, prevLow, prevHigh);
      Print("策略B: 做多信号待确认, 挂单价=", high, " 等待Ask突破...");
      return;
   }

   // 做空条件
   if(close < bbLower && bbLower < kcLower && emaFast < emaSlow)
   {
      double prevLow = iLow(NULL, PERIOD_M15, 1);
      double prevHigh = iHigh(NULL, PERIOD_M15, 1);

      SetPullbackState(-1, high, low, atr, prevLow, prevHigh);
      Print("策略B: 做空信号待确认, 挂单价=", low, " 等待Bid跌破...");
   }
}

//+------------------------------------------------------------------+
//| 设置待确认状态                                                    |
//+------------------------------------------------------------------+
void SetPullbackState(int direction, double breakoutHigh, double breakoutLow,
                      double atr, double prevLow, double prevHigh)
{
   g_pendingConfirmation = true;
   g_confirmationBarsLeft = InpPullbackBars;
   g_pendingDirection = direction;
   g_pendingBreakoutHigh = breakoutHigh;
   g_pendingBreakoutLow = breakoutLow;
   g_pendingATR = atr;
   g_pendingPrevLow = prevLow;
   g_pendingPrevHigh = prevHigh;
}

//+------------------------------------------------------------------+
//| 重置待确认状态                                                    |
//+------------------------------------------------------------------+
void ResetPullbackState()
{
   g_pendingConfirmation = false;
   g_confirmationBarsLeft = 0;
   g_pendingDirection = 0;
   g_pendingBreakoutHigh = 0;
   g_pendingBreakoutLow = 0;
   g_pendingATR = 0;
   g_pendingPrevLow = 0;
   g_pendingPrevHigh = 0;
}

//+------------------------------------------------------------------+
//| 每Tick检测策略B挂单入场                                           |
//+------------------------------------------------------------------+
void CheckPendingEntryEveryTick(double currentATR)
{
   if(!g_pendingConfirmation) return;

   // 多头挂单: Ask >= 突破高点时入场
   if(g_pendingDirection == 1)
   {
      if(Ask >= g_pendingBreakoutHigh)
      {
         Print("【Tick级入场】多头触发: Ask=", Ask, " >= BreakoutHigh=", g_pendingBreakoutHigh);

         double sl = MathMax(g_pendingBreakoutHigh - InpSLATRMultB * g_pendingATR, g_pendingPrevLow);
         g_avgATR = CalculateAverageATR();

         if(OpenPositionMQL4(OP_BUY, sl, 0, "B"))
         {
            g_currentStrategy = "B";
            g_entryPrice = Ask;
            g_fixedStopLoss = sl;
            g_barsHeld = 0;
            g_highestSinceEntry = Ask;
            g_lowestSinceEntry = Ask;
            SavePositionState();
         }
         ResetPullbackState();
         return;
      }
   }
   // 空头挂单: Bid <= 突破低点时入场
   else if(g_pendingDirection == -1)
   {
      if(Bid <= g_pendingBreakoutLow)
      {
         Print("【Tick级入场】空头触发: Bid=", Bid, " <= BreakoutLow=", g_pendingBreakoutLow);

         double sl = MathMin(g_pendingBreakoutLow + InpSLATRMultB * g_pendingATR, g_pendingPrevHigh);
         g_avgATR = CalculateAverageATR();

         if(OpenPositionMQL4(OP_SELL, sl, 0, "B"))
         {
            g_currentStrategy = "B";
            g_entryPrice = Bid;
            g_fixedStopLoss = sl;
            g_barsHeld = 0;
            g_highestSinceEntry = Bid;
            g_lowestSinceEntry = Bid;
            SavePositionState();
         }
         ResetPullbackState();
      }
   }
}

//+------------------------------------------------------------------+
//| 【终极修复】MQL4 原生下单函数                                     |
//| 使用标准 MT4 OrderSend 语法                                       |
//| 实盘容错：Error 138/146 重试机制                                  |
//| 【修复1.3】StopLevel 防御机制 - 拒绝止损过近的交易                |
//+------------------------------------------------------------------+
bool OpenPositionMQL4(int orderType, double sl, double tp, string strategy)
{
   double price;
   color arrowColor;

   if(orderType == OP_BUY)
   {
      price = Ask;
      arrowColor = clrBlue;
   }
   else if(orderType == OP_SELL)
   {
      price = Bid;
      arrowColor = clrRed;
   }
   else
   {
      return false;
   }

   // 规范化价格精度
   int digits = (int)MarketInfo(Symbol(), MODE_DIGITS);

   // 【修复1.3】StopLevel 防御机制 - 止损过近必须放弃交易
   // 原代码会自动拓宽止损，这是极端危险的！
   double stopLevel = MarketInfo(Symbol(), MODE_STOPLEVEL) * Point;

   if(orderType == OP_BUY)
   {
      // 多头止损必须低于入场价至少 stopLevel 距离
      if(sl > 0 && price - sl < stopLevel)
      {
         // 【关键修复】放弃该笔交易，绝不擅自拓宽止损
         Print("【风控拒绝】多头止损过近: 入场价=", price, " 止损=", sl,
               " 距离=", (price - sl) / Point, "点 < StopLevel=", stopLevel / Point, "点");
         Print("【风控拒绝】放弃交易，保护风险敞口");
         return false;
      }
   }
   else // OP_SELL
   {
      // 空头止损必须高于入场价至少 stopLevel 距离
      if(sl > 0 && sl - price < stopLevel)
      {
         // 【关键修复】放弃该笔交易，绝不擅自拓宽止损
         Print("【风控拒绝】空头止损过近: 入场价=", price, " 止损=", sl,
               " 距离=", (sl - price) / Point, "点 < StopLevel=", stopLevel / Point, "点");
         Print("【风控拒绝】放弃交易，保护风险敞口");
         return false;
      }
   }

   sl = NormalizeDouble(sl, digits);
   if(tp > 0) tp = NormalizeDouble(tp, digits);

   // 【实盘容错】最多重试 3 次
   int maxRetries = 3;
   int ticket = -1;

   for(int retry = 0; retry < maxRetries; retry++)
   {
      // 【MQL4 原生 OrderSend】
      // 语法: OrderSend(Symbol(), Type, Lots, Price, Slippage, SL, TP, Comment, Magic, Expiration, Color)
      ticket = OrderSend(
         Symbol(),                // 货币对
         orderType,               // 订单类型 (OP_BUY 或 OP_SELL)
         InpLotSize,              // 手数
         price,                   // 入场价格
         InpSlippage,             // 滑点
         sl,                      // 止损
         tp,                      // 止盈
         InpTradeComment + "_" + strategy,  // 注释
         InpMagicNumber,          // 魔术数字
         0,                       // 过期时间 (0 = 无)
         arrowColor               // 箭头颜色
      );

      if(ticket >= 0)
      {
         // 下单成功
         break;
      }

      int error = GetLastError();

      // Error 138 (重新报价) 或 Error 146 (服务器忙) 时重试
      if(error == 138 || error == 146)
      {
         Print("【MQL4下单重试】错误码: ", error, " 描述: ", ErrorDescription(error),
               " 重试次数: ", retry + 1, "/", maxRetries);
         Sleep(100);
         RefreshRates();

         // 更新价格 (重新报价后价格可能变化)
         if(orderType == OP_BUY)
            price = Ask;
         else
            price = Bid;
      }
      else
      {
         // 其他错误，不重试
         Print("【MQL4下单失败】错误码: ", error, " 描述: ", ErrorDescription(error));
         return false;
      }
   }

   if(ticket < 0)
   {
      int error = GetLastError();
      Print("【MQL4下单最终失败】错误码: ", error, " 描述: ", ErrorDescription(error));
      return false;
   }

   Print("【MQL4下单成功】Ticket: ", ticket, " 类型: ", (orderType == OP_BUY ? "BUY" : "SELL"),
         " 价格: ", price, " 止损: ", sl, " 止盈: ", tp);

   return true;
}

//+------------------------------------------------------------------+
//| 【修复1.5】更新持仓统计 - Tick级极值捕获                          |
//| 多头比较Ask，空头比较Bid，捕获瞬间极值                            |
//+------------------------------------------------------------------+
void UpdatePositionStats(double high, double low)
{
   // 遍历持仓获取方向
   int totalOrders = OrdersTotal();
   int positionType = -1;

   for(int i = totalOrders - 1; i >= 0; i--)
   {
      if(OrderSelect(i, SELECT_BY_POS, MODE_TRADES))
      {
         if(OrderSymbol() == Symbol() && OrderMagicNumber() == InpMagicNumber)
         {
            positionType = OrderType();
            break;
         }
      }
   }

   // 【关键修复】Tick级极值捕获
   // 多头：比较Ask（最高买入价），空头：比较Bid（最低卖出价）
   if(positionType == OP_BUY)
   {
      // 多头追踪最高价，应该用Ask
      g_highestSinceEntry = MathMax(g_highestSinceEntry, Ask);
      g_lowestSinceEntry = MathMin(g_lowestSinceEntry, Bid);
   }
   else if(positionType == OP_SELL)
   {
      // 空头追踪最低价，应该用Bid
      g_highestSinceEntry = MathMax(g_highestSinceEntry, Ask);
      g_lowestSinceEntry = MathMin(g_lowestSinceEntry, Bid);
   }
   else
   {
      // 无持仓时使用K线高低价
      g_highestSinceEntry = MathMax(g_highestSinceEntry, high);
      g_lowestSinceEntry = MathMin(g_lowestSinceEntry, low);
   }
}

//+------------------------------------------------------------------+
//| 出场条件检查 (每Tick执行)                                         |
//+------------------------------------------------------------------+
void CheckExitConditions(int positionType, double positionSL, double positionOpenPrice,
                         double currentATR, double vwap)
{
   bool shouldClose = false;
   string reason = "";

   // 策略A出场
   if(g_currentStrategy == "A")
   {
      if(positionType == OP_BUY)
      {
         // 止损检查
         if(Bid <= positionSL)
         {
            shouldClose = true;
            reason = "止损";
         }
         // VWAP止盈
         else if(Ask >= vwap)
         {
            shouldClose = true;
            reason = "VWAP止盈";
         }
      }
      else if(positionType == OP_SELL)
      {
         if(Ask >= positionSL)
         {
            shouldClose = true;
            reason = "止损";
         }
         else if(Bid <= vwap)
         {
            shouldClose = true;
            reason = "VWAP止盈";
         }
      }

      // ATR自适应动态时间止损
      if(!shouldClose)
      {
         double entryATR = iATR(NULL, PERIOD_M15, InpATRPeriod, g_barsHeld + 1);
         int dynamicMaxBars = CalculateDynamicTimeStop(entryATR, g_avgATR);
         if(g_barsHeld >= dynamicMaxBars)
         {
            shouldClose = true;
            reason = "ATR动态时间止损";
         }
      }
   }

   // 策略B出场
   if(g_currentStrategy == "B")
   {
      if(positionType == OP_BUY)
      {
         // 初始止损
         if(Bid <= positionSL)
         {
            shouldClose = true;
            reason = "初始止损";
         }
         // 追踪止损
         else
         {
            double trailingStop = g_highestSinceEntry - InpTrailingATRMult * currentATR;
            if(Bid <= trailingStop && g_highestSinceEntry > positionOpenPrice)
            {
               shouldClose = true;
               reason = "追踪止损";
            }
         }
      }
      else if(positionType == OP_SELL)
      {
         if(Ask >= positionSL)
         {
            shouldClose = true;
            reason = "初始止损";
         }
         else
         {
            double trailingStop = g_lowestSinceEntry + InpTrailingATRMult * currentATR;
            if(Ask >= trailingStop && g_lowestSinceEntry < positionOpenPrice)
            {
               shouldClose = true;
               reason = "追踪止损";
            }
         }
      }
   }

   // 执行平仓
   if(shouldClose)
   {
      ClosePositionMQL4(reason);
   }
}

//+------------------------------------------------------------------+
//| 【终极修复】MQL4 原生平仓函数                                     |
//| 使用 OrderClose() 替代反向 OrderSend，防止锁仓                    |
//| 实盘容错：Error 138/146 重试机制                                  |
//+------------------------------------------------------------------+
bool ClosePositionMQL4(string reason)
{
   int totalOrders = OrdersTotal();

   for(int i = totalOrders - 1; i >= 0; i--)
   {
      if(OrderSelect(i, SELECT_BY_POS, MODE_TRADES))
      {
         if(OrderSymbol() == Symbol() && OrderMagicNumber() == InpMagicNumber)
         {
            int orderType = OrderType();
            double lots = OrderLots();
            int ticket = OrderTicket();

            // 非持仓订单跳过
            if(orderType != OP_BUY && orderType != OP_SELL)
               continue;

            double closePrice;
            color arrowColor;

            if(orderType == OP_BUY)
            {
               closePrice = Bid;
               arrowColor = clrRed;
            }
            else // OP_SELL
            {
               closePrice = Ask;
               arrowColor = clrBlue;
            }

            // 规范化平仓价格
            int digits = (int)MarketInfo(Symbol(), MODE_DIGITS);
            closePrice = NormalizeDouble(closePrice, digits);

            // 【实盘容错】最多重试 3 次
            int maxRetries = 3;
            bool closeResult = false;

            for(int retry = 0; retry < maxRetries; retry++)
            {
               // 【MQL4 原生 OrderClose】
               // 语法: bool OrderClose(ticket, lots, price, slippage, arrowColor)
               closeResult = OrderClose(ticket, lots, closePrice, InpSlippage, arrowColor);

               if(closeResult == true)
               {
                  // 平仓成功
                  break;
               }

               int error = GetLastError();

               // Error 138 (重新报价) 或 Error 146 (服务器忙) 时重试
               if(error == 138 || error == 146)
               {
                  Print("【MQL4平仓重试】错误码: ", error, " 描述: ", ErrorDescription(error),
                        " 重试次数: ", retry + 1, "/", maxRetries);
                  Sleep(100);
                  RefreshRates();

                  // 更新价格 (重新报价后价格可能变化)
                  if(orderType == OP_BUY)
                     closePrice = NormalizeDouble(Bid, digits);
                  else
                     closePrice = NormalizeDouble(Ask, digits);
               }
               else
               {
                  // 其他错误，不重试
                  Print("【MQL4平仓失败】错误码: ", error, " 描述: ", ErrorDescription(error));
                  return false;
               }
            }

            if(closeResult == false)
            {
               int error = GetLastError();
               Print("【MQL4平仓最终失败】错误码: ", error, " 描述: ", ErrorDescription(error));
               return false;
            }

            Print("【MQL4平仓成功】Ticket: ", ticket, " 原因: ", reason, " 价格: ", closePrice, " 手数: ", lots);
            ResetPositionState();
            return true;
         }
      }
   }

   return false;
}

//+------------------------------------------------------------------+
//| 重置持仓状态                                                      |
//+------------------------------------------------------------------+
void ResetPositionState()
{
   g_currentStrategy = "";
   g_barsHeld = 0;
   g_entryTime = 0;
   g_entryPrice = 0;
   g_fixedStopLoss = 0;
   g_highestSinceEntry = 0;
   g_lowestSinceEntry = 1000000;
   SavePositionState();
}

//+------------------------------------------------------------------+
//| 保存持仓状态到文件                                                |
//+------------------------------------------------------------------+
void SavePositionState()
{
   string filename = "XAUUSD_DualStrategy_State.bin";
   int handle = FileOpen(filename, FILE_WRITE|FILE_BIN|FILE_COMMON);

   if(handle != INVALID_HANDLE)
   {
      FileWriteString(handle, g_currentStrategy, 10);
      FileWriteInteger(handle, g_barsHeld);
      FileWriteLong(handle, g_entryTime);
      FileWriteDouble(handle, g_entryPrice);
      FileWriteDouble(handle, g_fixedStopLoss);
      FileWriteDouble(handle, g_highestSinceEntry);
      FileWriteDouble(handle, g_lowestSinceEntry);
      FileClose(handle);
   }
}

//+------------------------------------------------------------------+
//| 从文件加载持仓状态                                                |
//+------------------------------------------------------------------+
void LoadPositionState()
{
   string filename = "XAUUSD_DualStrategy_State.bin";
   int handle = FileOpen(filename, FILE_READ|FILE_BIN|FILE_COMMON);

   if(handle != INVALID_HANDLE)
   {
      if(FileSize(handle) > 0)
      {
         g_currentStrategy = FileReadString(handle, 10);
         g_barsHeld = FileReadInteger(handle);
         g_entryTime = FileReadLong(handle);
         g_entryPrice = FileReadDouble(handle);
         g_fixedStopLoss = FileReadDouble(handle);
         g_highestSinceEntry = FileReadDouble(handle);
         g_lowestSinceEntry = FileReadDouble(handle);

         Print("加载持仓状态: 策略", g_currentStrategy);
      }
      FileClose(handle);
   }
}

//+------------------------------------------------------------------+
//| 错误描述 (MQL4 标准)                                              |
//+------------------------------------------------------------------+
string ErrorDescription(int error)
{
   switch(error)
   {
      case 0:   return "无错误";
      case 1:   return "无错误，但结果未知";
      case 2:   return "一般错误";
      case 3:   return "错误的参数";
      case 4:   return "交易服务器繁忙";
      case 5:   return "旧版本的客户端终端";
      case 6:   return "没有连接到交易服务器";
      case 7:   return "权限不足";
      case 8:   return "请求过于频繁";
      case 9:   return "无效操作";
      case 64:  return "账户被禁止";
      case 65:  return "无效账户";
      case 128: return "交易超时";
      case 129: return "无效价格";
      case 130: return "无效止损";
      case 131: return "无效手数";
      case 132: return "市场关闭";
      case 133: return "交易被禁止";
      case 134: return "资金不足";
      case 135: return "价格改变";
      case 136: return "价格改变";
      case 137: return "经纪商繁忙";
      case 138: return "重新报价";
      case 139: return "订单被锁定";
      case 140: return "只允许做多";
      case 141: return "请求过多";
      case 145: return "修改被拒绝";
      case 146: return "交易子系统繁忙";
      case 147: return "使用过期日期被禁止";
      case 148: return "订单数量超出限制";
      case 149: return "对冲被禁止";
      case 150: return "禁止按FIFO平仓";
      default:  return "未知错误 " + IntegerToString(error);
   }
}
//+------------------------------------------------------------------+
