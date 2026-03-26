//+------------------------------------------------------------------+
//| XAUUSD Common Utilities - MQL4                                   |
//|                                                                  |
//| 共享工具函数: VWAP计算、时段判断、仓位管理、交易执行               |
//+------------------------------------------------------------------+

//+------------------------------------------------------------------+
//| 通用输入参数                                                       |
//+------------------------------------------------------------------+
input int    InpATRPeriod = 14;          // ATR周期
input int    InpBrokerUTCOffset = 2;     // 券商服务器UTC时区
input int    InpAsianStartBJ = 6;        // 亚盘开始小时
input int    InpAsianEndBJ = 14;         // 亚盘结束小时
input int    InpEuropeanStartBJ = 15;    // 欧美盘开始小时
input int    InpEuropeanEndBJ = 2;       // 欧美盘结束小时
input double InpMaxSpread = 50.0;        // 最大允许点差

input double InpLotSize = 1.0;           // 交易手数
input int    InpSlippage = 30;           // 滑点
input int    InpMagicNumber = 20260324;  // 魔术数字
input string InpTradeComment = "XAUUSD_Strategy";  // 交易注释
input bool   InpUseDynamicLot = false;   // 启用动态仓位
input double InpRiskPercent = 2.0;       // 单笔交易风险百分比

input bool   InpEnableStrategyA = true;  // 启用策略A
input bool   InpEnableStrategyB = true;  // 启用策略B
input bool   InpEnableStrategyC = true;  // 启用策略C

//+------------------------------------------------------------------+
//| 全局变量                                                          |
//+------------------------------------------------------------------+
double g_cachedVWAP = 0;
int g_vwapCacheDay = 0;                  // 缓存交易日而非bar时间
int g_detectedDSTOffset = 2;
int g_lastTicket = 0;
int g_cachedSessionHour = -1;            // 时段缓存小时
bool g_cachedIsAsian = false;            // 缓存的亚时段状态
bool g_cachedIsEuropean = false;         // 缓存的欧美时段状态

//+------------------------------------------------------------------+
//| VWAP计算 (按日锚定)                                               |
//+------------------------------------------------------------------+
double GetDailyVWAP()
{
   datetime currentBarTime = iTime(NULL, PERIOD_M15, 0);
   int currentDay = GetForexTradingDay(currentBarTime);

   // 使用交易日作为缓存键，而非bar时间
   if(g_vwapCacheDay == currentDay && g_cachedVWAP > 0)
      return g_cachedVWAP;

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

   g_vwapCacheDay = currentDay;
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
//| 小时归一化辅助函数 (0-23范围)                                        |
//+------------------------------------------------------------------+
int NormalizeHour(int hour)
{
   if(hour >= 24) hour -= 24;
   if(hour < 0) hour += 24;
   return hour;
}

//+------------------------------------------------------------------+
//| 获取北京时间小时                                                    |
//+------------------------------------------------------------------+
int GetBeijingHour(int serverHour)
{
   return NormalizeHour(serverHour + (8 - g_detectedDSTOffset));
}

//+------------------------------------------------------------------+
//| 时段判断 (带缓存)                                                   |
//+------------------------------------------------------------------+
bool IsAsianSession()
{
   int serverHour = TimeHour(TimeCurrent());

   // 时段只在小时变化时才改变，使用缓存避免重复计算
   if(serverHour != g_cachedSessionHour)
   {
      g_cachedSessionHour = serverHour;
      int beijingHour = GetBeijingHour(serverHour);
      g_cachedIsAsian = (beijingHour >= InpAsianStartBJ && beijingHour < InpAsianEndBJ);
      g_cachedIsEuropean = (InpEuropeanEndBJ == 0)
         ? (beijingHour >= InpEuropeanStartBJ)
         : (beijingHour >= InpEuropeanStartBJ || beijingHour < InpEuropeanEndBJ);
   }

   return g_cachedIsAsian;
}

bool IsEuropeanSession()
{
   int serverHour = TimeHour(TimeCurrent());

   // 时段只在小时变化时才改变，使用缓存避免重复计算
   if(serverHour != g_cachedSessionHour)
   {
      g_cachedSessionHour = serverHour;
      int beijingHour = GetBeijingHour(serverHour);
      g_cachedIsAsian = (beijingHour >= InpAsianStartBJ && beijingHour < InpAsianEndBJ);
      g_cachedIsEuropean = (InpEuropeanEndBJ == 0)
         ? (beijingHour >= InpEuropeanStartBJ)
         : (beijingHour >= InpEuropeanStartBJ || beijingHour < InpEuropeanEndBJ);
   }

   return g_cachedIsEuropean;
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
//| 通用下单函数                                                      |
//+------------------------------------------------------------------+
bool OpenPosition(int orderType, double sl, double tp, string strategySuffix)
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
      InpTradeComment + "_" + strategySuffix,
      InpMagicNumber,
      0,
      arrowColor
   );

   if(ticket < 0)
   {
      Print("【下单失败】策略", strategySuffix, " 错误码: ", GetLastError());
      return false;
   }

   g_lastTicket = ticket;
   Print("【下单成功】策略", strategySuffix, " Ticket:", ticket, " 手数:", DoubleToString(lotSize, 2));
   return true;
}

//+------------------------------------------------------------------+
//| 通用平仓函数                                                      |
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
      Print("【平仓成功】原因:", reason, " Ticket:", ticket);
   else
      Print("【平仓失败】错误码: ", GetLastError());

   return result;
}

//+------------------------------------------------------------------+
//| 发送Buy Stop挂单                                                  |
//+------------------------------------------------------------------+
int SendBuyStopOrder(double triggerPrice, double stopLoss, string strategySuffix)
{
   int digits = (int)MarketInfo(Symbol(), MODE_DIGITS);
   triggerPrice = NormalizeDouble(triggerPrice, digits);
   stopLoss = NormalizeDouble(stopLoss, digits);

   if(Ask >= triggerPrice) return -1;

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
      InpTradeComment + "_" + strategySuffix,
      InpMagicNumber,
      expiration,
      clrBlue
   );

   if(ticket > 0) g_lastTicket = ticket;
   return ticket;
}

//+------------------------------------------------------------------+
//| 发送Sell Stop挂单                                                 |
//+------------------------------------------------------------------+
int SendSellStopOrder(double triggerPrice, double stopLoss, string strategySuffix)
{
   int digits = (int)MarketInfo(Symbol(), MODE_DIGITS);
   triggerPrice = NormalizeDouble(triggerPrice, digits);
   stopLoss = NormalizeDouble(stopLoss, digits);

   if(Bid <= triggerPrice) return -1;

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
      InpTradeComment + "_" + strategySuffix,
      InpMagicNumber,
      expiration,
      clrRed
   );

   if(ticket > 0) g_lastTicket = ticket;
   return ticket;
}

//+------------------------------------------------------------------+
//| 获取最后一张订单号                                                |
//+------------------------------------------------------------------+
int GetLastTicket() { return g_lastTicket; }
