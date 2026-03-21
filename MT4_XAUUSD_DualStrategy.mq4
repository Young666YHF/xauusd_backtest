//+------------------------------------------------------------------+
//| XAUUSD Dual Strategy EA - MQL4 Implementation                    |
//|                                                                  |
//| 策略说明:                                                        |
//|   策略A - 均值回归 (亚盘 06:00-14:00)                             |
//|   策略B - 动量突破 (欧美盘 15:00-00:00)                           |
//|                                                                  |
//| 与Python Tick引擎微观执行对齐 - 2026-03-21 重构                   |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, XAUUSD Dual Strategy"
#property link      ""
#property version   "3.00"
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

// 交易时段设置 (北京时间 UTC+8)
input int    InpAsianStart = 6;          // 亚盘开始小时
input int    InpAsianEnd = 14;           // 亚盘结束小时
input int    InpEuropeanStart = 15;      // 欧美盘开始小时
input int    InpEuropeanEnd = 0;         // 欧美盘结束小时 (次日0点)

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
int g_bbHandle = INVALID_HANDLE;         // 布林带指标句柄
int g_atrHandle = INVALID_HANDLE;        // ATR指标句柄
int g_rsiHandle = INVALID_HANDLE;        // RSI指标句柄
int g_emaFastHandle = INVALID_HANDLE;    // EMA快线句柄
int g_emaSlowHandle = INVALID_HANDLE;    // EMA慢线句柄

// 持仓状态
string g_currentStrategy = "";           // 当前策略 "A" 或 "B"
int g_barsHeld = 0;                      // 持仓K线数
datetime g_entryTime = 0;                // 入场时间
double g_entryPrice = 0;                 // 入场价格
double g_fixedStopLoss = 0;              // 固定止损
double g_highestSinceEntry = 0;          // 入场后最高价
double g_lowestSinceEntry = DBL_MAX;     // 入场后最低价
double g_avgATR = 0;                     // 入场时平均ATR (用于动态时间止损)

// VWAP 缓存 (优化性能)
double g_cachedVWAP = 0;
datetime g_vwapLastUpdate = 0;

// 策略B待确认状态 (Tick级挂单入场)
bool g_pendingConfirmation = false;
int g_pendingDirection = 0;               // 1=多, -1=空
double g_pendingBreakoutHigh = 0;        // 突破K线最高价 (挂单触发价)
double g_pendingBreakoutLow = 0;         // 突破K线最低价 (挂单触发价)
double g_pendingBBUpper = 0;
double g_pendingBBLower = 0;
double g_pendingATR = 0;
double g_pendingPrevLow = 0;
double g_pendingPrevHigh = 0;
double g_pendingEMADiff = 0;
int g_confirmationBarsLeft = 0;

//+------------------------------------------------------------------+
//| EA初始化                                                          |
//+------------------------------------------------------------------+
int OnInit()
{
   Print("=== XAUUSD Dual Strategy EA v3.0 初始化 ===");
   Print("【微观执行对齐】出场检查 + 策略B入场 = 每Tick执行");

   if(!InitializeIndicators())
   {
      Print("指标初始化失败!");
      return(INIT_FAILED);
   }

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
   ReleaseIndicators();
}

//+------------------------------------------------------------------+
//| 初始化指标                                                        |
//+------------------------------------------------------------------+
bool InitializeIndicators()
{
   g_bbHandle = iBands(NULL, PERIOD_M15, InpBBPeriod, 0, InpBBStd, PRICE_CLOSE);
   if(g_bbHandle == INVALID_HANDLE) { Print("布林带创建失败"); return false; }

   g_atrHandle = iATR(NULL, PERIOD_M15, InpATRPeriod);
   if(g_atrHandle == INVALID_HANDLE) { Print("ATR创建失败"); return false; }

   g_rsiHandle = iRSI(NULL, PERIOD_M15, InpRSIPeriod, PRICE_CLOSE);
   if(g_rsiHandle == INVALID_HANDLE) { Print("RSI创建失败"); return false; }

   g_emaFastHandle = iMA(NULL, PERIOD_M15, InpEMAFast, 0, MODE_EMA, PRICE_CLOSE);
   if(g_emaFastHandle == INVALID_HANDLE) { Print("EMA快线创建失败"); return false; }

   g_emaSlowHandle = iMA(NULL, PERIOD_M15, InpEMASlow, 0, MODE_EMA, PRICE_CLOSE);
   if(g_emaSlowHandle == INVALID_HANDLE) { Print("EMA慢线创建失败"); return false; }

   Print("所有指标初始化成功");
   return true;
}

