//+------------------------------------------------------------------+
//| XAUUSD Triple Strategy EA - MQL4 Implementation                  |
//|                                                                  |
//| 策略说明:                                                        |
//|   策略A - 均值回归 (亚盘 06:00-14:00 北京时间)                    |
//|   策略B - 动量突破 (欧美盘 15:00-00:00 北京时间)                  |
//|   策略C - 趋势角度突破 (全时段，SMA角度+K线突破)                  |
//|                                                                  |
//| 2026-03-24 更新 v6.0 - 新增策略C (SMA角度突破):                  |
//|   - 【新增】策略C: SMA角度(ATR标准化) + K线突破                  |
//|   - 【新增】角度计算: θ = atan((SMA[t]-SMA[t-n])/(ATR[t]*n))     |
//|   - 【新增】突破确认: 突破前N根K线高低点                         |
//|                                                                  |
//| 2026-03-22 更新 v5.2 - 核心逻辑缺陷修复:                         |
//|   - 【修复1】并发持仓逻辑: 策略A/B/C独立追踪持仓                 |
//|   - 【修复4】动态手数: NormalizeDouble防止浮点截断Error 131      |
//|   - 【修复5】VWAP时区: EST时间锚定确保美东17:00重置              |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, XAUUSD Triple Strategy"
#property link      ""
#property version   "6.00"
#property strict

//+------------------------------------------------------------------+
//| 输入参数 (策略A - 均值回归)                                       |
//+------------------------------------------------------------------+
input int    InpBBPeriod = 20;           // 布林带周期
input double InpBBStd = 2.0;             // 布林带标准差倍数
input int    InpRSIPeriod = 14;          // RSI周期
input int    InpRSIOversold = 25;        // RSI超卖阈值
input int    InpRSIOverbought = 75;      // RSI超买阈值
input double InpSLATRMultA = 1.0;        // 策略A止损ATR倍数
input int    InpMaxHoldBarsA = 5;        // 策略A最大持仓K线数

//+------------------------------------------------------------------+
//| 输入参数 (策略B - 动量突破)                                       |
//+------------------------------------------------------------------+
input int    InpEMAFastB = 20;           // 策略B快速EMA周期
input int    InpEMASlowB = 50;           // 策略B慢速EMA周期
input int    InpKCPeriod = 20;           // 肯特纳通道周期
input double InpKCATRMult = 1.5;         // 肯特纳通道ATR倍数
input double InpSLATRMultB = 1.2;        // 策略B止损ATR倍数
input double InpTrailingATRMultB = 2.5;  // 策略B追踪止损ATR倍数
input double InpSqueezeThreshold = 0.8;  // 波动率挤压阈值

//+------------------------------------------------------------------+
//| 输入参数 (策略C - 趋势角度突破) 【新增】                          |
//+------------------------------------------------------------------+
input int    InpSMAPeriodC = 20;         // 策略C SMA周期
input int    InpAngleLookbackC = 5;      // 策略C角度回看K线数
input double InpAngleThresholdC = 3.0;   // 策略C角度阈值(度)
input int    InpBreakoutLookbackC = 2;   // 策略C突破回看K线数
input double InpSLATRMultC = 2.0;        // 策略C止损ATR倍数
input double InpRiskRewardC = 2.0;       // 策略C盈亏比
input bool   InpUseFixedExitC = true;    // 策略C使用固定盈亏比出场

//+------------------------------------------------------------------+
//| 通用参数                                                          |
//+------------------------------------------------------------------+
input int    InpATRPeriod = 14;          // ATR周期
input int    InpBrokerUTCOffset = 2;     // 券商服务器UTC时区
input int    InpAsianStartBJ = 6;        // 亚盘开始小时 (北京时间)
input int    InpAsianEndBJ = 14;         // 亚盘结束小时 (北京时间)
input int    InpEuropeanStartBJ = 15;    // 欧美盘开始小时 (北京时间)
input int    InpEuropeanEndBJ = 2;       // 欧美盘结束小时 (北京时间)
input double InpMaxSpread = 50.0;        // 最大允许点差

//+------------------------------------------------------------------+
//| 交易设置                                                          |
//+------------------------------------------------------------------+
input double InpLotSize = 1.0;           // 交易手数
input int    InpSlippage = 30;           // 滑点
input int    InpMagicNumber = 20260324;  // 魔术数字
input string InpTradeComment = "XAUUSD_TripleStrategy";  // 交易注释
input bool   InpUseDynamicLot = false;   // 启用动态仓位
input double InpRiskPercent = 2.0;       // 单笔交易风险百分比

