//+------------------------------------------------------------------+
//| XAUUSD Dollar Trader Martingale EA                               |
//|                                                                  |
//| 策略: 三线SMA趋势跟踪 (20/50/200) + 马丁格尔仓位管理              |
//|                                                                  |
//| 核心逻辑:                                                        |
//|   - 多头开仓: C > SMA_20 > SMA_50 > SMA_200                      |
//|   - 空头开仓: C < SMA_20 < SMA_50 < SMA_200                      |
//|   - 多头平仓: SMA_20 < SMA_50 (死叉)                             |
//|   - 空头平仓: SMA_20 > SMA_50 (金叉)                             |
//|                                                                  |
//| 马丁格尔特性:                                                    |
//|   - 基础仓位: InpLotSize                                         |
//|   - 亏损后翻倍: 第N次交易仓位 = InpLotSize * multiplier^(N-1)    |
//|   - 盈利后重置: 回到基础仓位                                     |
//|   - 最大连续亏损次数限制: InpMaxMartingaleSteps                  |
//|                                                                  |
//| 版本: 1.0.0                                                      |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, XAUUSD Dollar Trader Martingale"
#property link      ""
#property version   "1.00"
#property strict

//+------------------------------------------------------------------+
//| 输入参数 (SMA设置)                                                |
//+------------------------------------------------------------------+
input int    InpSMAShort = 20;           // 短期SMA周期
input int    InpSMAMedium = 50;          // 中期SMA周期
input int    InpSMALong = 200;           // 长期SMA周期

//+------------------------------------------------------------------+
//| 输入参数 (马丁格尔设置)                                           |
//+------------------------------------------------------------------+
input double InpLotSize = 1.0;           // 基础仓位
input double InpMartingaleMult = 2.0;    // 马丁格尔倍数 (可配置)
input int    InpMaxMartingaleSteps = 5;  // 最大连续翻倍次数

//+------------------------------------------------------------------+
//| 输入参数 (交易设置)                                               |
//+------------------------------------------------------------------+
input int    InpSlippage = 30;           // 滑点
input int    InpMagicNumber = 20260325;  // 魔术数字
input string InpTradeComment = "DollarTrader_Martingale";  // 交易注释
input double InpMaxSpread = 50.0;        // 最大允许点差

//+------------------------------------------------------------------+
//| 全局变量                                                          |
//+------------------------------------------------------------------+
// 持仓状态
int    g_currentPosition = 0;            // 0=无, 1=多头, -1=空头

// 马丁格尔状态
int    g_consecutiveLosses = 0;          // 连续亏损次数
double g_currentLotSize = 0;             // 当前实际仓位
datetime g_lastTradeCloseTime = 0;       // 上次交易关闭时间

//+------------------------------------------------------------------+
//| EA初始化                                                          |
//+------------------------------------------------------------------+
int OnInit()
{
   Print("=== XAUUSD Dollar Trader Martingale EA v1.0 ===");
   Print("基础仓位: ", DoubleToString(InpLotSize, 2));
   Print("马丁格尔倍数: ", DoubleToString(InpMartingaleMult, 1));
   Print("最大翻倍次数: ", InpMaxMartingaleSteps);

   // 初始化当前仓位
   g_currentLotSize = CalculateMartingaleLotSize();

   // 恢复可能的历史状态
   RecoverMartingaleState();

   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| EA反初始化                                                        |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   Print("=== Dollar Trader Martingale EA 停止 ===");
   Print("最终马丁层级: ", g_consecutiveLosses);
}

//+------------------------------------------------------------------+
//| 计算马丁格尔仓位                                                  |
//+------------------------------------------------------------------+
double CalculateMartingaleLotSize()
{
   double lotSize = InpLotSize;

   // 限制最大翻倍次数
   int effectiveLosses = MathMin(g_consecutiveLosses, InpMaxMartingaleSteps);

   // 计算仓位: base * multiplier^losses
   for(int i = 0; i < effectiveLosses; i++)
   {
      lotSize *= InpMartingaleMult;
   }

   // 规范化手数
   double minLot = MarketInfo(Symbol(), MODE_MINLOT);
   double maxLot = MarketInfo(Symbol(), MODE_MAXLOT);
   double lotStep = MarketInfo(Symbol(), MODE_LOTSTEP);

   if(lotStep > 0)
      lotSize = NormalizeDouble(MathFloor(lotSize / lotStep + 0.00001) * lotStep, 2);

   lotSize = MathMax(minLot, MathMin(maxLot, lotSize));

   return lotSize;
}

