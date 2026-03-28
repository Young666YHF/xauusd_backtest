//+------------------------------------------------------------------+
//| XAUUSD Dollar Trader Martingale BBW Step EA                      |
//|                                                                  |
//| 策略: 三线SMA趋势跟踪 (20/50/200) + BBW过滤 + 阶梯式马丁        |
//|                                                                  |
//| 核心逻辑:                                                        |
//|   - 入场: SMA排列 + BBW > MA(BBW,50)                            |
//|   - BBW = (Upper - Lower) / Middle * 100                        |
//|   - 阶梯式马丁: 亏2次→阶梯+1, 盈1次→阶梯-1                      |
//|   - 最大层数继续亏损→超调计数                                   |
//|                                                                  |
//| 版本: 2.0.0                                                      |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, XAUUSD Dollar Trader Martingale BBW"
#property link      ""
#property version   "2.00"
#property strict

//+------------------------------------------------------------------+
//| 输入参数 (SMA设置)                                                |
//+------------------------------------------------------------------+
input int    InpSMAShort = 20;           // 短期SMA周期
input int    InpSMAMedium = 50;          // 中期SMA周期
input int    InpSMALong = 200;           // 长期SMA周期

//+------------------------------------------------------------------+
//| 输入参数 (布林带设置)                                             |
//+------------------------------------------------------------------+
input int    InpBBPeriod = 20;           // 布林带周期
input double InpBBStd = 2.0;             // 布林带标准差
input int    InpBBWMaPeriod = 50;        // BBW均线周期

//+------------------------------------------------------------------+
//| 输入参数 (阶梯式马丁设置)                                         |
//+------------------------------------------------------------------+
input double InpLotSize = 0.01;          // 基础仓位
input double InpMartingaleMult = 2.0;    // 马丁倍数
input int    InpMaxMartingaleSteps = 5;  // 最大阶梯层级
input bool   InpEnableOvershoot = true;  // 启用超调计数
input bool   InpEnableUndershoot = true; // 启用欠调计数

//+------------------------------------------------------------------+
//| 输入参数 (交易设置)                                               |
//+------------------------------------------------------------------+
input int    InpSlippage = 30;           // 滑点
input int    InpMagicNumber = 20260327;  // 魔术数字
input string InpTradeComment = "DollarTrader_Martingale_BBW";  // 交易注释
input double InpMaxSpread = 50.0;        // 最大允许点差

//+------------------------------------------------------------------+
//| 全局变量                                                          |
//+------------------------------------------------------------------+
// 持仓状态
int    g_currentPosition = 0;            // 0=无, 1=多头, -1=空头

// 阶梯式马丁状态
int    g_martingaleStep = 0;             // 当前阶梯层级
int    g_lossCountInStep = 0;            // 当前阶梯下连续亏损次数
int    g_overshootCount = 0;             // 超调计数
int    g_undershootCount = 0;            // 欠调计数
double g_currentLotSize = 0;             // 当前实际仓位
datetime g_lastTradeCloseTime = 0;       // 上次交易关闭时间

//+------------------------------------------------------------------+
//| EA初始化                                                          |
//+------------------------------------------------------------------+
int OnInit()
{
   Print("=== XAUUSD Dollar Trader Martingale BBW Step EA v2.0 ===");
   Print("基础仓位: ", DoubleToString(InpLotSize, 2));
   Print("马丁倍数: ", DoubleToString(InpMartingaleMult, 1));
   Print("最大阶梯层级: ", InpMaxMartingaleSteps);
   Print("BBW均线周期: ", InpBBWMaPeriod);

   // 初始化当前仓位
   g_currentLotSize = InpLotSize;

   // 恢复可能的历史状态
   RecoverMartingaleState();

   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| EA反初始化                                                        |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   Print("=== Dollar Trader Martingale BBW EA 停止 ===");
   Print("最终马丁阶梯: ", g_martingaleStep);
   Print("超调计数: ", g_overshootCount);
}

//+------------------------------------------------------------------+
//| 计算布林带宽度 (BBW)                                              |
//+------------------------------------------------------------------+
double CalculateBBW(int shift)
{
   double bbUpper = iBands(NULL, PERIOD_CURRENT, InpBBPeriod, InpBBStd, 0, PRICE_CLOSE, MODE_UPPER, shift);
   double bbLower = iBands(NULL, PERIOD_CURRENT, InpBBPeriod, InpBBStd, 0, PRICE_CLOSE, MODE_LOWER, shift);
   double bbMiddle = iBands(NULL, PERIOD_CURRENT, InpBBPeriod, InpBBStd, 0, PRICE_CLOSE, MODE_MAIN, shift);

   if(bbMiddle == 0) return 0;

   double bbw = (bbUpper - bbLower) / bbMiddle * 100;
   return bbw;
}

//+------------------------------------------------------------------+
//| 计算BBW均线                                                       |
//+------------------------------------------------------------------+
double CalculateBBWMa(int period, int shift)
{
   double sum = 0;
   int count = 0;

   for(int i = shift; i < shift + period && i < 1000; i++)
   {
      double bbw = CalculateBBW(i);
      if(bbw > 0)
      {
         sum += bbw;
         count++;
      }
   }

   if(count == 0) return 0;
   return sum / count;
}

