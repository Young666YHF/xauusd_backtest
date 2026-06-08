//+------------------------------------------------------------------+
//| XAUUSD Breakout Grid EA - Market Order Version                   |
//|                                                                  |
//| 策略: 突破网格交易（无限网格版）                                    |
//|                                                                  |
//| 核心逻辑:                                                        |
//|   - 网格间隔: 5美元                                               |
//|   - 初始仓位: 0.01手                                              |
//|   - 覆盖范围: 无限制（所有网格都监控）                              |
//|   - 入场方式: 价格突破任意网格线时市价入场                          |
//|   - 止盈: 固定5美元                                               |
//|   - 止损: 无                                                      |
//|   - 仓位平衡: 根据多空差异调整入场手数                             |
//|                                                                  |
//| 版本: 3.0.0                                                      |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, XAUUSD Breakout Grid"
#property link      ""
#property version   "3.00"
#property strict

//+------------------------------------------------------------------+
//| 输入参数                                                          |
//+------------------------------------------------------------------+
input double InpGridSpacing = 5.0;       // 网格间隔（美元）
input double InpInitialPosition = 0.01;  // 初始仓位（手）
input double InpTakeProfit = 5.0;        // 止盈距离（美元）
input double InpMaxLotMultiplier = 10.0; // 最大手数倍数（相对于初始仓位）

input int    InpSlippage = 30;           // 滑点
input int    InpMagicNumber = 20260331;  // 魔术数字
input string InpTradeComment = "BreakoutGrid";  // 交易注释
input double InpMaxSpread = 100.0;       // 最大允许点差（回测时调大）
input int    InpMaxHoldDays = 3;         // 最大持仓天数（3天后自动平仓）

//+------------------------------------------------------------------+
//| 网格级别数据结构                                                  |
//+------------------------------------------------------------------+
struct GridLevel
{
   double price;           // 网格价格
   int    levelIndex;      // 网格索引
   double longPosition;    // 多单持仓量
   double shortPosition;   // 空单持仓量
   double longEntryPrice;  // 多单入场价
   double shortEntryPrice; // 空单入场价
   datetime longEntryTime; // 多单入场时间
   datetime shortEntryTime;// 空单入场时间
   bool   longTriggered;   // 本根K线是否已触发过多单（防重复）
   bool   shortTriggered;  // 本根K线是否已触发过空单（防重复）
};

//+------------------------------------------------------------------+
//| 全局变量                                                          |
//+------------------------------------------------------------------+
GridLevel g_grids[];                     // 网格数组
int       g_maxGridLevels = 2001;        // 最大网格数量 (0-10000, step 5)
double    g_totalLongPosition = 0;       // 总多单持仓
double    g_totalShortPosition = 0;      // 总空单持仓
double    g_prevPrice = 0;               // 上一价格
int       g_currentCenterLevel = -1;     // 当前中心网格
bool      g_isInitialized = false;       // 是否已初始化

// K线跟踪
static datetime g_lastBarTime = 0;

//+------------------------------------------------------------------+
//| EA初始化                                                          |
//+------------------------------------------------------------------+
int OnInit()
{
   Print("=== XAUUSD Breakout Grid EA v3.0 (Unlimited Grid) ===");
   Print("网格间隔: ", DoubleToString(InpGridSpacing, 1), " 美元");
   Print("初始仓位: ", DoubleToString(InpInitialPosition, 2), " 手");
   Print("止盈距离: ", DoubleToString(InpTakeProfit, 1), " 美元");
   Print("最大手数倍数: ", DoubleToString(InpMaxLotMultiplier, 1));

   // 初始化网格
   InitGrids();

   // 恢复现有持仓状态
   RecoverPositions();

   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| EA反初始化                                                        |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   Print("=== Breakout Grid EA 停止 ===");
   Print("最终多单持仓: ", DoubleToString(g_totalLongPosition, 2));
   Print("最终空单持仓: ", DoubleToString(g_totalShortPosition, 2));
}

