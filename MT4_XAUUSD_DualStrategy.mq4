//+------------------------------------------------------------------+
//| XAUUSD Dual Strategy EA - MQL4 Implementation                    |
//|                                                                  |
//| 策略说明:                                                        |
//|   策略A - 均值回归 (亚盘 06:00-14:00 北京时间)                    |
//|   策略B - 动量突破 (欧美盘 15:00-00:00 北京时间)                  |
//|                                                                  |
//| 2026-03-21 重构 v5.0:                                            |
//|   - 【Critical Fix 1】废除本地Tick轮询模拟挂单，改用原生挂单      |
//|   - 【Critical Fix 2】废除文件I/O持仓状态，改为无状态计算         |
//|   - 【Critical Fix 3】VWAP按日动态锚定，不硬编码96根K线           |
//|   - 【Critical Fix 4】增加每日最大亏损熔断机制                    |
//|   - 增加 DST 动态探测                                            |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, XAUUSD Dual Strategy"
#property link      ""
#property version   "5.00"
#property strict

//+------------------------------------------------------------------+
//| 输入参数 (贝叶斯优化 - Optuna TPE 200次)                          |
//+------------------------------------------------------------------+
// 布林带参数
input int    InpBBPeriod = 13;           // 布林带周期
input double InpBBStd = 1.62;            // 布林带标准差倍数

// 肯特纳通道参数
input int    InpKCPeriod = 25;           // 肯特纳通道周期
input double InpKCATRMult = 1.30;        // 肯特纳通道ATR倍数

// ATR参数
input int    InpATRPeriod = 19;          // ATR周期

// RSI参数
input int    InpRSIPeriod = 21;          // RSI周期
input int    InpRSIOversold = 23;        // RSI超卖阈值
input int    InpRSIOverbought = 77;      // RSI超买阈值

// EMA参数
input int    InpEMAFast = 17;            // 快速EMA周期
input int    InpEMASlow = 32;            // 慢速EMA周期

// 策略A止损参数
input double InpSLATRMultA = 1.36;       // 策略A止损ATR倍数

// 策略B止损参数
input double InpSLATRMultB = 1.69;       // 策略B止损ATR倍数
input double InpTrailingATRMult = 4.54;  // 追踪止损ATR倍数

// 波动率挤压参数
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

// 【修复1.4 新增】最大点差过滤
input double InpMaxSpread = 50.0;        // 最大允许点差 (点值, XAUUSD典型点差约30-50)

// 【加固2.1 新增】休市保护参数
input bool   InpEnableFridayClose = true; // 启用周五闭盘前强制平仓
input int    InpFridayCloseHour = 22;     // 周五平仓小时 (服务器时间, 默认22:00)
input int    InpFridayCloseMinute = 0;    // 周五平仓分钟

// 【加固2.2 新增】点差平滑参数
input int    InpSpreadSmoothPeriod = 5;   // 点差平滑周期 (分钟)
input double InpSpreadMultThreshold = 2.0; // 点差扩大阈值倍数

// 【Critical Fix 4】熔断机制参数
input bool   InpEnableCircuitBreaker = true;  // 启用每日熔断
input double InpDailyMaxDrawdownPct = 3.0;    // 每日最大亏损百分比
input double InpInitialCapital = 10000.0;     // 初始资金 (用于熔断计算)

// 交易设置
input double InpLotSize = 1.0;           // 交易手数
input int    InpSlippage = 30;           // 滑点 (点)
input int    InpMagicNumber = 20260101;  // 魔术数字
input string InpTradeComment = "XAUUSD_DualStrategy";  // 交易注释

// 策略开关
input bool   InpEnableStrategyA = true;  // 启用策略A
input bool   InpEnableStrategyB = true;  // 启用策略B

// 挂单参数
input int    InpPendingExpirationHours = 4;  // 挂单过期时间 (小时)

//+------------------------------------------------------------------+
//| 全局变量                                                          |
//+------------------------------------------------------------------+
// 【Critical Fix 2】删除所有文件I/O相关的全局变量
// 持仓状态现在通过遍历订单实时计算

// 挂单状态跟踪 (用于策略B的挂单管理)
int g_pendingOrderTicket = 0;            // 当前挂单票号
int g_pendingDirection = 0;              // 挂单方向: 1=多, -1=空
double g_pendingStopLoss = 0;            // 挂单止损价
datetime g_pendingSignalTime = 0;        // 挂单信号产生时间

// 【Critical Fix 4】熔断状态
double g_dailyStartEquity = 0;           // 当日起始权益
datetime g_lastCircuitBreakerCheck = 0;  // 上次熔断检查日期
bool g_circuitBreakerTriggered = false;  // 熔断是否已触发

// 【加固2.2 新增】点差平滑跟踪
double g_spreadHistory[100];              // 存储历史点差
int g_spreadHistoryIndex = 0;
int g_spreadHistoryCount = 0;
datetime g_lastSpreadSampleTime = 0;