//+------------------------------------------------------------------+
//| 计算当前阶梯式马丁仓位                                            |
//+------------------------------------------------------------------+
double CalculateMartingaleLotSize()
{
   double lotSize = InpLotSize;

   // 计算仓位: base * multiplier^step
   for(int i = 0; i < g_martingaleStep; i++)
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
//| 更新阶梯式马丁状态                                                |
//+------------------------------------------------------------------+
void UpdateMartingaleState(double profit)
{
   int maxSteps = InpMaxMartingaleSteps;

   if(profit < 0)
   {
      // ========== 亏损处理 ==========
      g_lossCountInStep++;

      if(g_lossCountInStep >= 2)
      {
         // 需要上升阶梯
         if(g_martingaleStep < maxSteps)
         {
            // 正常上升
            g_martingaleStep++;
            g_lossCountInStep = 0;
            // 如果启用欠调计数且有欠调计数，消耗一个
            if(InpEnableUndershoot && g_undershootCount > 0)
               g_undershootCount--;

            Print("【阶梯马丁】亏损2次，阶梯上升: ", g_martingaleStep);
         }
         else
         {
            // 已经在最大层数
            if(InpEnableOvershoot)
            {
               // 启用超调计数，累积超调计数
               g_overshootCount++;
               g_lossCountInStep = 0;
               Print("【阶梯马丁】最大层数继续亏损，超调计数: ", g_overshootCount);
            }
            // 如果未启用超调，保持当前状态
         }
      }
   }
   else
   {
      // ========== 盈利处理 ==========
      g_lossCountInStep = 0;

      if(InpEnableOvershoot && g_overshootCount > 0)
      {
         // 有超调计数且启用，先消耗计数（不降阶梯）
         g_overshootCount--;
         Print("【阶梯马丁】盈利，消耗超调计数，保持阶梯: ", g_martingaleStep);
      }
      else if(g_martingaleStep > 0)
      {
         // 正常下降阶梯
         g_martingaleStep--;
         Print("【阶梯马丁】盈利，阶梯下降: ", g_martingaleStep);
      }
      else
      {
         // 已经在0层
         if(InpEnableUndershoot)
         {
            // 启用欠调计数，累积欠调计数
            g_undershootCount++;
            Print("【阶梯马丁】0层继续盈利，欠调计数: ", g_undershootCount);
         }
         // 如果未启用欠调，不做任何操作
      }
   }

   // 重新计算仓位
   g_currentLotSize = CalculateMartingaleLotSize();

   Print("【阶梯马丁】当前仓位: ", DoubleToString(g_currentLotSize, 2),
         " 阶梯: ", g_martingaleStep);
}

//+------------------------------------------------------------------+
//| 恢复马丁格尔状态 (从历史订单)                                     |
//+------------------------------------------------------------------+
void RecoverMartingaleState()
{
   // 查找最近的历史订单来确定当前状态
   int totalHistory = OrdersHistoryTotal();
   int consecutiveLosses = 0;

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
               // 盈利，恢复完成
               break;
            }
            else
            {
               // 亏损，增加计数
               consecutiveLosses++;
            }

            g_lastTradeCloseTime = OrderCloseTime();
         }
      }
   }

   // 根据连续亏损次数恢复阶梯
   // 简化处理：每2次亏损=1个阶梯
   g_martingaleStep = MathMin(consecutiveLosses / 2, InpMaxMartingaleSteps);
   g_currentLotSize = CalculateMartingaleLotSize();

   Print("恢复状态 - 连续亏损: ", consecutiveLosses,
         " 恢复阶梯: ", g_martingaleStep,
         " 当前仓位: ", DoubleToString(g_currentLotSize, 2));
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

   // === BBW波动率判断 (入场过滤) ===
   double bbw = CalculateBBW(1);
   double bbwMa = CalculateBBWMa(InpBBWMaPeriod, 1);
   bool bbwAllowEntry = (bbw > 0) && (bbwMa > 0) && (bbw > bbwMa);

   // === 出场逻辑 ===
   if(hasLong && smaBearishCross)
   {
      ClosePosition(ticketLong, "SMA死叉");
      hasLong = false;
      g_currentPosition = 0;

      if(!isBearish)
         return;
   }

   if(hasShort && smaBullishCross)
   {
      ClosePosition(ticketShort, "SMA金叉");
      hasShort = false;
      g_currentPosition = 0;

      if(!isBullish)
         return;
   }

   // === 入场逻辑 (仅在新K线时，带BBW过滤) ===
   if(newBar)
   {
      // 多头入场
      if(!hasLong && !hasShort && isBullish && bbwAllowEntry)
      {
         string comment = "多头排列_S" + IntegerToString(g_martingaleStep);
         OpenPosition(OP_BUY, comment);
      }
      // 空头入场
      else if(!hasLong && !hasShort && isBearish && bbwAllowEntry)
      {
         string comment = "空头排列_S" + IntegerToString(g_martingaleStep);
         OpenPosition(OP_SELL, comment);
      }
      // 反向 - 多转空 (需要BBW允许)
      else if(hasLong && isBearish && smaBearishCross && bbwAllowEntry)
      {
         string comment = "多转空_S" + IntegerToString(g_martingaleStep);
         OpenPosition(OP_SELL, comment);
      }
      // 反向 - 空转多 (需要BBW允许)
      else if(hasShort && isBullish && smaBullishCross && bbwAllowEntry)
      {
         string comment = "空转多_S" + IntegerToString(g_martingaleStep);
         OpenPosition(OP_BUY, comment);
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

   // 使用阶梯式马丁计算后的仓位
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
         " 阶梯:", g_martingaleStep);

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
   }
   else
   {
      Print("【平仓失败】错误码: ", GetLastError());
   }

   return result;
}
//+------------------------------------------------------------------+