//+------------------------------------------------------------------+
//| 初始化网格                                                        |
//+------------------------------------------------------------------+
void InitGrids()
{
   ArrayResize(g_grids, g_maxGridLevels);

   for(int i = 0; i < g_maxGridLevels; i++)
   {
      g_grids[i].price = i * InpGridSpacing;
      g_grids[i].levelIndex = i;
      g_grids[i].longPosition = 0;
      g_grids[i].shortPosition = 0;
      g_grids[i].longEntryPrice = 0;
      g_grids[i].shortEntryPrice = 0;
      g_grids[i].longEntryTime = 0;
      g_grids[i].shortEntryTime = 0;
      g_grids[i].longTriggered = false;
      g_grids[i].shortTriggered = false;
   }

   Print("网格初始化完成，共 ", g_maxGridLevels, " 个网格");
}

//+------------------------------------------------------------------+
//| 恢复现有持仓                                                      |
//+------------------------------------------------------------------+
void RecoverPositions()
{
   g_totalLongPosition = 0;
   g_totalShortPosition = 0;

   int total = OrdersTotal();
   for(int i = total - 1; i >= 0; i--)
   {
      if(OrderSelect(i, SELECT_BY_POS, MODE_TRADES))
      {
         if(OrderSymbol() == Symbol() && OrderMagicNumber() == InpMagicNumber)
         {
            int type = OrderType();
            double lots = OrderLots();
            double openPrice = OrderOpenPrice();
            int level = GridLevelFromPrice(openPrice);

            if(type == OP_BUY)
            {
               g_totalLongPosition += lots;
               if(level >= 0 && level < g_maxGridLevels)
               {
                  g_grids[level].longPosition += lots;
                  g_grids[level].longEntryPrice = openPrice;
                  g_grids[level].longEntryTime = OrderOpenTime();
               }
            }
            else if(type == OP_SELL)
            {
               g_totalShortPosition += lots;
               if(level >= 0 && level < g_maxGridLevels)
               {
                  g_grids[level].shortPosition += lots;
                  g_grids[level].shortEntryPrice = openPrice;
                  g_grids[level].shortEntryTime = OrderOpenTime();
               }
            }
         }
      }
   }

   Print("恢复持仓 - 多单: ", DoubleToString(g_totalLongPosition, 2),
         " 空单: ", DoubleToString(g_totalShortPosition, 2));
}

//+------------------------------------------------------------------+
//| 从价格计算网格级别                                                |
//+------------------------------------------------------------------+
int GridLevelFromPrice(double price)
{
   return (int)MathFloor(price / InpGridSpacing);
}

//+------------------------------------------------------------------+
//| 计算入场手数（仓位平衡 + 最大限制）                                |
//+------------------------------------------------------------------+
void CalculateLotSizes(double &longLotSize, double &shortLotSize)
{
   double maxLotSize = InpInitialPosition * InpMaxLotMultiplier;

   if(g_totalShortPosition > g_totalLongPosition)
   {
      longLotSize = g_totalShortPosition - g_totalLongPosition + InpInitialPosition;
      shortLotSize = InpInitialPosition;
   }
   else if(g_totalLongPosition > g_totalShortPosition)
   {
      longLotSize = InpInitialPosition;
      shortLotSize = g_totalLongPosition - g_totalShortPosition + InpInitialPosition;
   }
   else
   {
      longLotSize = InpInitialPosition;
      shortLotSize = InpInitialPosition;
   }

   longLotSize = MathMin(longLotSize, maxLotSize);
   shortLotSize = MathMin(shortLotSize, maxLotSize);

   // 规范化手数
   double minLot = MarketInfo(Symbol(), MODE_MINLOT);
   double maxLot = MarketInfo(Symbol(), MODE_MAXLOT);
   double lotStep = MarketInfo(Symbol(), MODE_LOTSTEP);

   if(lotStep > 0)
   {
      longLotSize = NormalizeDouble(MathFloor(longLotSize / lotStep + 0.00001) * lotStep, 2);
      shortLotSize = NormalizeDouble(MathFloor(shortLotSize / lotStep + 0.00001) * lotStep, 2);
   }

   longLotSize = MathMax(minLot, MathMin(maxLot, longLotSize));
   shortLotSize = MathMax(minLot, MathMin(maxLot, shortLotSize));
}

//+------------------------------------------------------------------+
//| 初始化策略                                                        |
//+------------------------------------------------------------------+
void InitializeStrategy(double price, int centerLevel)
{
   double gridPrice = centerLevel * InpGridSpacing;

   if(price >= gridPrice)
      OpenPosition(OP_BUY, InpInitialPosition, centerLevel);
   else
      OpenPosition(OP_SELL, InpInitialPosition, centerLevel);

   g_isInitialized = true;
   g_currentCenterLevel = centerLevel;
}

