//+------------------------------------------------------------------+
//| XAUUSD Momentum Breakout Strategy - MQL4                         |
//|                                                                  |
//| 策略B - 动量突破 (欧美盘 15:00-00:00 北京时间)                     |
//| 核心逻辑: 布林带突破 + EMA趋势确认 + 追踪止损                      |
//+------------------------------------------------------------------+

//+------------------------------------------------------------------+
//| 策略B输入参数                                                      |
//+------------------------------------------------------------------+
input int    InpEMAFastB = 20;           // 快速EMA周期
input int    InpEMASlowB = 50;           // 慢速EMA周期
input int    InpKCPeriod = 20;           // 肯特纳通道周期
input double InpKCATRMult = 1.5;         // 肯特纳通道ATR倍数
input double InpSLATRMultB = 1.2;        // 止损ATR倍数
input double InpTrailingATRMultB = 2.5;  // 追踪止损ATR倍数
input double InpSqueezeThreshold = 0.8;  // 波动率挤压阈值

//+------------------------------------------------------------------+
//| 策略B状态变量                                                      |
//+------------------------------------------------------------------+
var int g_strategyBBarsHeld = 0;
var double g_strategyBEntryPrice = 0.0;
var double g_strategyBFixedStopLoss = 0.0;

int g_pendingOrderTicket = 0;
double g_pendingStopLoss = 0;

//+------------------------------------------------------------------+
//| 策略B入场检查 (与Python逻辑一致)                                   |
//| Python: prev_close <= prev_bb_upper && close > bb_upper && ema_bullish |
//+------------------------------------------------------------------+
void CheckStrategyBEntry(double close, double bbUpper, double bbLower,
                         double emaFast, double emaSlow, double atr,
                         double high, double low, bool isEuropeanSession,
                         bool hasPositionB, int bbPeriod, double bbStd)
{
   if(!isEuropeanSession || hasPositionB || g_pendingOrderTicket != 0) return;

   double currentRange = high - low;
   if(atr > 0 && currentRange > atr * 2.0) return;

   // 获取前一K线数据用于突破判断 (与Python一致)
   double prevClose = iClose(NULL, PERIOD_M15, 2);
   double prevBBUpper = iBands(NULL, PERIOD_M15, bbPeriod, 0, bbStd, PRICE_CLOSE, MODE_UPPER, 2);
   double prevBBLower = iBands(NULL, PERIOD_M15, bbPeriod, 0, bbStd, PRICE_CLOSE, MODE_LOWER, 2);
   double prevLow = iLow(NULL, PERIOD_M15, 2);
   double prevHigh = iHigh(NULL, PERIOD_M15, 2);

   bool emaBullish = emaFast > emaSlow * 1.0005;
   bool emaBearish = emaFast < emaSlow * 0.9995;

   // 做多条件: 前一根K线收盘 <= 前一根上轨 且 当前K线收盘 > 当前上轨 且 EMA多头
   if(prevClose <= prevBBUpper && close > bbUpper && emaBullish)
   {
      double entryPrice = high;
      double sl = MathMax(entryPrice - InpSLATRMultB * atr, prevLow);

      int ticket = SendStrategyBBuyStop(entryPrice, sl);
      if(ticket > 0)
      {
         g_pendingOrderTicket = ticket;
         g_pendingStopLoss = sl;
      }
      return;
   }

   // 做空条件: 前一根K线收盘 >= 前一根下轨 且 当前K线收盘 < 当前下轨 且 EMA空头
   if(prevClose >= prevBBLower && close < bbLower && emaBearish)
   {
      double entryPrice = low;
      double sl = MathMin(entryPrice + InpSLATRMultB * atr, prevHigh);

      int ticket = SendStrategyBSellStop(entryPrice, sl);
      if(ticket > 0)
      {
         g_pendingOrderTicket = ticket;
         g_pendingStopLoss = sl;
      }
   }
}

//+------------------------------------------------------------------+
//| 策略B出场检查                                                      |
//+------------------------------------------------------------------+
void CheckExitStrategyB(int ticket, double atr)
{
   if(!OrderSelect(ticket, SELECT_BY_TICKET)) return;

   int orderType = OrderType();
   double positionSL = OrderStopLoss();
   double openPrice = OrderOpenPrice();
   datetime openTime = OrderOpenTime();

   // 使用iHighest/iLowest优化性能 (O(1) vs O(n))
   int startBar = iBarShift(NULL, PERIOD_M15, openTime);
   int barsSinceEntry = startBar + 1;

   int highestIdx = iHighest(NULL, PERIOD_M15, MODE_HIGH, barsSinceEntry, 0);
   int lowestIdx = iLowest(NULL, PERIOD_M15, MODE_LOW, barsSinceEntry, 0);

   double highestPrice = (highestIdx >= 0) ? iHigh(NULL, PERIOD_M15, highestIdx) : 0;
   double lowestPrice = (lowestIdx >= 0) ? iLow(NULL, PERIOD_M15, lowestIdx) : DBL_MAX;

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
      CloseStrategyBPosition(ticket, reason);
}

//+------------------------------------------------------------------+
//| 策略B挂单管理                                                      |
//+------------------------------------------------------------------+
void ManageStrategyBPendingOrders()
{
   if(g_pendingOrderTicket == 0) return;

   if(!OrderSelect(g_pendingOrderTicket, SELECT_BY_TICKET))
   {
      ResetStrategyBPendingState();
      return;
   }

   int orderType = OrderType();
   if(orderType == OP_BUY || orderType == OP_SELL)
   {
      ResetStrategyBPendingState();
      return;
   }

   datetime openTime = OrderOpenTime();
   if(TimeCurrent() - openTime > 4 * 3600)
   {
      OrderDelete(g_pendingOrderTicket);
      ResetStrategyBPendingState();
   }
}

void ResetStrategyBPendingState()
{
   g_pendingOrderTicket = 0;
   g_pendingStopLoss = 0;
}

//+------------------------------------------------------------------+
//| 策略B挂单函数 (由主程序实现)                                        |
//+------------------------------------------------------------------+
int SendStrategyBBuyStop(double triggerPrice, double stopLoss);
int SendStrategyBSellStop(double triggerPrice, double stopLoss);
bool CloseStrategyBPosition(int ticket, string reason);