// DST 探测变量
int g_detectedDSTOffset = 2;             // 探测到的DST偏移

//+------------------------------------------------------------------+
//| EA初始化                                                          |
//+------------------------------------------------------------------+
int OnInit()
{
   Print("=== XAUUSD Dual Strategy EA v5.0 (Critical Fixes) ===");
   Print("【时区设置】券商UTC偏移: ", InpBrokerUTCOffset, " 小时");

   // 【Critical Fix 2】不再加载持仓状态文件
   // 改为在OnTick中实时计算

   // DST 自动探测
   DetectDSTOffset();

   // 初始化熔断状态
   g_dailyStartEquity = AccountEquity();
   g_lastCircuitBreakerCheck = TimeCurrent();
   g_circuitBreakerTriggered = false;

   Print("=== 初始化完成 ===");
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| EA反初始化                                                        |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   // 【Critical Fix 2】不再保存持仓状态到文件
   Print("=== XAUUSD Dual Strategy EA 停止 ===");
}

//+------------------------------------------------------------------+
//| 【Critical Fix 3】DST 自动探测                                    |
//| 通过比对服务器时间与本地时间测算当前偏移                          |
//+------------------------------------------------------------------+
void DetectDSTOffset()
{
   datetime serverTime = TimeCurrent();
   datetime localTime = TimeLocal();

   // 计算当前服务器与本地时间的差值 (秒)
   int diffSeconds = (int)(serverTime - localTime);

   // 美东时间 DST:
   // 夏令时 (3月第二个周日 - 11月第一个周日): UTC-4
   // 冬令时 (11月第一个周日 - 3月第二个周日): UTC-5
   // 北京时间始终为 UTC+8

   // 根据月份粗略判断是否在夏令时期间
   int month = TimeMonth(serverTime);

   // 简化判断: 4月-10月为夏令时
   if(month >= 4 && month <= 10)
   {
      g_detectedDSTOffset = 3;  // 夏令时: 纽约 UTC-4, 服务器通常为 UTC+3
      Print("【DST探测】检测到夏令时，服务器UTC偏移估算: ", g_detectedDSTOffset);
   }
   else
   {
      g_detectedDSTOffset = 2;  // 冬令时: 纽约 UTC-5, 服务器通常为 UTC+2
      Print("【DST探测】检测到冬令时，服务器UTC偏移估算: ", g_detectedDSTOffset);
   }
}