//+------------------------------------------------------------------+
//| 开仓                                                              |
//+------------------------------------------------------------------+
void OpenPosition(int orderType, double lotSize, int level)
{
   double price = (orderType == OP_BUY) ? Ask : Bid;
   double tp = (orderType == OP_BUY) ? price + InpTakeProfit : price - InpTakeProfit;
   color arrowColor = (orderType == OP_BUY) ? clrBlue : clrRed;

   int ticket = OrderSend(
      Symbol(),
      orderType,
      lotSize,
      price,
      InpSlippage,
      0,
      tp,
      InpTradeComment + "_L" + IntegerToString(level),
      InpMagicNumber,
      0,
      arrowColor
   );

   if(ticket > 0)
   {
      if(orderType == OP_BUY)
      {
         g_grids[level].longPosition += lotSize;
         g_grids[level].longEntryPrice = price;
         g_grids[level].longEntryTime = Time[0];  // 使用K线时间，回测中更准确
         g_totalLongPosition += lotSize;
      }
      else
      {
         g_grids[level].shortPosition += lotSize;
         g_grids[level].shortEntryPrice = price;
         g_grids[level].shortEntryTime = Time[0];  // 使用K线时间，回测中更准确
         g_totalShortPosition += lotSize;
      }

      Print("【开仓】", (orderType == OP_BUY ? "多单" : "空单"),
            " Level:", level, " @", DoubleToString(price, 2),
            " Size:", DoubleToString(lotSize, 2));
   }
   else
   {
      Print("【开仓失败】错误:", GetLastError());
   }
}

//+------------------------------------------------------------------+
//| 检查所有网格穿越 - 核心逻辑（基于tick价格）                          |
//+------------------------------------------------------------------+
void CheckAllGridCrossings(double prevPrice, double currPrice)
{
   double longLotSize, shortLotSize;
   CalculateLotSizes(longLotSize, shortLotSize);

   // 计算需要检查的网格范围
   int minCheckLevel = MathMax(0, GridLevelFromPrice(MathMin(prevPrice, currPrice)) - 1);
   int maxCheckLevel = MathMin(g_maxGridLevels - 1, GridLevelFromPrice(MathMax(prevPrice, currPrice)) + 1);

   // 调试输出（每100个tick输出一次）
   static int tickCount = 0;
   tickCount++;
   if(tickCount % 100 == 0)
   {
      Print("【调试】Price: ", DoubleToString(prevPrice, 2), " -> ", DoubleToString(currPrice, 2),
            " Levels: ", minCheckLevel, "-", maxCheckLevel,
            " Center: ", g_currentCenterLevel);
   }

   for(int level = minCheckLevel; level <= maxCheckLevel; level++)
   {
      if(level < 0 || level >= g_maxGridLevels) continue;

      double gridPrice = g_grids[level].price;

      // 检查向上突破（多单）：prevPrice在网格下方，currPrice突破到上方
      if(g_grids[level].longPosition == 0 && !g_grids[level].longTriggered)
      {
         if(prevPrice < gridPrice && currPrice >= gridPrice)
         {
            Print("【突破检测】向上 Level:", level, " Price:", DoubleToString(currPrice, 2), " Grid:", DoubleToString(gridPrice, 2));
            OpenPosition(OP_BUY, longLotSize, level);
            g_grids[level].longTriggered = true;
         }
      }

      // 检查向下突破（空单）：prevPrice在网格上方，currPrice跌破到下方
      if(g_grids[level].shortPosition == 0 && !g_grids[level].shortTriggered)
      {
         if(prevPrice > gridPrice && currPrice <= gridPrice)
         {
            Print("【突破检测】向下 Level:", level, " Price:", DoubleToString(currPrice, 2), " Grid:", DoubleToString(gridPrice, 2));
            OpenPosition(OP_SELL, shortLotSize, level);
            g_grids[level].shortTriggered = true;
         }
      }
   }
}