// 策略开关
input bool   InpEnableStrategyA = true;  // 启用策略A
input bool   InpEnableStrategyB = true;  // 启用策略B
input bool   InpEnableStrategyC = true;  // 启用策略C

//+------------------------------------------------------------------+
//| 全局变量                                                          |
//+------------------------------------------------------------------+
int g_pendingOrderTicket = 0;            // 策略B挂单票号
double g_pendingStopLoss = 0;            // 策略B挂单止损价

double g_cachedVWAP = 0;                 // VWAP缓存
datetime g_vwapCacheBarTime = 0;

// 策略B追踪止损存储
#define MAX_TRAILING_STOP_TRACKERS 100
int g_trailingStopTickets[MAX_TRAILING_STOP_TRACKERS];
int g_trailingStopCount = 0;

// DST探测
int g_detectedDSTOffset = 2;

//+------------------------------------------------------------------+
//| EA初始化                                                          |
//+------------------------------------------------------------------+
int OnInit()
{
   Print("=== XAUUSD Triple Strategy EA v6.0 ===");
   Print("【策略A】均值回归 - 亚盘时段 RSI+BB");
   Print("【策略B】动量突破 - 欧美盘时段 EMA+BB突破");
   Print("【策略C】趋势角度突破 - 全时段 SMA角度+K线突破 (新增)");

   DetectDSTOffset();
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| DST探测                                                           |
//+------------------------------------------------------------------+
void DetectDSTOffset()
{
   datetime serverTime = TimeCurrent();
   int month = TimeMonth(serverTime);
   int day = TimeDay(serverTime);
   int dayOfWeek = TimeDayOfWeek(serverTime);

   bool isDST = false;
   if(month >= 4 && month <= 10)
      isDST = true;
   else if(month == 3)
   {
      int secondSunday = 8 + (6 - dayOfWeek) % 7;
      isDST = (day >= secondSunday);
   }
   else if(month == 11)
   {
      int firstSunday = 1 + (7 - dayOfWeek) % 7;
      isDST = (day < firstSunday);
   }

   g_detectedDSTOffset = isDST ? 3 : 2;

   Print("【DST】夏令时: ", (isDST ? "是" : "否"),
         ", UTC偏移: +", g_detectedDSTOffset);
}

//+------------------------------------------------------------------+
//| 每个Tick处理                                                      |
//+------------------------------------------------------------------+
void OnTick()
{
   // 点差过滤
   double currentSpread = MarketInfo(Symbol(), MODE_SPREAD);
   if(currentSpread > InpMaxSpread) return;

   // 管理策略B挂单
   ManagePendingOrders();

   // 检查新K线
   static datetime lastBarTime = 0;
   datetime currentBarTime = iTime(NULL, PERIOD_M15, 0);
   bool newBar = (currentBarTime != lastBarTime);

   // 获取指标值 (使用索引1 - 已收盘K线)
   double bbUpper = iBands(NULL, PERIOD_M15, InpBBPeriod, 0, InpBBStd, PRICE_CLOSE, MODE_UPPER, 1);
   double bbLower = iBands(NULL, PERIOD_M15, InpBBPeriod, 0, InpBBStd, PRICE_CLOSE, MODE_LOWER, 1);
   double bbMiddle = iBands(NULL, PERIOD_M15, InpBBPeriod, 0, InpBBStd, PRICE_CLOSE, MODE_MAIN, 1);

   double atr = iATR(NULL, PERIOD_M15, InpATRPeriod, 1);
   double rsi = iRSI(NULL, PERIOD_M15, InpRSIPeriod, PRICE_CLOSE, 1);

   double emaFast = iMA(NULL, PERIOD_M15, InpEMAFastB, 0, MODE_EMA, PRICE_CLOSE, 1);
   double emaSlow = iMA(NULL, PERIOD_M15, InpEMASlowB, 0, MODE_EMA, PRICE_CLOSE, 1);

   // 策略C SMA
   double smaC = iMA(NULL, PERIOD_M15, InpSMAPeriodC, 0, MODE_SMA, PRICE_CLOSE, 1);
   double smaC_prev = iMA(NULL, PERIOD_M15, InpSMAPeriodC, 0, MODE_SMA, PRICE_CLOSE, 1 + InpAngleLookbackC);

   // 当前价格
   double close = iClose(NULL, PERIOD_M15, 0);
   double close1 = iClose(NULL, PERIOD_M15, 1);
   double high = iHigh(NULL, PERIOD_M15, 0);
   double low = iLow(NULL, PERIOD_M15, 0);
   double high1 = iHigh(NULL, PERIOD_M15, 1);
   double low1 = iLow(NULL, PERIOD_M15, 1);

   // 时段判断
   bool isAsian = IsAsianSession();
   bool isEuropean = IsEuropeanSession();

   // VWAP
   double vwap = GetDailyVWAP();

   // 持仓检查 - 分别追踪三个策略
   bool hasPositionA = false, hasPositionB = false, hasPositionC = false;
   int positionTicketsA[MAX_TRAILING_STOP_TRACKERS];
   int positionTicketsB[MAX_TRAILING_STOP_TRACKERS];
   int positionTicketsC[MAX_TRAILING_STOP_TRACKERS];
   int countA = 0, countB = 0, countC = 0;

   int totalOrders = OrdersTotal();
   for(int i = totalOrders - 1; i >= 0; i--)
   {
      if(OrderSelect(i, SELECT_BY_POS, MODE_TRADES))
      {
         if(OrderSymbol() == Symbol() && OrderMagicNumber() == InpMagicNumber)
         {
            int orderType = OrderType();
            if(orderType == OP_BUY || orderType == OP_SELL)
            {
               string comment = OrderComment();
               int ticket = OrderTicket();

               if(StringFind(comment, "_A") >= 0)
               {
                  hasPositionA = true;
                  if(countA < MAX_TRAILING_STOP_TRACKERS)
                     positionTicketsA[countA++] = ticket;
               }
               else if(StringFind(comment, "_B") >= 0)
               {
                  hasPositionB = true;
                  if(countB < MAX_TRAILING_STOP_TRACKERS)
                     positionTicketsB[countB++] = ticket;
               }
               else if(StringFind(comment, "_C") >= 0)
               {
                  hasPositionC = true;
                  if(countC < MAX_TRAILING_STOP_TRACKERS)
                     positionTicketsC[countC++] = ticket;
               }
            }
         }
      }
   }

   // 清理追踪止损记录
   CleanupTrailingStopTrackers();

   // 出场检查
   for(int p = 0; p < countA; p++)
      CheckExitStrategyA(positionTicketsA[p], atr, vwap);
   for(int p = 0; p < countB; p++)
      CheckExitStrategyB(positionTicketsB[p], atr);
   for(int p = 0; p < countC; p++)
      CheckExitStrategyC(positionTicketsC[p], atr);

   // 入场检查 (仅在新K线时)
   if(newBar)
   {
      // 策略A - 均值回归
      if(InpEnableStrategyA && !hasPositionA && isAsian)
         CheckStrategyAEntry(close1, bbUpper, bbLower, rsi, atr, high1, low1);

      // 策略B - 动量突破
      if(InpEnableStrategyB && !hasPositionB && isEuropean && g_pendingOrderTicket == 0)
         CheckStrategyBEntry(close1, bbUpper, bbLower, emaFast, emaSlow, atr, high1, low1);

      // 策略C - 趋势角度突破
      if(InpEnableStrategyC && !hasPositionC)
         CheckStrategyCEntry(smaC, smaC_prev, atr, close, high, low);
   }

   if(newBar) lastBarTime = currentBarTime;
}

//+------------------------------------------------------------------+
//| 策略C - 趋势角度突破入场
//+------------------------------------------------------------------+
void CheckStrategyCEntry(double smaCurrent, double smaPrev, double atr,
                         double close, double high, double low)
{
   if(atr <= 0) return;

   // 计算SMA角度 (ATR标准化)
   // θ = atan((SMA[t] - SMA[t-n]) / (ATR[t] * n)) * (180/π)
   double smaDiff = smaCurrent - smaPrev;
   double angleRad = MathArctan(smaDiff / (atr * InpAngleLookbackC));
   double angleDeg = angleRad * 180.0 / M_PI;

   // 使用iHighest/iLowest获取前N根K线的高低点 (高效，仅2次API调用)
   int highestIdx = iHighest(NULL, PERIOD_M15, MODE_HIGH, InpBreakoutLookbackC, 1);
   int lowestIdx = iLowest(NULL, PERIOD_M15, MODE_LOW, InpBreakoutLookbackC, 1);

   if(highestIdx < 0 || lowestIdx < 0) return; // 数据无效

   double highestN = iHigh(NULL, PERIOD_M15, highestIdx);
   double lowestN = iLow(NULL, PERIOD_M15, lowestIdx);

   // 多头信号: 角度 > 阈值 且 突破前N根K线高点
   if(angleDeg > InpAngleThresholdC && high > highestN)
   {
      double sl = close - atr * InpSLATRMultC;
      double tp = 0;

      if(InpUseFixedExitC)
         tp = close + atr * InpRiskRewardC * InpSLATRMultC;

      Print("策略C做多: 角度=", DoubleToString(angleDeg, 2), "°, 突破>", DoubleToString(highestN, 2));

      OpenPositionMQL4(OP_BUY, sl, tp, "C");
      return;
   }

   // 空头信号: 角度 < -阈值 且 跌破前N根K线低点
   if(angleDeg < -InpAngleThresholdC && low < lowestN)
   {
      double sl = close + atr * InpSLATRMultC;
      double tp = 0;

      if(InpUseFixedExitC)
         tp = close - atr * InpRiskRewardC * InpSLATRMultC;

      Print("策略C做空: 角度=", DoubleToString(angleDeg, 2), "°, 跌破<", DoubleToString(lowestN, 2));

      OpenPositionMQL4(OP_SELL, sl, tp, "C");
   }
}

//+------------------------------------------------------------------+
//| 策略C - 出场检查
//+------------------------------------------------------------------+
void CheckExitStrategyC(int ticket, double atr)
{
   if(!OrderSelect(ticket, SELECT_BY_TICKET)) return;

   int orderType = OrderType();
   double positionSL = OrderStopLoss();
   double positionTP = OrderTakeProfit();
   double openPrice = OrderOpenPrice();

   bool shouldClose = false;
   string reason = "";

   // 固定止盈止损出场
   if(orderType == OP_BUY)
   {
      if(Bid <= positionSL)
      {
         shouldClose = true;
         reason = "C止损";
      }
      else if(positionTP > 0 && Ask >= positionTP)
      {
         shouldClose = true;
         reason = "C止盈";
      }
   }
   else if(orderType == OP_SELL)
   {
      if(Ask >= positionSL)
      {
         shouldClose = true;
         reason = "C止损";
      }
      else if(positionTP > 0 && Bid <= positionTP)
      {
         shouldClose = true;
         reason = "C止盈";
      }
   }

   // 追踪止损 (使用iHighest/iLowest优化)
   if(!shouldClose)
   {
      datetime openTime = OrderOpenTime();
      int startBar = iBarShift(NULL, PERIOD_M15, openTime);
      if(startBar < 0) startBar = 0;
      int barsSinceEntry = startBar + 1;

      int highestIdx = iHighest(NULL, PERIOD_M15, MODE_HIGH, barsSinceEntry, 0);
      int lowestIdx = iLowest(NULL, PERIOD_M15, MODE_LOW, barsSinceEntry, 0);

      double highestSinceEntry = (highestIdx >= 0) ? iHigh(NULL, PERIOD_M15, highestIdx) : 0;
      double lowestSinceEntry = (lowestIdx >= 0) ? iLow(NULL, PERIOD_M15, lowestIdx) : DBL_MAX;

      if(orderType == OP_BUY)
      {
         double trailingStop = highestSinceEntry - InpSLATRMultC * atr;
         if(Bid <= trailingStop && highestSinceEntry > openPrice)
         {
            shouldClose = true;
            reason = "C追踪止损";
         }
      }
      else
      {
         double trailingStop = lowestSinceEntry + InpSLATRMultC * atr;
         if(Ask >= trailingStop && lowestSinceEntry < openPrice)
         {
            shouldClose = true;
            reason = "C追踪止损";
         }
      }
   }

   if(shouldClose)
      ClosePositionMQL4(ticket, reason);
}

//+------------------------------------------------------------------+
//| 策略A入场检查                                                     |
//+------------------------------------------------------------------+
void CheckStrategyAEntry(double close, double bbUpper, double bbLower,
                         double rsi, double atr, double high, double low)
{
   double currentRange = high - low;
   if(atr > 0 && currentRange > atr * 2.0) return; // 异常波动过滤

   // 做多条件
   if(close <= bbLower && rsi < InpRSIOversold)
   {
      double sl = close - InpSLATRMultA * atr;
      double tp = GetDailyVWAP();

      if(tp <= close) // VWAP无效时用固定盈亏比
         tp = close + MathAbs(close - sl) * 2.0;

      Print("策略A做多: RSI=", DoubleToString(rsi, 1),
            " BB_Lower=", DoubleToString(bbLower, 2));
      OpenPositionMQL4(OP_BUY, sl, tp, "A");
      return;
   }

   // 做空条件
   if(close >= bbUpper && rsi > InpRSIOverbought)
   {
      double sl = close + InpSLATRMultA * atr;
      double tp = GetDailyVWAP();

      if(tp >= close)
         tp = close - MathAbs(close - sl) * 2.0;

      Print("策略A做空: RSI=", DoubleToString(rsi, 1),
            " BB_Upper=", DoubleToString(bbUpper, 2));
      OpenPositionMQL4(OP_SELL, sl, tp, "A");
   }
}

//+------------------------------------------------------------------+
//| 策略B入场检查                                                     |
//+------------------------------------------------------------------+
void CheckStrategyBEntry(double close, double bbUpper, double bbLower,
                         double emaFast, double emaSlow, double atr,
                         double high, double low)
{
   double currentRange = high - low;
   if(atr > 0 && currentRange > atr * 2.0) return;

   // EMA趋势判断
   bool emaBullish = emaFast > emaSlow * 1.0005;
   bool emaBearish = emaFast < emaSlow * 0.9995;

   double prevClose = iClose(NULL, PERIOD_M15, 2);
   double prevBBUpper = iBands(NULL, PERIOD_M15, InpBBPeriod, 0, InpBBStd, PRICE_CLOSE, MODE_UPPER, 2);
   double prevBBLower = iBands(NULL, PERIOD_M15, InpBBPeriod, 0, InpBBStd, PRICE_CLOSE, MODE_LOWER, 2);

   // 做多条件: 突破布林带 + EMA多头
   if(prevClose <= prevBBUpper && close > bbUpper && emaBullish)
   {
      double prevLow = iLow(NULL, PERIOD_M15, 2);
      double entryPrice = high;
      double sl = MathMax(entryPrice - InpSLATRMultB * atr, prevLow);

      int ticket = SendBuyStopOrder(entryPrice, sl);
      if(ticket > 0)
      {
         g_pendingOrderTicket = ticket;
         g_pendingStopLoss = sl;
         Print("策略B: 做多挂单 Ticket=", ticket);
      }
      return;
   }

   // 做空条件: 跌破布林带 + EMA空头
   if(prevClose >= prevBBLower && close < bbLower && emaBearish)
   {
      double prevHigh = iHigh(NULL, PERIOD_M15, 2);
      double entryPrice = low;
      double sl = MathMin(entryPrice + InpSLATRMultB * atr, prevHigh);

      int ticket = SendSellStopOrder(entryPrice, sl);
      if(ticket > 0)
      {
         g_pendingOrderTicket = ticket;
         g_pendingStopLoss = sl;
         Print("策略B: 做空挂单 Ticket=", ticket);
      }
   }
}

//+------------------------------------------------------------------+
//| 策略A出场检查                                                     |
//+------------------------------------------------------------------+
void CheckExitStrategyA(int ticket, double atr, double vwap)
{
   if(!OrderSelect(ticket, SELECT_BY_TICKET)) return;

   int orderType = OrderType();
   double positionSL = OrderStopLoss();
   datetime openTime = OrderOpenTime();
   int barsHeld = (int)((TimeCurrent() - openTime) / (15 * 60));

   bool shouldClose = false;
   string reason = "";

   if(orderType == OP_BUY)
   {
      if(Bid <= positionSL)
      {
         shouldClose = true;
         reason = "A止损";
      }
      else if(Ask >= vwap)
      {
         shouldClose = true;
         reason = "A_VWAP止盈";
      }
      else if(barsHeld >= InpMaxHoldBarsA)
      {
         shouldClose = true;
         reason = "A时间止损";
      }
   }
   else if(orderType == OP_SELL)
   {
      if(Ask >= positionSL)
      {
         shouldClose = true;
         reason = "A止损";
      }
      else if(Bid <= vwap)
      {
         shouldClose = true;
         reason = "A_VWAP止盈";
      }
      else if(barsHeld >= InpMaxHoldBarsA)
      {
         shouldClose = true;
         reason = "A时间止损";
      }
   }

   if(shouldClose)
      ClosePositionMQL4(ticket, reason);
}

//+------------------------------------------------------------------+
//| 策略B出场检查                                                     |
//+------------------------------------------------------------------+
void CheckExitStrategyB(int ticket, double atr)
{
   if(!OrderSelect(ticket, SELECT_BY_TICKET)) return;

   int orderType = OrderType();
   double positionSL = OrderStopLoss();
   double openPrice = OrderOpenPrice();
   datetime openTime = OrderOpenTime();

   double highestPrice = 0, lowestPrice = 1000000.0;
   int startBar = iBarShift(NULL, PERIOD_M15, openTime);
   for(int i = startBar; i >= 0; i--)
   {
      double barHigh = iHigh(NULL, PERIOD_M15, i);
      double barLow = iLow(NULL, PERIOD_M15, i);
      if(barHigh > highestPrice) highestPrice = barHigh;
      if(barLow < lowestPrice) lowestPrice = barLow;
   }

   bool shouldClose = false;
   string reason = "";

   if(orderType == OP_BUY)
   {
      if(Bid <= positionSL)
      {
         shouldClose = true;
         reason = "B初始止损";
      }
      else
      {
         double trailingStop = highestPrice - InpTrailingATRMultB * atr;
         if(Bid <= trailingStop && highestPrice > openPrice)
         {
            shouldClose = true;
            reason = "B追踪止损";
         }
      }
   }
   else if(orderType == OP_SELL)
   {
      if(Ask >= positionSL)
      {
         shouldClose = true;
         reason = "B初始止损";
      }
      else
      {
         double trailingStop = lowestPrice + InpTrailingATRMultB * atr;
         if(Ask >= trailingStop && lowestPrice < openPrice)
         {
            shouldClose = true;
            reason = "B追踪止损";
         }
      }
   }

   if(shouldClose)
   {
      RemoveTrailingStopTracker(ticket);
      ClosePositionMQL4(ticket, reason);
   }
}

//+------------------------------------------------------------------+
//| 挂单管理                                                          |
//+------------------------------------------------------------------+
void ManagePendingOrders()
{
   if(g_pendingOrderTicket == 0) return;

   if(!OrderSelect(g_pendingOrderTicket, SELECT_BY_TICKET))
   {
      ResetPendingState();
      return;
   }

   int orderType = OrderType();
   if(orderType == OP_BUY || orderType == OP_SELL)
   {
      Print("策略B挂单已成交 Ticket:", g_pendingOrderTicket);
      ResetPendingState();
      return;
   }

   // 检查过期 (4小时)
   datetime openTime = OrderOpenTime();
   if(TimeCurrent() - openTime > 4 * 3600)
   {
      OrderDelete(g_pendingOrderTicket);
      Print("策略B挂单已过期删除");
      ResetPendingState();
   }
}

void ResetPendingState()
{
   g_pendingOrderTicket = 0;
   g_pendingStopLoss = 0;
}

//+------------------------------------------------------------------+
//| 发送Buy Stop挂单                                                  |
//+------------------------------------------------------------------+
int SendBuyStopOrder(double triggerPrice, double stopLoss)
{
   int digits = (int)MarketInfo(Symbol(), MODE_DIGITS);
   triggerPrice = NormalizeDouble(triggerPrice, digits);
   stopLoss = NormalizeDouble(stopLoss, digits);

   if(Ask >= triggerPrice)
   {
      Print("【挂单放弃】价格已突破 Ask=", Ask, " >= Trigger=", triggerPrice);
      return -1;
   }

   double lotSize = CalculateDynamicLotSize(triggerPrice, stopLoss);
   datetime expiration = TimeCurrent() + 4 * 3600;

   int ticket = OrderSend(
      Symbol(),
      OP_BUYSTOP,
      lotSize,
      triggerPrice,
      InpSlippage,
      stopLoss,
      0,
      InpTradeComment + "_B",
      InpMagicNumber,
      expiration,
      clrBlue
   );

   if(ticket < 0)
      Print("【挂单失败】错误码: ", GetLastError());

   return ticket;
}

//+------------------------------------------------------------------+
//| 发送Sell Stop挂单                                                 |
//+------------------------------------------------------------------+
int SendSellStopOrder(double triggerPrice, double stopLoss)
{
   int digits = (int)MarketInfo(Symbol(), MODE_DIGITS);
   triggerPrice = NormalizeDouble(triggerPrice, digits);
   stopLoss = NormalizeDouble(stopLoss, digits);

   if(Bid <= triggerPrice)
   {
      Print("【挂单放弃】价格已跌破 Bid=", Bid, " <= Trigger=", triggerPrice);
      return -1;
   }

   double lotSize = CalculateDynamicLotSize(triggerPrice, stopLoss);
   datetime expiration = TimeCurrent() + 4 * 3600;

   int ticket = OrderSend(
      Symbol(),
      OP_SELLSTOP,
      lotSize,
      triggerPrice,
      InpSlippage,
      stopLoss,
      0,
      InpTradeComment + "_B",
      InpMagicNumber,
      expiration,
      clrRed
   );

   if(ticket < 0)
      Print("【挂单失败】错误码: ", GetLastError());

   return ticket;
}

//+------------------------------------------------------------------+
//| 动态仓位计算                                                      |
//+------------------------------------------------------------------+
double CalculateDynamicLotSize(double entryPrice, double stopLoss)
{
   if(!InpUseDynamicLot) return InpLotSize;
   if(stopLoss <= 0 || entryPrice <= 0) return InpLotSize;

   double tickValue = MarketInfo(Symbol(), MODE_TICKVALUE);
   double tickSize = MarketInfo(Symbol(), MODE_TICKSIZE);
   double minLot = MarketInfo(Symbol(), MODE_MINLOT);
   double maxLot = MarketInfo(Symbol(), MODE_MAXLOT);
   double lotStep = MarketInfo(Symbol(), MODE_LOTSTEP);

   if(tickValue <= 0 || tickSize <= 0) return InpLotSize;

   double stopLossPoints = MathAbs(entryPrice - stopLoss) / Point;
   if(stopLossPoints <= 0) return InpLotSize;

   double accountEquity = AccountEquity();
   double riskAmount = accountEquity * (InpRiskPercent / 100.0);
   double pointValuePerLot = tickValue * (Point / tickSize);

   double lotSize = riskAmount / (stopLossPoints * pointValuePerLot);

   if(lotStep > 0)
      lotSize = NormalizeDouble(MathFloor(lotSize / lotStep + 0.00001) * lotStep, 2);

   lotSize = MathMax(minLot, MathMin(maxLot, lotSize));
   lotSize = MathMin(lotSize, InpLotSize);

   return lotSize;
}

//+------------------------------------------------------------------+
//| 下单函数                                                          |
//+------------------------------------------------------------------+
bool OpenPositionMQL4(int orderType, double sl, double tp, string strategy)
{
   double price = (orderType == OP_BUY) ? Ask : Bid;
   color arrowColor = (orderType == OP_BUY) ? clrBlue : clrRed;

   int digits = (int)MarketInfo(Symbol(), MODE_DIGITS);
   sl = NormalizeDouble(sl, digits);
   if(tp > 0) tp = NormalizeDouble(tp, digits);

   double lotSize = CalculateDynamicLotSize(price, sl);

   int ticket = OrderSend(
      Symbol(),
      orderType,
      lotSize,
      price,
      InpSlippage,
      sl,
      tp,
      InpTradeComment + "_" + strategy,
      InpMagicNumber,
      0,
      arrowColor
   );

   if(ticket < 0)
   {
      Print("【下单失败】错误码: ", GetLastError());
      return false;
   }

   Print("【下单成功】Ticket:", ticket, " 策略:", strategy,
         " 手数:", DoubleToString(lotSize, 2));
   return true;
}

//+------------------------------------------------------------------+
//| 平仓函数                                                          |
//+------------------------------------------------------------------+
bool ClosePositionMQL4(int ticket, string reason)
{
   if(!OrderSelect(ticket, SELECT_BY_TICKET)) return false;
   if(OrderSymbol() != Symbol() || OrderMagicNumber() != InpMagicNumber) return false;

   int orderType = OrderType();
   if(orderType != OP_BUY && orderType != OP_SELL) return false;

   double lots = OrderLots();
   double closePrice = (orderType == OP_BUY) ? Bid : Ask;
   color arrowColor = (orderType == OP_BUY) ? clrRed : clrBlue;

   bool result = OrderClose(ticket, lots, closePrice, InpSlippage, arrowColor);

   if(result)
      Print("【平仓成功】Ticket:", ticket, " 原因:", reason);
   else
      Print("【平仓失败】错误码: ", GetLastError());

   return result;
}

//+------------------------------------------------------------------+
//| VWAP计算 (按日锚定)                                               |
//+------------------------------------------------------------------+
double GetDailyVWAP()
{
   datetime currentBarTime = iTime(NULL, PERIOD_M15, 0);
   if(g_vwapCacheBarTime == currentBarTime && g_cachedVWAP > 0)
      return g_cachedVWAP;

   // 外汇交易日: 美东17:00为分界
   int currentDay = GetForexTradingDay(currentBarTime);

   double dailyTPV = 0;
   double dailyVolume = 0;

   for(int i = 1; i <= 100; i++)
   {
      datetime barTime = iTime(NULL, PERIOD_M15, i);
      if(GetForexTradingDay(barTime) != currentDay) break;

      double typicalPrice = (iHigh(NULL, PERIOD_M15, i) +
                             iLow(NULL, PERIOD_M15, i) +
                             iClose(NULL, PERIOD_M15, i)) / 3.0;
      double vol = (double)iVolume(NULL, PERIOD_M15, i);

      dailyTPV += typicalPrice * vol;
      dailyVolume += vol;
   }

   if(dailyVolume > 0)
      g_cachedVWAP = dailyTPV / dailyVolume;
   else
      g_cachedVWAP = iClose(NULL, PERIOD_M15, 1);

   g_vwapCacheBarTime = currentBarTime;
   return g_cachedVWAP;
}

//+------------------------------------------------------------------+
//| 外汇交易日计算                                                    |
//+------------------------------------------------------------------+
int GetForexTradingDay(datetime barTime)
{
   int serverHour = TimeHour(barTime);
   int utcHour = serverHour - g_detectedDSTOffset;
   int isDST = (g_detectedDSTOffset == 3) ? 1 : 0;
   int estOffset = 5 - isDST;
   int estHour = utcHour - estOffset;

   datetime estDate = barTime;
   if(estHour < 0)
   {
      estDate = barTime - 86400;
      estHour += 24;
   }
   else if(estHour >= 24)
   {
      estDate = barTime + 86400;
      estHour -= 24;
   }

   int estTotalMinutes = estHour * 60 + TimeMinute(barTime);
   if(estTotalMinutes < 17 * 60)
      estDate = estDate - 86400;

   return TimeYear(estDate) * 1000 + TimeDayOfYear(estDate);
}

//+------------------------------------------------------------------+
//| 时段判断                                                          |
//+------------------------------------------------------------------+
bool IsAsianSession()
{
   int serverHour = TimeHour(TimeCurrent());
   int beijingHour = serverHour + (8 - g_detectedDSTOffset);
   if(beijingHour >= 24) beijingHour -= 24;
   if(beijingHour < 0) beijingHour += 24;

   return (beijingHour >= InpAsianStartBJ && beijingHour < InpAsianEndBJ);
}

bool IsEuropeanSession()
{
   int serverHour = TimeHour(TimeCurrent());
   int beijingHour = serverHour + (8 - g_detectedDSTOffset);
   if(beijingHour >= 24) beijingHour -= 24;
   if(beijingHour < 0) beijingHour += 24;

   if(InpEuropeanEndBJ == 0)
      return (beijingHour >= InpEuropeanStartBJ);
   else
      return (beijingHour >= InpEuropeanStartBJ || beijingHour < InpEuropeanEndBJ);
}

//+------------------------------------------------------------------+
//| 追踪止损管理                                                      |
//+------------------------------------------------------------------+
void RemoveTrailingStopTracker(int ticket)
{
   for(int i = 0; i < g_trailingStopCount; i++)
   {
      if(g_trailingStopTickets[i] == ticket)
      {
         g_trailingStopTickets[i] = g_trailingStopTickets[g_trailingStopCount - 1];
         g_trailingStopCount--;
         return;
      }
   }
}

void CleanupTrailingStopTrackers()
{
   for(int i = g_trailingStopCount - 1; i >= 0; i--)
   {
      if(!OrderSelect(g_trailingStopTickets[i], SELECT_BY_TICKET))
      {
         RemoveTrailingStopTracker(g_trailingStopTickets[i]);
      }
   }
}
//+------------------------------------------------------------------+