//+------------------------------------------------------------------+
//| 释放指标                                                          |
//+------------------------------------------------------------------+
void ReleaseIndicators()
{
   if(g_bbHandle != INVALID_HANDLE) IndicatorRelease(g_bbHandle);
   if(g_atrHandle != INVALID_HANDLE) IndicatorRelease(g_atrHandle);
   if(g_rsiHandle != INVALID_HANDLE) IndicatorRelease(g_rsiHandle);
   if(g_emaFastHandle != INVALID_HANDLE) IndicatorRelease(g_emaFastHandle);
   if(g_emaSlowHandle != INVALID_HANDLE) IndicatorRelease(g_emaSlowHandle);
}

//+------------------------------------------------------------------+
//| 每个Tick处理 (微观执行对齐)                                       |
//+------------------------------------------------------------------+
void OnTick()
{
   // 检查新K线形成
   static datetime lastBarTime = 0;
   datetime currentBarTime = iTime(NULL, PERIOD_M15, 0);
   bool newBar = (currentBarTime != lastBarTime);

   // 获取指标值
   double bbUpper[], bbMiddle[], bbLower[], atr[], rsi[], emaFast[], emaSlow[];
   if(CopyBuffer(g_bbHandle, UPPER_BAND, 0, 1, bbUpper) < 1) return;
   if(CopyBuffer(g_bbHandle, BASE_LINE, 0, 1, bbMiddle) < 1) return;
   if(CopyBuffer(g_bbHandle, LOWER_BAND, 0, 1, bbLower) < 1) return;
   if(CopyBuffer(g_atrHandle, 0, 0, 1, atr) < 1) return;
   if(CopyBuffer(g_rsiHandle, 0, 0, 1, rsi) < 1) return;
   if(CopyBuffer(g_emaFastHandle, 0, 0, 1, emaFast) < 1) return;
   if(CopyBuffer(g_emaSlowHandle, 0, 0, 1, emaSlow) < 1) return;

   // 计算肯特纳通道
   double kcUpper, kcMiddle, kcLower;
   CalculateKeltnerChannel(kcUpper, kcMiddle, kcLower, atr[0]);

   // 获取当前价格
   double close = iClose(NULL, PERIOD_M15, 0);
   double high = iHigh(NULL, PERIOD_M15, 0);
   double low = iLow(NULL, PERIOD_M15, 0);

   bool isAsian = IsAsianSession();
   bool isEuropean = IsEuropeanSession();

   // 计算波动率指标
   double squeezeRatio = CalculateSqueezeRatio(bbUpper[0], bbLower[0], bbMiddle[0], kcUpper, kcLower);
   bool isTrend = (squeezeRatio >= InpSqueezeThreshold);
   bool squeezeRelease = CheckSqueezeRelease(bbUpper, bbLower, kcUpper, kcLower);

   // 获取VWAP (简化计算)
   double vwap = GetVWAP();

   // ═══════════════════════════════════════════════════════════════════
   // 【Task 1.1】持仓出场检查 - 每Tick实时执行 (移出 newBar 限制)
   // 与Python Tick引擎对齐: 止损/追踪止损/止盈必须实时检查
   // ═══════════════════════════════════════════════════════════════════
   if(PositionSelect(Symbol()))
   {
      // 更新持仓统计 (每Tick更新最高最低价)
      UpdatePositionStats(high, low);

      // 【关键修复】出场检查移出 newBar 限制，每Tick执行
      // 使用当前实时 atr[0] 计算
      CheckExitConditions(close, Bid, Ask, atr[0], vwap);

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

      // ═════════════════════════════════════════════════════════════════
      // 【Task 1.3】策略B挂单级入场 - 每Tick检测价格突破
      // 与Python Tick引擎对齐: Ask >= breakout_high 时立即入场
      // ═════════════════════════════════════════════════════════════════
      if(g_pendingConfirmation)
      {
         // 【关键修复】每Tick检测，不等待 newBar
         CheckPendingEntryEveryTick(atr[0]);
      }

      // 入场信号检查 (只在 newBar 时检测新信号)
      if(newBar)
      {
         // 策略A检查 - 均值回归
         if(InpEnableStrategyA && isAsian && !g_pendingConfirmation)
         {
            CheckStrategyAEntry(close, bbUpper[0], bbLower[0], rsi[0], atr[0], high, low);
         }

         // 策略B检查 - 动量突破 (设置待确认状态)
         if(InpEnableStrategyB && isEuropean && !g_pendingConfirmation)
         {
            CheckStrategyBEntry(close, bbUpper[0], bbLower[0], bbMiddle[0],
                               kcUpper, kcLower, emaFast[0], emaSlow[0],
                               isTrend, squeezeRelease, atr[0], high, low);
         }
      }
   }

   if(newBar) lastBarTime = currentBarTime;
}