//+------------------------------------------------------------------+
//| 检查止盈并更新状态                                                |
//+------------------------------------------------------------------+
void CheckTakeProfitAndUpdate()
{
   int totalHistory = OrdersHistoryTotal();
   static int lastHistoryCount = 0;

   if(totalHistory > lastHistoryCount)
   {
      for(int i = totalHistory - 1; i >= lastHistoryCount; i--)
      {
         if(OrderSelect(i, SELECT_BY_POS, MODE_HISTORY))
         {
            if(OrderSymbol() == Symbol() && OrderMagicNumber() == InpMagicNumber)
            {
               // 只处理止盈平仓的订单（MT4止盈平仓会自动添加"[tp]"到注释）
               string comment = OrderComment();
               if(StringFind(comment, "[tp]") < 0)
                  continue; // 跳过非止盈平仓（如时间平仓）

               int type = OrderType();
               double lots = OrderLots();
               double openPrice = OrderOpenPrice();
               int level = GridLevelFromPrice(openPrice);

               if(type == OP_BUY)
               {
                  if(level >= 0 && level < g_maxGridLevels)
                  {
                     g_grids[level].longPosition = MathMax(0, g_grids[level].longPosition - lots);
                     if(g_grids[level].longPosition <= 0)
                     {
                        g_grids[level].longEntryPrice = 0;
                        g_grids[level].longEntryTime = 0;
                     }
                  }
                  g_totalLongPosition = MathMax(0, g_totalLongPosition - lots);
                  Print("【止盈平仓】多单 Level:", level);
               }
               else if(type == OP_SELL)
               {
                  if(level >= 0 && level < g_maxGridLevels)
                  {
                     g_grids[level].shortPosition = MathMax(0, g_grids[level].shortPosition - lots);
                     if(g_grids[level].shortPosition <= 0)
                     {
                        g_grids[level].shortEntryPrice = 0;
                        g_grids[level].shortEntryTime = 0;
                     }
                  }
                  g_totalShortPosition = MathMax(0, g_totalShortPosition - lots);
                  Print("【止盈平仓】空单 Level:", level);
               }
            }
         }
      }
      lastHistoryCount = totalHistory;
   }
}

//+------------------------------------------------------------------+
//| 检查时间平仓（3天后自动平仓）                                      |
//+------------------------------------------------------------------+
void CheckTimeExit()
{
   datetime currentTime = Time[0]; // 使用K线时间（回测中更准确）
   int maxHoldSeconds = InpMaxHoldDays * 24 * 60 * 60; // 3天的秒数

   // 检查所有网格级别的持仓
   for(int level = 0; level < g_maxGridLevels; level++)
   {
      // 检查多单时间
      if(g_grids[level].longPosition > 0 && g_grids[level].longEntryTime > 0)
      {
         int holdTime = (int)(currentTime - g_grids[level].longEntryTime);
         // 调试输出（每100个tick检查一次）
         static int checkCount = 0;
         checkCount++;
         if(checkCount % 1000 == 0 && level == g_currentCenterLevel)
         {
            Print("【时间检查】Level:", level, " 多单持仓时间:", holdTime/3600, "小时");
         }
         if(holdTime >= maxHoldSeconds)
         {
            Print("【时间平仓触发】多单 Level:", level, " 持仓时间:", holdTime/3600, "小时");
            ClosePositionByLevel(level, OP_BUY, "时间平仓");
         }
      }

      // 检查空单时间
      if(g_grids[level].shortPosition > 0 && g_grids[level].shortEntryTime > 0)
      {
         int holdTime = (int)(currentTime - g_grids[level].shortEntryTime);
         if(holdTime >= maxHoldSeconds)
         {
            Print("【时间平仓触发】空单 Level:", level, " 持仓时间:", holdTime/3600, "小时");
            ClosePositionByLevel(level, OP_SELL, "时间平仓");
         }
      }
   }
}