//+------------------------------------------------------------------+
//| 恢复马丁格尔状态 (从历史订单)                                     |
//+------------------------------------------------------------------+
void RecoverMartingaleState()
{
   // 查找最近的历史订单来确定当前状态
   int totalHistory = OrdersHistoryTotal();

   for(int i = totalHistory - 1; i >= 0; i--)
   {
      if(OrderSelect(i, SELECT_BY_POS, MODE_HISTORY))
      {
         if(OrderSymbol() == Symbol() && OrderMagicNumber() == InpMagicNumber)
         {
            // 找到本EA的订单
            double profit = OrderProfit() + OrderSwap() + OrderCommission();

            if(profit > 0)
            {
               g_consecutiveLosses = 0;
            }
            else
            {
               g_consecutiveLosses++;
            }

            g_currentLotSize = CalculateMartingaleLotSize();
            g_lastTradeCloseTime = OrderCloseTime();

            Print("恢复状态 - 连续亏损: ", g_consecutiveLosses,
                  " 当前仓位: ", DoubleToString(g_currentLotSize, 2));
            break;
         }
      }
   }
}

//+------------------------------------------------------------------+
//| 更新马丁格尔状态 (交易完成后调用)                                 |
//+------------------------------------------------------------------+
void UpdateMartingaleState(double profit)
{
   if(profit > 0)
   {
      // 盈利: 重置
      if(g_consecutiveLosses > 0)
      {
         Print("【马丁格尔】盈利 ", DoubleToString(profit, 2),
               ", 重置仓位从 ", g_consecutiveLosses, " 到 0");
         g_consecutiveLosses = 0;
      }
   }
   else
   {
      // 亏损: 增加层级
      g_consecutiveLosses++;
      Print("【马丁格尔】亏损 ", DoubleToString(profit, 2),
            ", 仓位层级升至: ", g_consecutiveLosses);
   }

   // 重新计算仓位
   g_currentLotSize = CalculateMartingaleLotSize();

   Print("【马丁格尔】当前仓位: ", DoubleToString(g_currentLotSize, 2));
}

//+------------------------------------------------------------------+
//| 检查并处理已平仓订单                                              |
//+------------------------------------------------------------------+
void CheckClosedTrades()
{
   // 遍历历史订单，查找新关闭的订单
   int totalHistory = OrdersHistoryTotal();
   static int lastHistoryCount = 0;

   if(totalHistory > lastHistoryCount)
   {
      // 有新的历史订单
      for(int i = totalHistory - 1; i >= lastHistoryCount; i--)
      {
         if(OrderSelect(i, SELECT_BY_POS, MODE_HISTORY))
         {
            if(OrderSymbol() == Symbol() && OrderMagicNumber() == InpMagicNumber)
            {
               // 计算盈亏
               double profit = OrderProfit() + OrderSwap() + OrderCommission();

               Print("【交易完成】Ticket: ", OrderTicket(),
                     " 盈亏: ", DoubleToString(profit, 2));

               // 更新马丁格尔状态
               UpdateMartingaleState(profit);
            }
         }
      }

      lastHistoryCount = totalHistory;
   }
   else if(totalHistory < lastHistoryCount)
   {
      // 历史记录被重置或清理
      lastHistoryCount = totalHistory;
   }
}