//+------------------------------------------------------------------+
//| 【Task 1.3】每Tick检测策略B挂单入场                               |
//| 与Python Tick引擎对齐: 价格突破时立即执行                         |
//+------------------------------------------------------------------+
void CheckPendingEntryEveryTick(double currentATR)
{
   if(!g_pendingConfirmation) return;

   // 多头挂单: Ask >= 突破高点时入场
   if(g_pendingDirection == 1)
   {
      // 【关键对齐】Python: tick_ask >= breakout_high 时入场
      if(Ask >= g_pendingBreakoutHigh)
      {
         Print("【Tick级入场】多头触发: Ask=", Ask, " >= BreakoutHigh=", g_pendingBreakoutHigh);

         double sl = MathMax(g_pendingBreakoutHigh - InpSLATRMultB * g_pendingATR, g_pendingPrevLow);
         g_avgATR = CalculateAverageATR();

         OpenPositionWithPrice(ORDER_TYPE_BUY, g_pendingBreakoutHigh, sl, 0, "B");
         ResetPullbackState();
         return;
      }
   }
   // 空头挂单: Bid <= 突破低点时入场
   else if(g_pendingDirection == -1)
   {
      // 【关键对齐】Python: tick_bid <= breakout_low 时入场
      if(Bid <= g_pendingBreakoutLow)
      {
         Print("【Tick级入场】空头触发: Bid=", Bid, " <= BreakoutLow=", g_pendingBreakoutLow);

         double sl = MathMin(g_pendingBreakoutLow + InpSLATRMultB * g_pendingATR, g_pendingPrevHigh);
         g_avgATR = CalculateAverageATR();

         OpenPositionWithPrice(ORDER_TYPE_SELL, g_pendingBreakoutLow, sl, 0, "B");
         ResetPullbackState();
         return;
      }
   }

   // 超时检查 (在 newBar 时由调用方处理)
}