//+------------------------------------------------------------------+
//| 按网格级别平仓                                                    |
//+------------------------------------------------------------------+
void ClosePositionByLevel(int level, int orderType, string comment)
{
   // 查找对应持仓
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if(OrderSelect(i, SELECT_BY_POS, MODE_TRADES))
      {
         if(OrderSymbol() == Symbol() && OrderMagicNumber() == InpMagicNumber)
         {
            int type = OrderType();
            if(type != orderType) continue;

            double openPrice = OrderOpenPrice();
            int orderLevel = GridLevelFromPrice(openPrice);
            if(orderLevel != level) continue;

            // 平仓
            double lots = OrderLots();
            color arrowColor = (type == OP_BUY) ? clrBlue : clrRed;

            int closeTicket = OrderSend(
               Symbol(),
               (type == OP_BUY) ? OP_SELL : OP_BUY,
               lots,
               (type == OP_BUY) ? Bid : Ask,
               InpSlippage,
               0,
               0,
               InpTradeComment + "_" + comment + "_L" + IntegerToString(level),
               InpMagicNumber,
               0,
               arrowColor
            );

            if(closeTicket > 0)
            {
               // 更新网格状态
               if(type == OP_BUY)
               {
                  g_grids[level].longPosition = MathMax(0, g_grids[level].longPosition - lots);
                  if(g_grids[level].longPosition <= 0)
                  {
                     g_grids[level].longEntryPrice = 0;
                     g_grids[level].longEntryTime = 0;
                  }
                  g_totalLongPosition = MathMax(0, g_totalLongPosition - lots);
                  Print("【", comment, "】多单 Level:", level, " 持仓", InpMaxHoldDays, "天");
               }
               else
               {
                  g_grids[level].shortPosition = MathMax(0, g_grids[level].shortPosition - lots);
                  if(g_grids[level].shortPosition <= 0)
                  {
                     g_grids[level].shortEntryPrice = 0;
                     g_grids[level].shortEntryTime = 0;
                  }
                  g_totalShortPosition = MathMax(0, g_totalShortPosition - lots);
                  Print("【", comment, "】空单 Level:", level, " 持仓", InpMaxHoldDays, "天");
               }
            }
            else
            {
               Print("【", comment, "失败】错误:", GetLastError());
            }
            break;
         }
      }
   }
}

//+------------------------------------------------------------------+
//| 重置触发标记（新K线开始时）                                        |
//+------------------------------------------------------------------+
void ResetTriggerFlags()
{
   for(int i = 0; i < g_maxGridLevels; i++)
   {
      g_grids[i].longTriggered = false;
      g_grids[i].shortTriggered = false;
   }
}

//+------------------------------------------------------------------+
//| 每个Tick处理                                                      |
//+------------------------------------------------------------------+
void OnTick()
{
   // 点差过滤
   if(MarketInfo(Symbol(), MODE_SPREAD) > InpMaxSpread) return;

   datetime currBarTime = iTime(Symbol(), PERIOD_CURRENT, 0);
   static datetime prevBarTime = 0;
   static double prevTickPrice = 0;
   static int tickCount = 0;

   // 获取当前价格
   double currHigh = High[0];
   double currLow = Low[0];
   double currClose = Close[0];
   double currTickPrice = (Bid + Ask) / 2;

   tickCount++;
   if(tickCount <= 5 || tickCount % 500 == 0)
   {
      Print("【OnTick】#", tickCount, " Price:", DoubleToString(currTickPrice, 2),
            " Init:", g_isInitialized, " Center:", g_currentCenterLevel);
   }

   // 检查止盈
   CheckTakeProfitAndUpdate();

   // 检查时间平仓（3天）
   CheckTimeExit();

   // 计算当前中心网格
   int centerLevel = GridLevelFromPrice(currClose);
   centerLevel = MathMax(0, MathMin(centerLevel, g_maxGridLevels - 1));

   // 初始化策略
   if(!g_isInitialized)
   {
      InitializeStrategy(currClose, centerLevel);
      g_prevPrice = currClose;
      prevBarTime = currBarTime;
      prevTickPrice = currTickPrice;
      return;
   }

   // 新K线开始时重置触发标记
   if(currBarTime != prevBarTime)
   {
      ResetTriggerFlags();
      prevBarTime = currBarTime;
   }

   // 检查网格穿越（使用tick价格实时检测）
   if(prevTickPrice > 0)
   {
      CheckAllGridCrossings(prevTickPrice, currTickPrice);
   }

   // 更新网格中心
   if(centerLevel != g_currentCenterLevel)
   {
      Print("【网格移动】从 ", g_currentCenterLevel, " 到 ", centerLevel,
            " 价格:", DoubleToString(currClose, 2));
      g_currentCenterLevel = centerLevel;
   }

   prevTickPrice = currTickPrice;
   g_prevPrice = currClose;
}
//+------------------------------------------------------------------+