//+------------------------------------------------------------------+
//| 每个Tick处理                                                      |
//+------------------------------------------------------------------+
void OnTick()
{
   // 点差过滤
   double currentSpread = MarketInfo(Symbol(), MODE_SPREAD);
   if(currentSpread > InpMaxSpread) return;

   // 检查已平仓交易并更新马丁格尔状态
   CheckClosedTrades();

   // 检查新K线
   static datetime lastBarTime = 0;
   datetime currentBarTime = iTime(NULL, PERIOD_CURRENT, 0);
   bool newBar = (currentBarTime != lastBarTime);

   // 获取当前持仓
   bool hasLong = false;
   bool hasShort = false;
   int ticketLong = 0;
   int ticketShort = 0;

   int totalOrders = OrdersTotal();
   for(int i = totalOrders - 1; i >= 0; i--)
   {
      if(OrderSelect(i, SELECT_BY_POS, MODE_TRADES))
      {
         if(OrderSymbol() == Symbol() && OrderMagicNumber() == InpMagicNumber)
         {
            int orderType = OrderType();
            if(orderType == OP_BUY)
            {
               hasLong = true;
               ticketLong = OrderTicket();
            }
            else if(orderType == OP_SELL)
            {
               hasShort = true;
               ticketShort = OrderTicket();
            }
         }
      }
   }

   // 更新当前持仓状态
   if(hasLong) g_currentPosition = 1;
   else if(hasShort) g_currentPosition = -1;
   else g_currentPosition = 0;

   // 获取指标值 (使用索引1 - 已收盘K线)
   double smaShort = iMA(NULL, PERIOD_CURRENT, InpSMAShort, 0, MODE_SMA, PRICE_CLOSE, 1);
   double smaMedium = iMA(NULL, PERIOD_CURRENT, InpSMAMedium, 0, MODE_SMA, PRICE_CLOSE, 1);
   double smaLong = iMA(NULL, PERIOD_CURRENT, InpSMALong, 0, MODE_SMA, PRICE_CLOSE, 1);
   double close = iClose(NULL, PERIOD_CURRENT, 1);

   // 前两根K线用于判断交叉
   double smaShortPrev2 = iMA(NULL, PERIOD_CURRENT, InpSMAShort, 0, MODE_SMA, PRICE_CLOSE, 2);
   double smaMediumPrev2 = iMA(NULL, PERIOD_CURRENT, InpSMAMedium, 0, MODE_SMA, PRICE_CLOSE, 2);

   // 检查指标有效性
   if(smaShort == 0 || smaMedium == 0 || smaLong == 0) return;

   // === 趋势判断 (基于上一根已收盘K线) ===
   bool isBullish = (close > smaShort) && (smaShort > smaMedium) && (smaMedium > smaLong);
   bool isBearish = (close < smaShort) && (smaShort < smaMedium) && (smaMedium < smaLong);

   // === 交叉判断 (用于出场) ===
   bool smaBearishCross = (smaShortPrev2 >= smaMediumPrev2) && (smaShort < smaMedium);
   bool smaBullishCross = (smaShortPrev2 <= smaMediumPrev2) && (smaShort > smaMedium);

   // === 出场逻辑 ===
   if(hasLong && smaBearishCross)
   {
      ClosePosition(ticketLong, "SMA死叉");
      hasLong = false;
      g_currentPosition = 0;

      // 如果趋势转空，标记为可开空仓
      if(!isBearish)
         return; // 不平仓后立即开仓，等待下一根K线
   }

   if(hasShort && smaBullishCross)
   {
      ClosePosition(ticketShort, "SMA金叉");
      hasShort = false;
      g_currentPosition = 0;

      // 如果趋势转多，标记为可开多仓
      if(!isBullish)
         return; // 不平仓后立即开仓，等待下一根K线
   }

   // === 入场逻辑 (仅在新K线时) ===
   if(newBar)
   {
      // 多头入场
      if(!hasLong && !hasShort && isBullish)
      {
         OpenPosition(OP_BUY, "多头排列_M" + IntegerToString(g_consecutiveLosses));
      }
      // 空头入场
      else if(!hasLong && !hasShort && isBearish)
      {
         OpenPosition(OP_SELL, "空头排列_M" + IntegerToString(g_consecutiveLosses));
      }
      // 反向 - 多转空
      else if(hasLong && isBearish && smaBearishCross)
      {
         OpenPosition(OP_SELL, "多转空_M" + IntegerToString(g_consecutiveLosses));
      }
      // 反向 - 空转多
      else if(hasShort && isBullish && smaBullishCross)
      {
         OpenPosition(OP_BUY, "空转多_M" + IntegerToString(g_consecutiveLosses));
      }
   }

   if(newBar) lastBarTime = currentBarTime;
}

//+------------------------------------------------------------------+
//| 开仓函数                                                          |
//+------------------------------------------------------------------+
bool OpenPosition(int orderType, string comment)
{
   double price = (orderType == OP_BUY) ? Ask : Bid;
   color arrowColor = (orderType == OP_BUY) ? clrBlue : clrRed;

   // 使用马丁格尔计算后的仓位
   double lotSize = g_currentLotSize;

   int ticket = OrderSend(
      Symbol(),
      orderType,
      lotSize,
      price,
      InpSlippage,
      0,  // 无止损
      0,  // 无止盈
      InpTradeComment + "_" + comment,
      InpMagicNumber,
      0,
      arrowColor
   );

   if(ticket < 0)
   {
      Print("【开仓失败】错误码: ", GetLastError(),
            " 手数: ", DoubleToString(lotSize, 2));
      return false;
   }

   Print("【开仓成功】Ticket:", ticket,
         " 方向:", (orderType == OP_BUY ? "多" : "空"),
         " 手数:", DoubleToString(lotSize, 2),
         " 马丁层级:", g_consecutiveLosses);

   return true;
}

//+------------------------------------------------------------------+
//| 平仓函数                                                          |
//+------------------------------------------------------------------+
bool ClosePosition(int ticket, string reason)
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
   {
      Print("【平仓成功】Ticket:", ticket, " 原因:", reason);

      // 计算盈亏并更新马丁格尔状态
      // 注意: OrderClose后需要重新查询历史订单来获取盈亏
      // 这里只是标记平仓，实际状态更新在CheckClosedTrades中处理
   }
   else
   {
      Print("【平仓失败】错误码: ", GetLastError());
   }

   return result;
}
//+------------------------------------------------------------------+
