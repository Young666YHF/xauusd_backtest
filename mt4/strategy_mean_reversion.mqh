//+------------------------------------------------------------------+
//| XAUUSD Mean Reversion Strategy - MQL4                            |
//|                                                                  |
//| 策略A - 均值回归 (亚盘 06:00-14:00 北京时间)                       |
//| 核心逻辑: RSI超卖+布林带下轨做多, RSI超买+布林带上轨做空            |
//+------------------------------------------------------------------+

//+------------------------------------------------------------------+
//| 策略A输入参数                                                      |
//+------------------------------------------------------------------+
input int    InpBBPeriod = 20;           // 布林带周期
input double InpBBStd = 2.0;             // 布林带标准差倍数
input int    InpRSIPeriod = 14;          // RSI周期
input int    InpRSIOversold = 25;        // RSI超卖阈值
input int    InpRSIOverbought = 75;      // RSI超买阈值
input double InpSLATRMultA = 1.0;        // 止损ATR倍数
input int    InpMaxHoldBarsA = 5;        // 最大持仓K线数

//+------------------------------------------------------------------+
//| 策略A状态变量                                                      |
//+------------------------------------------------------------------+
var int g_strategyABarsHeld = 0;
var double g_strategyAEntryPrice = 0.0;
var double g_strategyAFixedStopLoss = 0.0;

//+------------------------------------------------------------------+
//| 策略A入场检查 (与Python逻辑一致)                                   |
//| Python逻辑: prev_close <= bb_lower && prev_rsi <= oversold && rsi > prev_rsi |
//+------------------------------------------------------------------+
void CheckStrategyAEntry(double close, double bbUpper, double bbLower,
                         double rsi, double atr, double high, double low,
                         double vwap, bool isAsianSession,
                         bool hasPositionA, int &positionTicketsA[], int &countA)
{
   if(!isAsianSession || hasPositionA) return;

   double currentRange = high - low;
   if(atr > 0 && currentRange > atr * 2.0) return; // 异常波动过滤

   // 获取前一K线的RSI用于回升确认
   double rsiPrev = iRSI(NULL, PERIOD_M15, InpRSIPeriod, PRICE_CLOSE, 2);

   // 做多条件: 前一根K线触及布林带下轨 + RSI超卖 + 当前RSI回升
   if(close <= bbLower && rsiPrev <= InpRSIOversold && rsi > rsiPrev)
   {
      double sl = close - InpSLATRMultA * atr;
      double tp = vwap > close ? vwap : close + MathAbs(close - sl) * 2.0;

      if(OpenStrategyAPosition(OP_BUY, sl, tp))
      {
         g_strategyABarsHeld = 0;
         g_strategyAEntryPrice = close;
         g_strategyAFixedStopLoss = sl;
         if(countA < ArraySize(positionTicketsA))
            positionTicketsA[countA++] = GetLastTicket();
      }
      return;
   }

   // 做空条件: 前一根K线触及布林带上轨 + RSI超买 + 当前RSI回落
   if(close >= bbUpper && rsiPrev >= InpRSIOverbought && rsi < rsiPrev)
   {
      double sl = close + InpSLATRMultA * atr;
      double tp = vwap < close ? vwap : close - MathAbs(close - sl) * 2.0;

      if(OpenStrategyAPosition(OP_SELL, sl, tp))
      {
         g_strategyABarsHeld = 0;
         g_strategyAEntryPrice = close;
         g_strategyAFixedStopLoss = sl;
         if(countA < ArraySize(positionTicketsA))
            positionTicketsA[countA++] = GetLastTicket();
      }
   }
}

//+------------------------------------------------------------------+
//| 策略A出场检查                                                      |
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
      CloseStrategyAPosition(ticket, reason);
}

//+------------------------------------------------------------------+
//| 策略A开平仓函数 (由主程序实现)                                      |
//+------------------------------------------------------------------+
bool OpenStrategyAPosition(int orderType, double sl, double tp);
bool CloseStrategyAPosition(int ticket, string reason);
int GetLastTicket();