//+------------------------------------------------------------------+
//| 计算肯特纳通道                                                    |
//+------------------------------------------------------------------+
void CalculateKeltnerChannel(double &upper, double &middle, double &lower, double atr)
{
   middle = iMA(NULL, PERIOD_M15, InpKCPeriod, 0, MODE_EMA, PRICE_CLOSE, 0);
   upper = middle + InpKCATRMult * atr;
   lower = middle - InpKCATRMult * atr;
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
//| 检查波动率挤压释放                                                |
//+------------------------------------------------------------------+
bool CheckSqueezeRelease(double &bbUpper[], double &bbLower[],
                         double kcUpper, double kcLower)
{
   double bbUpperPrev[], bbLowerPrev[];
   if(CopyBuffer(g_bbHandle, UPPER_BAND, 1, 1, bbUpperPrev) < 1) return false;
   if(CopyBuffer(g_bbHandle, LOWER_BAND, 1, 1, bbLowerPrev) < 1) return false;

   bool releaseUp = (bbUpper[0] > kcUpper) && (bbUpperPrev[0] <= kcUpper);
   bool releaseDown = (bbLower[0] < kcLower) && (bbLowerPrev[0] >= kcLower);

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
//| 【Task 1.4】简化VWAP计算                                          |
//| 使用缓存避免每Tick循环100次                                       |
//+------------------------------------------------------------------+
double GetVWAP()
{
   // 每根K线只计算一次
   datetime currentBarTime = iTime(NULL, PERIOD_M15, 0);
   if(currentBarTime == g_vwapLastUpdate)
      return g_cachedVWAP;

   g_vwapLastUpdate = currentBarTime;

   // 简化计算: 使用最近20根K线
   double cumulativeTPV = 0;
   double cumulativeVol = 0;
   int lookback = MathMin(20, iBars(NULL, PERIOD_M15));

   for(int i = 0; i < lookback; i++)
   {
      double h = iHigh(NULL, PERIOD_M15, i);
      double l = iLow(NULL, PERIOD_M15, i);
      double c = iClose(NULL, PERIOD_M15, i);
      double vol = (double)iVolume(NULL, PERIOD_M15, i);

      cumulativeTPV += (h + l + c) / 3.0 * vol;
      cumulativeVol += vol;
   }

   g_cachedVWAP = (cumulativeVol > 0) ? cumulativeTPV / cumulativeVol : iClose(NULL, PERIOD_M15, 0);
   return g_cachedVWAP;
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
//| 计算平均ATR                                                       |
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
//| 检查是否为亚盘时段                                                |
//+------------------------------------------------------------------+
bool IsAsianSession()
{
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   return (dt.hour >= InpAsianStart && dt.hour < InpAsianEnd);
}

//+------------------------------------------------------------------+
//| 检查是否为欧美盘时段                                              |
//+------------------------------------------------------------------+
bool IsEuropeanSession()
{
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   if(InpEuropeanEnd == 0)
      return (dt.hour >= InpEuropeanStart);
   else
      return (dt.hour >= InpEuropeanStart || dt.hour < InpEuropeanEnd);
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
      double vwap = GetVWAP();

      g_avgATR = CalculateAverageATR();
      Print("策略A做多: 止损锚定=", slAnchor, " 止损=", sl);
      OpenPosition(ORDER_TYPE_BUY, sl, vwap, "A");
      return;
   }

   // 做空条件
   if(close >= bbUpper && rsi > InpRSIOverbought)
   {
      double slAnchor = MathMax(close, bbUpper);
      double sl = slAnchor + InpSLATRMultA * atr;
      double vwap = GetVWAP();

      g_avgATR = CalculateAverageATR();
      Print("策略A做空: 止损锚定=", slAnchor, " 止损=", sl);
      OpenPosition(ORDER_TYPE_SELL, sl, vwap, "A");
      return;
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

      SetPullbackState(1, high, low, bbUpper, bbLower, atr, prevLow, prevHigh, emaFast - emaSlow);
      Print("策略B: 做多信号待确认, 挂单价=", high, " 等待Ask突破...");
      return;
   }

   // 做空条件
   if(close < bbLower && bbLower < kcLower && emaFast < emaSlow)
   {
      double prevLow = iLow(NULL, PERIOD_M15, 1);
      double prevHigh = iHigh(NULL, PERIOD_M15, 1);

      SetPullbackState(-1, high, low, bbUpper, bbLower, atr, prevLow, prevHigh, emaSlow - emaFast);
      Print("策略B: 做空信号待确认, 挂单价=", low, " 等待Bid跌破...");
      return;
   }
}

//+------------------------------------------------------------------+
//| 设置待确认状态                                                    |
//+------------------------------------------------------------------+
void SetPullbackState(int direction, double breakoutHigh, double breakoutLow,
                      double bbUpper, double bbLower, double atr,
                      double prevLow, double prevHigh, double emaDiff)
{
   g_pendingConfirmation = true;
   g_confirmationBarsLeft = InpPullbackBars;
   g_pendingDirection = direction;
   g_pendingBreakoutHigh = breakoutHigh;
   g_pendingBreakoutLow = breakoutLow;
   g_pendingBBUpper = bbUpper;
   g_pendingBBLower = bbLower;
   g_pendingATR = atr;
   g_pendingPrevLow = prevLow;
   g_pendingPrevHigh = prevHigh;
   g_pendingEMADiff = emaDiff;
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
   g_pendingBBUpper = 0;
   g_pendingBBLower = 0;
   g_pendingATR = 0;
   g_pendingPrevLow = 0;
   g_pendingPrevHigh = 0;
   g_pendingEMADiff = 0;
}

//+------------------------------------------------------------------+
//| 开仓 (市价)                                                       |
//+------------------------------------------------------------------+
bool OpenPosition(ENUM_ORDER_TYPE orderType, double sl, double tp, string strategy)
{
   if(PositionSelect(Symbol())) return false;
   double price = (orderType == ORDER_TYPE_BUY) ? Ask : Bid;
   return OpenPositionWithPrice(orderType, price, sl, tp, strategy);
}

//+------------------------------------------------------------------+
//| 开仓 (指定价格)                                                   |
//+------------------------------------------------------------------+
bool OpenPositionWithPrice(ENUM_ORDER_TYPE orderType, double price, double sl, double tp, string strategy)
{
   if(PositionSelect(Symbol())) return false;

   double tickSize = SymbolInfoDouble(Symbol(), SYMBOL_TRADE_TICK_SIZE);
   sl = NormalizeDouble(MathRound(sl / tickSize) * tickSize, (int)SymbolInfoInteger(Symbol(), SYMBOL_DIGITS));
   if(tp > 0)
      tp = NormalizeDouble(MathRound(tp / tickSize) * tickSize, (int)SymbolInfoInteger(Symbol(), SYMBOL_DIGITS));

   MqlTradeRequest request = {};
   request.action = TRADE_ACTION_DEAL;
   request.symbol = Symbol();
   request.volume = InpLotSize;
   request.type = orderType;
   request.price = (orderType == ORDER_TYPE_BUY) ? Ask : Bid;
   request.sl = sl;
   request.tp = tp;
   request.deviation = InpSlippage;
   request.magic = InpMagicNumber;
   request.comment = InpTradeComment + "_" + strategy;

   MqlTradeResult result = {};

   if(!OrderSend(request, result))
   {
      Print("开仓失败: ", GetLastError());
      return false;
   }

   if(result.retcode == TRADE_RETCODE_DONE)
   {
      g_currentStrategy = strategy;
      g_entryTime = TimeCurrent();
      g_entryPrice = price;
      g_fixedStopLoss = sl;
      g_barsHeld = 0;
      g_highestSinceEntry = price;
      g_lowestSinceEntry = price;

      double atr[];
      if(CopyBuffer(g_atrHandle, 0, 0, 1, atr) > 0)
         ; // 不再保存 g_entryATR

      Print("开仓成功: ", (orderType == ORDER_TYPE_BUY ? "做多" : "做空"),
            " 策略", strategy, " 价格:", price, " 止损:", sl);

      SavePositionState();
      return true;
   }

   return false;
}

//+------------------------------------------------------------------+
//| 更新持仓统计                                                      |
//+------------------------------------------------------------------+
void UpdatePositionStats(double high, double low)
{
   g_highestSinceEntry = MathMax(g_highestSinceEntry, high);
   g_lowestSinceEntry = MathMin(g_lowestSinceEntry, low);
}

//+------------------------------------------------------------------+
//| 【Task 1.1 & 1.2】出场条件检查 (每Tick执行)                       |
//| 关键修复: 追踪止损使用当前实时ATR                                 |
//+------------------------------------------------------------------+
void CheckExitConditions(double close, double tickBid, double tickAsk, double currentATR, double vwap)
{
   if(!PositionSelect(Symbol())) return;

   long posType = PositionGetInteger(POSITION_TYPE);
   double sl = PositionGetDouble(POSITION_SL);

   bool shouldClose = false;
   string reason = "";

   // ═══════════════════════════════════════════════════════════════════
   // 策略A出场 (每Tick检查)
   // ═══════════════════════════════════════════════════════════════════
   if(g_currentStrategy == "A")
   {
      // 止损检查 (使用实际Tick价格)
      if(posType == POSITION_TYPE_BUY)
      {
         // 【与Python对齐】多头止损: tick_bid <= stop_loss
         if(tickBid <= sl)
         {
            shouldClose = true;
            reason = "止损";
         }
         // VWAP止盈 (使用Tick价格)
         else if(tickAsk >= vwap)
         {
            shouldClose = true;
            reason = "VWAP止盈";
         }
      }
      else if(posType == POSITION_TYPE_SELL)
      {
         // 【与Python对齐】空头止损: tick_ask >= stop_loss
         if(tickAsk >= sl)
         {
            shouldClose = true;
            reason = "止损";
         }
         // VWAP止盈
         else if(tickBid <= vwap)
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

   // ═══════════════════════════════════════════════════════════════════
   // 策略B出场 (每Tick检查)
   // ═══════════════════════════════════════════════════════════════════
   if(g_currentStrategy == "B")
   {
      if(posType == POSITION_TYPE_BUY)
      {
         // 初始止损
         if(tickBid <= sl)
         {
            shouldClose = true;
            reason = "初始止损";
         }
         // 【Task 1.2 关键修复】追踪止损使用当前实时ATR
         // 与Python对齐: trailing_stop = highest_price - mult * current_atr
         else
         {
            double trailingStop = g_highestSinceEntry - InpTrailingATRMult * currentATR;
            if(tickBid <= trailingStop && g_highestSinceEntry > g_entryPrice)
            {
               shouldClose = true;
               reason = "追踪止损";
            }
         }
      }
      else if(posType == POSITION_TYPE_SELL)
      {
         // 初始止损
         if(tickAsk >= sl)
         {
            shouldClose = true;
            reason = "初始止损";
         }
         // 【Task 1.2 关键修复】追踪止损使用当前实时ATR
         else
         {
            double trailingStop = g_lowestSinceEntry + InpTrailingATRMult * currentATR;
            if(tickAsk >= trailingStop && g_lowestSinceEntry < g_entryPrice)
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
      ClosePosition(reason);
   }
}

//+------------------------------------------------------------------+
//| 平仓                                                              |
//+------------------------------------------------------------------+
bool ClosePosition(string reason)
{
   if(!PositionSelect(Symbol())) return false;

   long posType = PositionGetInteger(POSITION_TYPE);
   double volume = PositionGetDouble(POSITION_VOLUME);

   MqlTradeRequest request = {};
   request.action = TRADE_ACTION_DEAL;
   request.symbol = Symbol();
   request.volume = volume;
   request.type = (posType == POSITION_TYPE_BUY) ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;
   request.price = (posType == POSITION_TYPE_BUY) ? Bid : Ask;
   request.deviation = InpSlippage;
   request.magic = InpMagicNumber;
   request.comment = InpTradeComment + "_平仓_" + reason;

   MqlTradeResult result = {};

   if(!OrderSend(request, result))
   {
      Print("平仓失败: ", GetLastError());
      return false;
   }

   if(result.retcode == TRADE_RETCODE_DONE)
   {
      Print("平仓成功: 策略", g_currentStrategy, " 原因:", reason);
      ResetPositionState();
      return true;
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
   g_lowestSinceEntry = DBL_MAX;
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