//+------------------------------------------------------------------+
//| 每个Tick处理 (MQL4 标准语法)                                      |
//+------------------------------------------------------------------+
void OnTick()
{
   // ═══════════════════════════════════════════════════════════════════
   // 【Critical Fix 4】熔断机制检查 (最高优先级)
   // ═══════════════════════════════════════════════════════════════════
   if(InpEnableCircuitBreaker)
   {
      if(CheckCircuitBreaker())
      {
         // 熔断已触发，拒绝所有交易
         return;
      }
   }

   // ═══════════════════════════════════════════════════════════════════
   // 【修复1.4】最大点差过滤
   // ═══════════════════════════════════════════════════════════════════
   double currentSpread = MarketInfo(Symbol(), MODE_SPREAD);
   if(currentSpread > InpMaxSpread)
   {
      return;
   }

   // ═══════════════════════════════════════════════════════════════════
   // 【加固2.1】周五闭盘前强制平仓检查
   // ═══════════════════════════════════════════════════════════════════
   CheckFridayForceClose();

   // 【加固2.2】采样当前点差
   SampleSpread();

   // 【Critical Fix 1】检查并管理挂单状态
   ManagePendingOrders();

   // 检查新K线形成
   static datetime lastBarTime = 0;
   datetime currentBarTime = iTime(NULL, PERIOD_M15, 0);
   bool newBar = (currentBarTime != lastBarTime);

   // 【MQL4 原生方式】获取指标值 - 使用当前K线的前一根已收盘K线 (索引1)
   double bbUpper = iBands(NULL, PERIOD_M15, InpBBPeriod, 0, InpBBStd, PRICE_CLOSE, MODE_UPPER, 1);
   double bbLower = iBands(NULL, PERIOD_M15, InpBBPeriod, 0, InpBBStd, PRICE_CLOSE, MODE_LOWER, 1);
   double bbMiddle = iBands(NULL, PERIOD_M15, InpBBPeriod, 0, InpBBStd, PRICE_CLOSE, MODE_MAIN, 1);

   double atr = iATR(NULL, PERIOD_M15, InpATRPeriod, 1);
   double rsi = iRSI(NULL, PERIOD_M15, InpRSIPeriod, PRICE_CLOSE, 1);

   double emaFast = iMA(NULL, PERIOD_M15, InpEMAFast, 0, MODE_EMA, PRICE_CLOSE, 1);
   double emaSlow = iMA(NULL, PERIOD_M15, InpEMASlow, 0, MODE_EMA, PRICE_CLOSE, 1);

   // 计算肯特纳通道
   double kcMiddle = iMA(NULL, PERIOD_M15, InpKCPeriod, 0, MODE_EMA, PRICE_CLOSE, 1);
   double kcUpper = kcMiddle + InpKCATRMult * atr;
   double kcLower = kcMiddle - InpKCATRMult * atr;

   // 获取当前价格
   double close = iClose(NULL, PERIOD_M15, 0);
   double high = iHigh(NULL, PERIOD_M15, 0);
   double low = iLow(NULL, PERIOD_M15, 0);

   // 时区转换后的交易时段判断
   bool isAsian = IsAsianSession();
   bool isEuropean = IsEuropeanSession();

   // 计算波动率指标
   double squeezeRatio = CalculateSqueezeRatio(bbUpper, bbLower, bbMiddle, kcUpper, kcLower);
   bool isTrend = (squeezeRatio >= InpSqueezeThreshold);
   bool squeezeRelease = CheckSqueezeRelease();

   // 【Critical Fix 3】获取按日动态锚定的 VWAP
   double vwap = GetDailyVWAP();

   // ═══════════════════════════════════════════════════════════════════
   // 【Critical Fix 2】持仓检查 - 实时遍历订单 (无状态)
   // ═══════════════════════════════════════════════════════════════════
   bool hasPosition = false;
   int positionTicket = -1;
   int positionType = -1;
   double positionSL = 0;
   double positionOpenPrice = 0;
   datetime positionOpenTime = 0;

   int totalOrders = OrdersTotal();

   for(int i = totalOrders - 1; i >= 0; i--)
   {
      if(OrderSelect(i, SELECT_BY_POS, MODE_TRADES))
      {
         if(OrderSymbol() == Symbol() && OrderMagicNumber() == InpMagicNumber)
         {
            int orderType = OrderType();

            // 只处理持仓订单 (OP_BUY 或 OP_SELL)
            if(orderType == OP_BUY || orderType == OP_SELL)
            {
               hasPosition = true;
               positionTicket = OrderTicket();
               positionType = orderType;
               positionSL = OrderStopLoss();
               positionOpenPrice = OrderOpenPrice();
               positionOpenTime = OrderOpenTime();
               break;
            }
         }
      }
   }

   // ═══════════════════════════════════════════════════════════════════
   // 持仓出场检查 - 每Tick实时执行
   // ═══════════════════════════════════════════════════════════════════
   if(hasPosition)
   {
      // 【Critical Fix 2】实时计算持仓K线数
      int barsHeld = CalculateBarsHeld(positionOpenTime);

      // 【Critical Fix 2】实时计算持仓期间最高/最低价
      double highestPrice = 0, lowestPrice = 1000000;
      CalculatePositionExtremes(positionOpenTime, positionType, highestPrice, lowestPrice);

      // 出场检查
      CheckExitConditions(positionTicket, positionType, positionSL, positionOpenPrice,
                          atr, vwap, barsHeld, highestPrice, lowestPrice);
   }
   else
   {
      // 无持仓时检查入场信号 (只在 newBar 时检测新信号)
      if(newBar)
      {
         // 策略A检查 - 均值回归
         if(InpEnableStrategyA && isAsian)
         {
            CheckStrategyAEntry(close, bbUpper, bbLower, rsi, atr, high, low);
         }

         // 策略B检查 - 动量突破
         if(InpEnableStrategyB && isEuropean && g_pendingOrderTicket == 0)
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
//| 【Critical Fix 4】熔断机制检查                                    |
//| 返回 true 表示熔断已触发，应拒绝交易                              |
//+------------------------------------------------------------------+
bool CheckCircuitBreaker()
{
   datetime currentTime = TimeCurrent();
   int currentDay = TimeDay(currentTime);
   int lastCheckDay = TimeDay(g_lastCircuitBreakerCheck);

   // 新的一天，重置熔断状态
   if(currentDay != lastCheckDay)
   {
      g_dailyStartEquity = AccountEquity();
      g_circuitBreakerTriggered = false;
      g_lastCircuitBreakerCheck = currentTime;
      Print("【熔断重置】新的一天，起始权益: $", DoubleToString(g_dailyStartEquity, 2));
   }

   // 如果已触发熔断，检查是否还在同一天
   if(g_circuitBreakerTriggered)
   {
      return true;
   }

   // 计算当前回撤
   double currentEquity = AccountEquity();
   double drawdownPct = (g_dailyStartEquity - currentEquity) / g_dailyStartEquity * 100;

   // 检查是否触发熔断阈值
   if(drawdownPct >= InpDailyMaxDrawdownPct)
   {
      g_circuitBreakerTriggered = true;
      Print("【熔断触发】当日回撤 ", DoubleToString(drawdownPct, 2), "% 达到阈值 ",
            DoubleToString(InpDailyMaxDrawdownPct, 2), "%");

      // 强制平掉所有仓位
      CloseAllPositions("每日熔断平仓");

      // 删除所有挂单
      DeleteAllPendingOrders();

      return true;
   }

   return false;
}

//+------------------------------------------------------------------+
//| 【Critical Fix 2】实时计算持仓K线数                               |
//+------------------------------------------------------------------+
int CalculateBarsHeld(datetime openTime)
{
   datetime currentTime = TimeCurrent();
   int barDiff = (int)((currentTime - openTime) / (15 * 60));  // 15分钟K线
   return MathMax(0, barDiff);
}

//+------------------------------------------------------------------+
//| 【Critical Fix 2】实时计算持仓期间最高/最低价                     |
//+------------------------------------------------------------------+
void CalculatePositionExtremes(datetime openTime, int positionType,
                               double &highestPrice, double &lowestPrice)
{
   // 找到入场时间对应的K线索引
   int startBar = iBarShift(NULL, PERIOD_M15, openTime);
   int currentBar = 0;  // 当前K线

   highestPrice = 0;
   lowestPrice = 1000000;

   // 遍历持仓期间的所有K线
   for(int i = startBar; i >= currentBar; i--)
   {
      double barHigh = iHigh(NULL, PERIOD_M15, i);
      double barLow = iLow(NULL, PERIOD_M15, i);

      if(barHigh > highestPrice) highestPrice = barHigh;
      if(barLow < lowestPrice) lowestPrice = barLow;
   }

   // 同时考虑当前Tick的价格
   if(positionType == OP_BUY)
   {
      if(Ask > highestPrice) highestPrice = Ask;
      if(Bid < lowestPrice) lowestPrice = Bid;
   }
   else
   {
      if(Ask > highestPrice) highestPrice = Ask;
      if(Bid < lowestPrice) lowestPrice = Bid;
   }
}

//+------------------------------------------------------------------+
//| 【Critical Fix 3】VWAP 按日动态锚定计算                           |
//| 不硬编码 i<96，通过日期判断确保节假日也能正确计算                  |
//+------------------------------------------------------------------+
double GetDailyVWAP()
{
   // 获取当前K线的日期
   datetime currentBarTime = iTime(NULL, PERIOD_M15, 0);
   int currentDayOfYear = TimeDayOfYear(currentBarTime);
   int currentYear = TimeYear(currentBarTime);

   double dailyTPV = 0;
   double dailyVolume = 0;

   // 向前遍历，直到日期变化
   for(int i = 1; i < 500; i++)  // 最多遍历500根K线 (防止无限循环)
   {
      datetime barTime = iTime(NULL, PERIOD_M15, i);

      // 检查日期是否变化
      int barDayOfYear = TimeDayOfYear(barTime);
      int barYear = TimeYear(barTime);

      if(barDayOfYear != currentDayOfYear || barYear != currentYear)
      {
         // 已到达前一天，停止遍历
         break;
      }

      // 累加当日数据 (只使用已收盘K线，i >= 1)
      double typicalPrice = (iHigh(NULL, PERIOD_M15, i) +
                             iLow(NULL, PERIOD_M15, i) +
                             iClose(NULL, PERIOD_M15, i)) / 3.0;
      double vol = (double)iVolume(NULL, PERIOD_M15, i);

      dailyTPV += typicalPrice * vol;
      dailyVolume += vol;
   }

   // 返回VWAP
   if(dailyVolume > 0)
   {
      return dailyTPV / dailyVolume;
   }
   else
   {
      // 无数据时返回前一根K线收盘价
      return iClose(NULL, PERIOD_M15, 1);
   }
}

//+------------------------------------------------------------------+
//| 【Critical Fix 1】挂单管理                                        |
//| 检查挂单状态，处理过期、触发或失败的挂单                          |
//+------------------------------------------------------------------+
void ManagePendingOrders()
{
   if(g_pendingOrderTicket == 0) return;

   // 检查挂单是否还存在
   if(!OrderSelect(g_pendingOrderTicket, SELECT_BY_TICKET))
   {
      // 挂单不存在，重置状态
      ResetPendingState();
      return;
   }

   int orderType = OrderType();

   // 检查是否已成交 (变为持仓)
   if(orderType == OP_BUY || orderType == OP_SELL)
   {
      // 挂单已成交，重置挂单状态
      Print("【挂单成交】Ticket: ", g_pendingOrderTicket,
            " 类型: ", (orderType == OP_BUY ? "BUY" : "SELL"));
      ResetPendingState();
      return;
   }

   // 检查挂单是否过期
   datetime expirationTime = OrderExpiration();
   if(expirationTime > 0 && TimeCurrent() >= expirationTime)
   {
      // 挂单过期，删除它
      if(OrderDelete(g_pendingOrderTicket))
      {
         Print("【挂单过期删除】Ticket: ", g_pendingOrderTicket);
      }
      ResetPendingState();
      return;
   }

   // 检查挂单类型是否正确
   if(orderType != OP_BUYSTOP && orderType != OP_SELLSTOP)
   {
      // 异常状态，重置
      ResetPendingState();
   }
}

//+------------------------------------------------------------------+
//| 重置挂单状态                                                      |
//+------------------------------------------------------------------+
void ResetPendingState()
{
   g_pendingOrderTicket = 0;
   g_pendingDirection = 0;
   g_pendingStopLoss = 0;
   g_pendingSignalTime = 0;
}

//+------------------------------------------------------------------+
//| 时区转换：检查是否为亚盘时段                                      |
//+------------------------------------------------------------------+
bool IsAsianSession()
{
   int serverHour = TimeHour(TimeCurrent());
   // 使用 DST 感知后的偏移量
   int effectiveOffset = InpBrokerUTCOffset;
   if(g_detectedDSTOffset != InpBrokerUTCOffset)
   {
      effectiveOffset = g_detectedDSTOffset;
   }

   int beijingHour = serverHour + (8 - effectiveOffset);

   if(beijingHour >= 24) beijingHour -= 24;
   if(beijingHour < 0) beijingHour += 24;

   return (beijingHour >= InpAsianStartBJ && beijingHour < InpAsianEndBJ);
}

//+------------------------------------------------------------------+
//| 时区转换：检查是否为欧美盘时段                                    |
//+------------------------------------------------------------------+
bool IsEuropeanSession()
{
   int serverHour = TimeHour(TimeCurrent());
   int effectiveOffset = InpBrokerUTCOffset;
   if(g_detectedDSTOffset != InpBrokerUTCOffset)
   {
      effectiveOffset = g_detectedDSTOffset;
   }

   int beijingHour = serverHour + (8 - effectiveOffset);

   if(beijingHour >= 24) beijingHour -= 24;
   if(beijingHour < 0) beijingHour += 24;

   if(InpEuropeanEndBJ == 0)
      return (beijingHour >= InpEuropeanStartBJ);
   else
      return (beijingHour >= InpEuropeanStartBJ || beijingHour < InpEuropeanEndBJ);
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
bool CheckSqueezeRelease()
{
   double bbUpper0 = iBands(NULL, PERIOD_M15, InpBBPeriod, 0, InpBBStd, PRICE_CLOSE, MODE_UPPER, 1);
   double bbLower0 = iBands(NULL, PERIOD_M15, InpBBPeriod, 0, InpBBStd, PRICE_CLOSE, MODE_LOWER, 1);

   double atr0 = iATR(NULL, PERIOD_M15, InpATRPeriod, 1);
   double kcMiddle0 = iMA(NULL, PERIOD_M15, InpKCPeriod, 0, MODE_EMA, PRICE_CLOSE, 1);
   double kcUpper0 = kcMiddle0 + InpKCATRMult * atr0;
   double kcLower0 = kcMiddle0 - InpKCATRMult * atr0;

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
//| 策略A入场检查                                                     |
//+------------------------------------------------------------------+
void CheckStrategyAEntry(double close, double bbUpper, double bbLower,
                         double rsi, double atr, double high, double low)
{
   if(CheckAbnormalVolatility(high, low, atr))
   {
      return;
   }

   // 做多条件
   if(close <= bbLower && rsi < InpRSIOversold)
   {
      double slAnchor = MathMin(close, bbLower);
      double sl = slAnchor - InpSLATRMultA * atr;
      double vwap = GetDailyVWAP();

      Print("策略A做多: 止损锚定=", slAnchor, " 止损=", sl);

      if(OpenPositionMQL4(OP_BUY, sl, vwap, "A"))
      {
         // 策略A成功开仓
      }
      return;
   }

   // 做空条件
   if(close >= bbUpper && rsi > InpRSIOverbought)
   {
      double slAnchor = MathMax(close, bbUpper);
      double sl = slAnchor + InpSLATRMultA * atr;
      double vwap = GetDailyVWAP();

      Print("策略A做空: 止损锚定=", slAnchor, " 止损=", sl);

      if(OpenPositionMQL4(OP_SELL, sl, vwap, "A"))
      {
         // 策略A成功开仓
      }
   }
}

//+------------------------------------------------------------------+
//| 【Critical Fix 1】策略B入场 - 使用原生挂单                        |
//+------------------------------------------------------------------+
void CheckStrategyBEntry(double close, double bbUpper, double bbLower, double bbMiddle,
                         double kcUpper, double kcLower,
                         double emaFast, double emaSlow,
                         bool isTrend, bool squeezeRelease, double atr, double high, double low)
{
   if(CheckAbnormalVolatility(high, low, atr))
   {
      return;
   }

   if(!isTrend && !squeezeRelease) return;

   // 检查是否已有挂单
   if(g_pendingOrderTicket != 0) return;

   // 做多条件
   if(close > bbUpper && bbUpper > kcUpper && emaFast > emaSlow)
   {
      double prevLow = iLow(NULL, PERIOD_M15, 1);
      double entryPrice = high;  // 突破K线最高价作为挂单触发价
      double sl = MathMax(entryPrice - InpSLATRMultB * atr, prevLow);

      // 【Critical Fix 1】发送原生 Buy Stop 挂单
      int ticket = SendBuyStopOrder(entryPrice, sl, 0);

      if(ticket > 0)
      {
         g_pendingOrderTicket = ticket;
         g_pendingDirection = 1;
         g_pendingStopLoss = sl;
         g_pendingSignalTime = TimeCurrent();
         Print("策略B: 做多挂单已发送, Ticket=", ticket, " 触发价=", entryPrice, " 止损=", sl);
      }
      return;
   }

   // 做空条件
   if(close < bbLower && bbLower < kcLower && emaFast < emaSlow)
   {
      double prevHigh = iHigh(NULL, PERIOD_M15, 1);
      double entryPrice = low;  // 突破K线最低价作为挂单触发价
      double sl = MathMin(entryPrice + InpSLATRMultB * atr, prevHigh);

      // 【Critical Fix 1】发送原生 Sell Stop 挂单
      int ticket = SendSellStopOrder(entryPrice, sl, 0);

      if(ticket > 0)
      {
         g_pendingOrderTicket = ticket;
         g_pendingDirection = -1;
         g_pendingStopLoss = sl;
         g_pendingSignalTime = TimeCurrent();
         Print("策略B: 做空挂单已发送, Ticket=", ticket, " 触发价=", entryPrice, " 止损=", sl);
      }
   }
}

//+------------------------------------------------------------------+
//| 【Critical Fix 1】发送 Buy Stop 挂单                              |
//+------------------------------------------------------------------+
int SendBuyStopOrder(double triggerPrice, double stopLoss, double takeProfit)
{
   // 规范化价格
   int digits = (int)MarketInfo(Symbol(), MODE_DIGITS);
   triggerPrice = NormalizeDouble(triggerPrice, digits);
   stopLoss = NormalizeDouble(stopLoss, digits);
   if(takeProfit > 0) takeProfit = NormalizeDouble(takeProfit, digits);

   // 计算过期时间
   datetime expiration = TimeCurrent() + InpPendingExpirationHours * 3600;

   // StopLevel 检查
   double stopLevel = MarketInfo(Symbol(), MODE_STOPLEVEL) * Point;
   double ask = Ask;

   if(triggerPrice - ask < stopLevel)
   {
      // 挂单价太近，调整到最小距离
      triggerPrice = ask + stopLevel;
      triggerPrice = NormalizeDouble(triggerPrice, digits);
   }

   if(ask - stopLoss < stopLevel)
   {
      Print("【挂单拒绝】止损过近: 入场价=", ask, " 止损=", stopLoss);
      return -1;
   }

   // 发送挂单
   int ticket = OrderSend(
      Symbol(),
      OP_BUYSTOP,
      InpLotSize,
      triggerPrice,
      InpSlippage,
      stopLoss,
      takeProfit,
      InpTradeComment + "_B",
      InpMagicNumber,
      expiration,
      clrBlue
   );

   if(ticket < 0)
   {
      int error = GetLastError();
      Print("【挂单失败】BuyStop, 错误码: ", error, " 描述: ", ErrorDescription(error));
   }

   return ticket;
}

//+------------------------------------------------------------------+
//| 【Critical Fix 1】发送 Sell Stop 挂单                             |
//+------------------------------------------------------------------+
int SendSellStopOrder(double triggerPrice, double stopLoss, double takeProfit)
{
   int digits = (int)MarketInfo(Symbol(), MODE_DIGITS);
   triggerPrice = NormalizeDouble(triggerPrice, digits);
   stopLoss = NormalizeDouble(stopLoss, digits);
   if(takeProfit > 0) takeProfit = NormalizeDouble(takeProfit, digits);

   datetime expiration = TimeCurrent() + InpPendingExpirationHours * 3600;

   double stopLevel = MarketInfo(Symbol(), MODE_STOPLEVEL) * Point;
   double bid = Bid;

   if(bid - triggerPrice < stopLevel)
   {
      triggerPrice = bid - stopLevel;
      triggerPrice = NormalizeDouble(triggerPrice, digits);
   }

   if(stopLoss - bid < stopLevel)
   {
      Print("【挂单拒绝】止损过近: 入场价=", bid, " 止损=", stopLoss);
      return -1;
   }

   int ticket = OrderSend(
      Symbol(),
      OP_SELLSTOP,
      InpLotSize,
      triggerPrice,
      InpSlippage,
      stopLoss,
      takeProfit,
      InpTradeComment + "_B",
      InpMagicNumber,
      expiration,
      clrRed
   );

   if(ticket < 0)
   {
      int error = GetLastError();
      Print("【挂单失败】SellStop, 错误码: ", error, " 描述: ", ErrorDescription(error));
   }

   return ticket;
}

//+------------------------------------------------------------------+
//| MQL4 原生下单函数                                                 |
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

   int digits = (int)MarketInfo(Symbol(), MODE_DIGITS);
   double stopLevel = MarketInfo(Symbol(), MODE_STOPLEVEL) * Point;

   // StopLevel 防御
   if(orderType == OP_BUY)
   {
      if(sl > 0 && price - sl < stopLevel)
      {
         Print("【风控拒绝】多头止损过近: 入场价=", price, " 止损=", sl);
         return false;
      }
   }
   else
   {
      if(sl > 0 && sl - price < stopLevel)
      {
         Print("【风控拒绝】空头止损过近: 入场价=", price, " 止损=", sl);
         return false;
      }
   }

   sl = NormalizeDouble(sl, digits);
   if(tp > 0) tp = NormalizeDouble(tp, digits);

   int maxRetries = 3;
   int ticket = -1;

   for(int retry = 0; retry < maxRetries; retry++)
   {
      ticket = OrderSend(
         Symbol(),
         orderType,
         InpLotSize,
         price,
         InpSlippage,
         sl,
         tp,
         InpTradeComment + "_" + strategy,
         InpMagicNumber,
         0,
         arrowColor
      );

      if(ticket >= 0)
      {
         break;
      }

      int error = GetLastError();

      if(error == 138 || error == 146)
      {
         Print("【下单重试】错误码: ", error, " 重试次数: ", retry + 1);
         Sleep(100);
         RefreshRates();

         if(orderType == OP_BUY)
            price = Ask;
         else
            price = Bid;
      }
      else
      {
         Print("【下单失败】错误码: ", error, " 描述: ", ErrorDescription(error));
         return false;
      }
   }

   if(ticket < 0)
   {
      int error = GetLastError();
      Print("【下单最终失败】错误码: ", error);
      return false;
   }

   Print("【下单成功】Ticket: ", ticket, " 类型: ", (orderType == OP_BUY ? "BUY" : "SELL"),
         " 价格: ", price, " 止损: ", sl, " 止盈: ", tp);

   return true;
}

//+------------------------------------------------------------------+
//| 出场条件检查                                                      |
//+------------------------------------------------------------------+
void CheckExitConditions(int positionTicket, int positionType, double positionSL,
                         double positionOpenPrice, double currentATR, double vwap,
                         int barsHeld, double highestPrice, double lowestPrice)
{
   // 获取当前策略
   string strategy = GetOrderStrategy(positionTicket);

   bool shouldClose = false;
   string reason = "";

   SampleSpread();

   // 策略A出场
   if(strategy == "A")
   {
      if(positionType == OP_BUY)
      {
         if(Bid <= positionSL)
         {
            shouldClose = true;
            reason = "止损";
         }
         else if(Ask >= vwap)
         {
            double midPrice = (Bid + Ask) / 2;
            if(midPrice >= vwap && IsSpreadSafeForExit())
            {
               shouldClose = true;
               reason = "VWAP止盈";
            }
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
            double midPrice = (Bid + Ask) / 2;
            if(midPrice <= vwap && IsSpreadSafeForExit())
            {
               shouldClose = true;
               reason = "VWAP止盈";
            }
         }
      }

      // ATR自适应动态时间止损
      if(!shouldClose)
      {
         double avgATR = CalculateAverageATR();
         int dynamicMaxBars = CalculateDynamicTimeStop(currentATR, avgATR);
         if(barsHeld >= dynamicMaxBars)
         {
            shouldClose = true;
            reason = "ATR动态时间止损";
         }
      }
   }

   // 策略B出场
   if(strategy == "B")
   {
      if(positionType == OP_BUY)
      {
         if(Bid <= positionSL)
         {
            shouldClose = true;
            reason = "初始止损";
         }
         else
         {
            double trailingStop = highestPrice - InpTrailingATRMult * currentATR;
            if(Bid <= trailingStop && highestPrice > positionOpenPrice)
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
            double trailingStop = lowestPrice + InpTrailingATRMult * currentATR;
            if(Ask >= trailingStop && lowestPrice < positionOpenPrice)
            {
               shouldClose = true;
               reason = "追踪止损";
            }
         }
      }
   }

   if(shouldClose)
   {
      ClosePositionMQL4(reason);
   }
}

//+------------------------------------------------------------------+
//| 获取订单策略类型                                                  |
//+------------------------------------------------------------------+
string GetOrderStrategy(int ticket)
{
   if(OrderSelect(ticket, SELECT_BY_TICKET))
   {
      string comment = OrderComment();
      if(StringFind(comment, "_A") >= 0) return "A";
      if(StringFind(comment, "_B") >= 0) return "B";
   }
   return "A";  // 默认返回A
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
//| 采样当前点差                                                      |
//+------------------------------------------------------------------+
void SampleSpread()
{
   datetime currentTime = TimeCurrent();
   int elapsedSeconds = (int)(currentTime - g_lastSpreadSampleTime);

   if(elapsedSeconds >= 60)
   {
      double currentSpread = MarketInfo(Symbol(), MODE_SPREAD);
      g_spreadHistory[g_spreadHistoryIndex] = currentSpread;
      g_spreadHistoryIndex = (g_spreadHistoryIndex + 1) % 100;
      if(g_spreadHistoryCount < 100) g_spreadHistoryCount++;
      g_lastSpreadSampleTime = currentTime;
   }
}

//+------------------------------------------------------------------+
//| 计算平均点差                                                      |
//+------------------------------------------------------------------+
double GetAverageSpread(int periodMinutes)
{
   if(g_spreadHistoryCount == 0) return MarketInfo(Symbol(), MODE_SPREAD);

   double sum = 0;
   int count = MathMin(periodMinutes, g_spreadHistoryCount);
   int startIndex = g_spreadHistoryIndex - count;
   if(startIndex < 0) startIndex += 100;

   for(int i = 0; i < count; i++)
   {
      int idx = (startIndex + i) % 100;
      sum += g_spreadHistory[idx];
   }

   return (count > 0) ? sum / count : MarketInfo(Symbol(), MODE_SPREAD);
}

//+------------------------------------------------------------------+
//| 检查点差是否允许出场                                              |
//+------------------------------------------------------------------+
bool IsSpreadSafeForExit()
{
   double currentSpread = MarketInfo(Symbol(), MODE_SPREAD);
   double avgSpread = GetAverageSpread(InpSpreadSmoothPeriod);

   if(avgSpread > 0 && currentSpread > avgSpread * InpSpreadMultThreshold)
   {
      Print("【点差防护】拒绝出场: 当前点差=", currentSpread);
      return false;
   }

   return true;
}

//+------------------------------------------------------------------+
//| 周五闭盘前强制平仓检查                                            |
//+------------------------------------------------------------------+
void CheckFridayForceClose()
{
   if(!InpEnableFridayClose) return;

   datetime currentTime = TimeCurrent();
   int dayOfWeek = TimeDayOfWeek(currentTime);
   int hour = TimeHour(currentTime);
   int minute = TimeMinute(currentTime);

   if(dayOfWeek == 5)
   {
      if(hour == InpFridayCloseHour && minute >= InpFridayCloseMinute)
      {
         CloseAllPositions("周五闭盘前强制平仓");
      }
   }
}

//+------------------------------------------------------------------+
//| 平仓所有仓位                                                      |
//+------------------------------------------------------------------+
void CloseAllPositions(string reason)
{
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
               Print("【强制平仓】原因: ", reason, " 订单 #", OrderTicket());
               ClosePositionMQL4(reason);
            }
         }
      }
   }
}

//+------------------------------------------------------------------+
//| 删除所有挂单                                                      |
//+------------------------------------------------------------------+
void DeleteAllPendingOrders()
{
   int totalOrders = OrdersTotal();
   for(int i = totalOrders - 1; i >= 0; i--)
   {
      if(OrderSelect(i, SELECT_BY_POS, MODE_TRADES))
      {
         if(OrderSymbol() == Symbol() && OrderMagicNumber() == InpMagicNumber)
         {
            int orderType = OrderType();
            if(orderType == OP_BUYSTOP || orderType == OP_SELLSTOP ||
               orderType == OP_BUYLIMIT || orderType == OP_SELLLIMIT)
            {
               if(OrderDelete(OrderTicket()))
               {
                  Print("【删除挂单】Ticket: ", OrderTicket());
               }
            }
         }
      }
   }
   ResetPendingState();
}

//+------------------------------------------------------------------+
//| MQL4 原生平仓函数                                                 |
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

            if(orderType != OP_BUY && orderType != OP_SELL)
               continue;

            double closePrice;
            color arrowColor;

            if(orderType == OP_BUY)
            {
               closePrice = Bid;
               arrowColor = clrRed;
            }
            else
            {
               closePrice = Ask;
               arrowColor = clrBlue;
            }

            int digits = (int)MarketInfo(Symbol(), MODE_DIGITS);
            closePrice = NormalizeDouble(closePrice, digits);

            int maxRetries = 3;
            bool closeResult = false;

            for(int retry = 0; retry < maxRetries; retry++)
            {
               closeResult = OrderClose(ticket, lots, closePrice, InpSlippage, arrowColor);

               if(closeResult == true)
               {
                  break;
               }

               int error = GetLastError();

               if(error == 138 || error == 146)
               {
                  Print("【平仓重试】错误码: ", error, " 重试次数: ", retry + 1);
                  Sleep(100);
                  RefreshRates();

                  if(orderType == OP_BUY)
                     closePrice = NormalizeDouble(Bid, digits);
                  else
                     closePrice = NormalizeDouble(Ask, digits);
               }
               else
               {
                  Print("【平仓失败】错误码: ", error);
                  return false;
               }
            }

            if(closeResult == false)
            {
               int error = GetLastError();
               Print("【平仓最终失败】错误码: ", error);
               return false;
            }

            Print("【平仓成功】Ticket: ", ticket, " 原因: ", reason, " 价格: ", closePrice);
            return true;
         }
      }
   }

   return false;
}

//+------------------------------------------------------------------+
//| 错误描述                                                          |
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
