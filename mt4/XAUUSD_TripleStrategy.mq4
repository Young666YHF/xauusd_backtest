//+------------------------------------------------------------------+
//| XAUUSD Triple Strategy EA - MQL4 Main                            |
//|                                                                  |
//| 主EA文件 - 整合三种策略:                                          |
//|   - 策略A: 均值回归 (亚盘时段)                                    |
//|   - 策略B: 动量突破 (欧美盘时段)                                  |
//|   - 策略C: 趋势角度突破 (全时段)                                  |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, XAUUSD Triple Strategy"
#property link      ""
#property version   "6.00"
#property strict

// 包含共享工具函数
#include "common_utils.mqh"

// 包含策略模块
#include "strategy_mean_reversion.mqh"
#include "strategy_momentum_breakout.mqh"
#include "strategy_trend_angle_breakout.mqh"

//+------------------------------------------------------------------+
//| EA初始化                                                          |
//+------------------------------------------------------------------+
int OnInit()
{
   Print("=== XAUUSD Triple Strategy EA v6.0 ===");
   Print("【策略A】均值回归 - 亚盘时段 RSI+BB");
   Print("【策略B】动量突破 - 欧美盘时段 EMA+BB突破");
   Print("【策略C】趋势角度突破 - 全时段 SMA角度+K线突破");

   DetectDSTOffset();
   return(INIT_SUCCEEDED);
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
   ManageStrategyBPendingOrders();

   // 检查新K线
   static datetime lastBarTime = 0;
   datetime currentBarTime = iTime(NULL, PERIOD_M15, 0);
   bool newBar = (currentBarTime != lastBarTime);

   // 获取指标值 (出场需要 - 每Tick计算)
   double atr = iATR(NULL, PERIOD_M15, InpATRPeriod, 1);
   double vwap = GetDailyVWAP();

   // 获取指标值 (入场需要 - 仅新K线计算)
   double bbUpper, bbLower, rsi, emaFast, emaSlow, smaC, smaC_prev;
   double close, close1, high, low, high1, low1;

   if(newBar)
   {
      bbUpper = iBands(NULL, PERIOD_M15, InpBBPeriod, 0, InpBBStd, PRICE_CLOSE, MODE_UPPER, 1);
      bbLower = iBands(NULL, PERIOD_M15, InpBBPeriod, 0, InpBBStd, PRICE_CLOSE, MODE_LOWER, 1);
      rsi = iRSI(NULL, PERIOD_M15, InpRSIPeriod, PRICE_CLOSE, 1);
      emaFast = iMA(NULL, PERIOD_M15, InpEMAFastB, 0, MODE_EMA, PRICE_CLOSE, 1);
      emaSlow = iMA(NULL, PERIOD_M15, InpEMASlowB, 0, MODE_EMA, PRICE_CLOSE, 1);
      smaC = iMA(NULL, PERIOD_M15, InpSMAPeriodC, 0, MODE_SMA, PRICE_CLOSE, 1);
      smaC_prev = iMA(NULL, PERIOD_M15, InpSMAPeriodC, 0, MODE_SMA, PRICE_CLOSE, 1 + InpAngleLookbackC);

      close = iClose(NULL, PERIOD_M15, 0);
      close1 = iClose(NULL, PERIOD_M15, 1);
      high = iHigh(NULL, PERIOD_M15, 0);
      low = iLow(NULL, PERIOD_M15, 0);
      high1 = iHigh(NULL, PERIOD_M15, 1);
      low1 = iLow(NULL, PERIOD_M15, 1);
   }

   // 时段判断
   bool isAsian = IsAsianSession();
   bool isEuropean = IsEuropeanSession();

   // 持仓检查
   bool hasPositionA = false, hasPositionB = false, hasPositionC = false;
   int positionTicketsA[100], positionTicketsB[100], positionTicketsC[100];
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
                  if(countA < ArraySize(positionTicketsA))
                     positionTicketsA[countA++] = ticket;
               }
               else if(StringFind(comment, "_B") >= 0)
               {
                  hasPositionB = true;
                  if(countB < ArraySize(positionTicketsB))
                     positionTicketsB[countB++] = ticket;
               }
               else if(StringFind(comment, "_C") >= 0)
               {
                  hasPositionC = true;
                  if(countC < ArraySize(positionTicketsC))
                     positionTicketsC[countC++] = ticket;
               }
            }
         }
      }
   }

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
      if(InpEnableStrategyA)
         CheckStrategyAEntry(close1, bbUpper, bbLower, rsi, atr, high1, low1,
                             vwap, isAsian, hasPositionA, positionTicketsA, countA);

      if(InpEnableStrategyB)
         CheckStrategyBEntry(close1, bbUpper, bbLower, emaFast, emaSlow, atr,
                             high1, low1, isEuropean, hasPositionB, InpBBPeriod, InpBBStd);

      if(InpEnableStrategyC)
         CheckStrategyCEntry(smaC, smaC_prev, atr, close, high, low, hasPositionC);
   }

   if(newBar) lastBarTime = currentBarTime;
}

//+------------------------------------------------------------------+
//| 策略A函数实现                                                     |
//+------------------------------------------------------------------+
bool OpenStrategyAPosition(int orderType, double sl, double tp)
{
   return OpenPosition(orderType, sl, tp, "A");
}

bool CloseStrategyAPosition(int ticket, string reason)
{
   return ClosePosition(ticket, reason);
}

//+------------------------------------------------------------------+
//| 策略B函数实现                                                     |
//+------------------------------------------------------------------+
int SendStrategyBBuyStop(double triggerPrice, double stopLoss)
{
   return SendBuyStopOrder(triggerPrice, stopLoss, "B");
}

int SendStrategyBSellStop(double triggerPrice, double stopLoss)
{
   return SendSellStopOrder(triggerPrice, stopLoss, "B");
}

bool CloseStrategyBPosition(int ticket, string reason)
{
   return ClosePosition(ticket, reason);
}

//+------------------------------------------------------------------+
//| 策略C函数实现                                                     |
//+------------------------------------------------------------------+
bool OpenStrategyCPosition(int orderType, double sl, double tp)
{
   return OpenPosition(orderType, sl, tp, "C");
}

bool CloseStrategyCPosition(int ticket, string reason)
{
   return ClosePosition(ticket, reason);
}
//+------------------------------------------------------------------+
