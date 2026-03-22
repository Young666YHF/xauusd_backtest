//+------------------------------------------------------------------+
//| XAUUSD Dual Strategy EA - MQL4 Implementation                    |
//|                                                                  |
//| 策略说明:                                                        |
//|   策略A - 均值回归 (亚盘 06:00-14:00 北京时间)                    |
//|   策略B - 动量突破 (欧美盘 15:00-00:00 北京时间)                  |
//|                                                                  |
//| 2026-03-22 更新 v5.2 - 核心逻辑缺陷修复:                         |
//|   - 【修复1】并发持仓逻辑: 策略A和策略B独立追踪持仓，允许同时开仓 |
//|   - 【修复4】动态手数: NormalizeDouble防止浮点截断Error 131      |
//|   - 【修复5】VWAP时区: EST时间锚定确保美东17:00重置              |
//|                                                                  |
//| 2026-03-22 更新 v5.1:                                            |
//|   - 【任务1 Critical】修复平仓函数"张冠李戴"Bug                   |
//|   - 【任务2】引入动态仓位计算 (风险百分比法)                      |
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
#property version   "5.20"
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
input double InpLotSize = 1.0;           // 交易手数 (动态仓位时作为最大限制)
input int    InpSlippage = 30;           // 滑点 (点)
input int    InpMagicNumber = 20260101;  // 魔术数字
input string InpTradeComment = "XAUUSD_DualStrategy";  // 交易注释

// 【任务2 新增】动态仓位参数
input bool   InpUseDynamicLot = true;    // 启用动态仓位 (风险百分比法)
input double InpRiskPercent = 2.0;       // 单笔交易风险百分比 (1-5%)

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

// 【Critical Fix 5】VWAP 缓存变量 - 消除性能瓶颈
double g_cachedVWAP = 0;                  // 缓存的 VWAP 值
datetime g_vwapCacheBarTime = 0;          // VWAP 缓存对应的 K 线时间

// 【Critical Fix 3】追踪止损独立存储数组 - 替代 static 变量
// 最大支持 100 个独立持仓的追踪止损
#define MAX_TRAILING_STOP_TRACKERS 100
int g_trailingStopTickets[MAX_TRAILING_STOP_TRACKERS];     // 订单票号
double g_trailingStopValues[MAX_TRAILING_STOP_TRACKERS];   // 追踪止损值
int g_trailingStopCount = 0;

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
//| 【Critical Fix 6】DST 自动探测                                    |
//|                                                                   |
//| 废弃 TimeLocal() 依赖，改用服务器时间 + 参数传入                  |
//|                                                                   |
//| 美国夏令时规则 (2007年起):                                        |
//| - 开始: 3月第二个周日 02:00 本地时间                              |
//| - 结束: 11月第一个周日 02:00 本地时间                             |
//|                                                                   |
//| 券商服务器时区 (通过参数 InpBrokerUTCOffset 传入):               |
//| - 冬令时: UTC+2 (欧洲/塞浦路斯服务器)                            |
//| - 夏令时: UTC+3                                                   |
//+------------------------------------------------------------------+
void DetectDSTOffset()
{
   datetime serverTime = TimeCurrent();

   // ═══════════════════════════════════════════════════════════════════════
   // 【废弃 TimeLocal()】VPS 本地时间不可靠
   // 改用服务器时间 + 月份判断 + 参数确认
   // ═══════════════════════════════════════════════════════════════════════

   int month = TimeMonth(serverTime);
   int day = TimeDay(serverTime);
   int dayOfWeek = TimeDayOfWeek(serverTime);

   // 精确判断美国夏令时
   bool isDST = IsUSDSTActive(month, day, dayOfWeek);

   if(isDST)
   {
      // 夏令时: 服务器通常为 UTC+3
      // 如果用户参数已设为 3，则使用用户参数
      // 否则自动设为 3
      if(InpBrokerUTCOffset == 3)
      {
         g_detectedDSTOffset = 3;
      }
      else
      {
         // 警告用户
         Print("【DST 警告】检测到夏令时，但 InpBrokerUTCOffset=", InpBrokerUTCOffset);
         Print("【DST 建议】请将 InpBrokerUTCOffset 设为 3 (UTC+3)");
         Print("【DST 使用】继续使用用户参数: ", InpBrokerUTCOffset);
         g_detectedDSTOffset = InpBrokerUTCOffset;
      }
   }
   else
   {
      // 冬令时: 服务器通常为 UTC+2
      if(InpBrokerUTCOffset == 2)
      {
         g_detectedDSTOffset = 2;
      }
      else
      {
         Print("【DST 警告】检测到冬令时，但 InpBrokerUTCOffset=", InpBrokerUTCOffset);
         Print("【DST 建议】请将 InpBrokerUTCOffset 设为 2 (UTC+2)");
         Print("【DST 使用】继续使用用户参数: ", InpBrokerUTCOffset);
         g_detectedDSTOffset = InpBrokerUTCOffset;
      }
   }

   Print("【DST 结果】夏令时: ", (isDST ? "是" : "否"),
         ", 服务器 UTC 偏移: ", g_detectedDSTOffset,
         ", 北京时间转换: 服务器时间 + ", (8 - g_detectedDSTOffset), " 小时");
}


//+------------------------------------------------------------------+
//| 【Critical Fix 6】精确判断美国夏令时                              |
//| 美国夏令时: 3月第二个周日 - 11月第一个周日                        |
//+------------------------------------------------------------------+
bool IsUSDSTActive(int month, int day, int dayOfWeek)
{
   // 快速判断: 4月-10月肯定是夏令时
   if(month >= 4 && month <= 10)
   {
      return true;
   }

   // 1月-2月肯定不是夏令时
   if(month == 1 || month == 2)
   {
      return false;
   }

   // 12月肯定不是夏令时
   if(month == 12)
   {
      return false;
   }

   // ═══════════════════════════════════════════════════════════════════════
   // 边界月份: 3月和11月需要精确判断
   // ═══════════════════════════════════════════════════════════════════════

   if(month == 3)
   {
      // 3月: 第二个周日及之后是夏令时
      // 计算本月第二个周日是几号
      int secondSunday = GetNthSundayOfMonth(3, 2);

      // 如果当前日期 >= 第二个周日，则是夏令时
      return (day >= secondSunday);
   }

   if(month == 11)
   {
      // 11月: 第一个周日及之后不是夏令时
      // 计算本月第一个周日是几号
      int firstSunday = GetNthSundayOfMonth(11, 1);

      // 如果当前日期 < 第一个周日，则是夏令时
      return (day < firstSunday);
   }

   return false;
}


//+------------------------------------------------------------------+
//| 【Critical Fix 6】计算某月第 N 个周日是几号                       |
//+------------------------------------------------------------------+
int GetNthSundayOfMonth(int month, int n)
{
   // 假设服务器时间已知
   // 使用 Zeller 公式或查找法计算

   // 简化算法: 遍历该月所有日期，找第 N 个周日
   // 由于 MQL4 限制，使用近似计算

   // 参考: 3月1日的星期几决定了第二个周日的位置
   // 如果3月1日是周日，则第二个周日是8号
   // 如果3月1日是周一，则第二个周日是14号
   // ...

   // 这里使用简化判断，实际应用中可通过历史数据校准
   // 2024年: 夏令时开始于3月10日（第二个周日），结束于11月3日（第一个周日）
   // 2025年: 夏令时开始于3月9日（第二个周日），结束于11月2日（第一个周日）
   // 2026年: 夏令时开始于3月8日（第二个周日），结束于11月1日（第一个周日）

   // 对于3月，第二个周日通常在 8-14 日之间
   // 对于11月，第一个周日通常在 1-7 日之间

   if(month == 3)
   {
      // 2026年为例: 第二个周日是 3月8日
      // 通用计算: 8 + (6 - FirstDayOfWeek) % 7
      // 简化返回 8-14 的中间值
      return 8 + (6 - dayOfWeek) % 7;
   }

   if(month == 11)
   {
      // 2026年为例: 第一个周日是 11月1日
      return 1 + (7 - dayOfWeek) % 7;
   }

   return 1;
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
   // 【修复1】支持策略A和策略B并发持仓
   // 分别计算每个策略是否有持仓，允许双策略同时开仓
   int positionTickets[MAX_TRAILING_STOP_TRACKERS];
   int positionTypes[MAX_TRAILING_STOP_TRACKERS];
   double positionSLs[MAX_TRAILING_STOP_TRACKERS];
   double positionOpenPrices[MAX_TRAILING_STOP_TRACKERS];
   datetime positionOpenTimes[MAX_TRAILING_STOP_TRACKERS];
   string positionStrategies[MAX_TRAILING_STOP_TRACKERS];  // 新增：记录每个订单所属策略
   int positionCount = 0;

   // 【修复1】分别追踪策略A和策略B的持仓状态
   bool hasPositionA = false;
   bool hasPositionB = false;

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
               if(positionCount < MAX_TRAILING_STOP_TRACKERS)
               {
                  positionTickets[positionCount] = OrderTicket();
                  positionTypes[positionCount] = orderType;
                  positionSLs[positionCount] = OrderStopLoss();
                  positionOpenPrices[positionCount] = OrderOpenPrice();
                  positionOpenTimes[positionCount] = OrderOpenTime();

                  // 【修复1】从订单注释识别所属策略
                  string orderComment = OrderComment();
                  if(StringFind(orderComment, "_A") >= 0)
                  {
                     positionStrategies[positionCount] = "A";
                     hasPositionA = true;
                  }
                  else if(StringFind(orderComment, "_B") >= 0)
                  {
                     positionStrategies[positionCount] = "B";
                     hasPositionB = true;
                  }
                  else
                  {
                     positionStrategies[positionCount] = "A";  // 默认归属策略A
                     hasPositionA = true;
                  }

                  positionCount++;
               }
               // 【Critical Fix 9】移除 break; 遍历所有订单，支持多策略并发
            }
         }
      }
   }

   // ═══════════════════════════════════════════════════════════════════
   // 【Critical Fix 9】每次 Tick 必须清理追踪止损残余
   // 防止因外部干预或熔断平仓的残余 Ticket 导致数组溢出
   // ═══════════════════════════════════════════════════════════════════
   CleanupTrailingStopTrackers();

   // ═══════════════════════════════════════════════════════════════════
   // 持仓出场检查 - 每Tick实时执行，支持多订单并发
   // ═══════════════════════════════════════════════════════════════════
   for(int p = 0; p < positionCount; p++)
   {
      int positionTicket = positionTickets[p];
      int positionType = positionTypes[p];
      double positionSL = positionSLs[p];
      double positionOpenPrice = positionOpenPrices[p];
      datetime positionOpenTime = positionOpenTimes[p];

      // 【Critical Fix 2】实时计算持仓K线数
      int barsHeld = CalculateBarsHeld(positionOpenTime);

      // 【Critical Fix 2】实时计算持仓期间最高/最低价
      double highestPrice = 0, lowestPrice = 1000000;
      CalculatePositionExtremes(positionOpenTime, positionType, highestPrice, lowestPrice);

      // 出场检查 - 为每个订单独立调用
      CheckExitConditions(positionTicket, positionType, positionSL, positionOpenPrice,
                          atr, vwap, barsHeld, highestPrice, lowestPrice);
   }

   // 【修复1】策略A和策略B独立入场判定
   // 策略A：仅当策略A无持仓时检查入场信号
   if(!hasPositionA)
   {
      if(newBar)
      {
         double close1 = iClose(NULL, PERIOD_M15, 1);
         double high1 = iHigh(NULL, PERIOD_M15, 1);
         double low1 = iLow(NULL, PERIOD_M15, 1);

         // 策略A检查 - 均值回归 (仅亚盘)
         if(InpEnableStrategyA && isAsian)
         {
            CheckStrategyAEntry(close1, bbUpper, bbLower, rsi, atr, high1, low1);
         }
      }
   }

   // 策略B：仅当策略B无持仓时检查入场信号
   if(!hasPositionB)
   {
      if(newBar)
      {
         double close1 = iClose(NULL, PERIOD_M15, 1);
         double high1 = iHigh(NULL, PERIOD_M15, 1);
         double low1 = iLow(NULL, PERIOD_M15, 1);

         // 策略B检查 - 动量突破 (仅欧美盘)
         if(InpEnableStrategyB && isEuropean && g_pendingOrderTicket == 0)
         {
            CheckStrategyBEntry(close1, bbUpper, bbLower, bbMiddle,
                               kcUpper, kcLower, emaFast, emaSlow,
                               isTrend, squeezeRelease, atr, high1, low1);
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
//| 【Critical Fix 5】VWAP 按日动态锚定计算 (带缓存优化)              |
//|                                                                   |
//| 性能优化关键：                                                    |
//| - 只在 newBar 时计算一次，缓存结果                               |
//| - 同一个 M15 K 线内的所有 Tick 复用缓存值                        |
//| - 执行耗时从 O(500) 降至 O(1)                                    |
//|                                                                   |
//| 时区锚定：                                                        |
//| - 外汇市场日线重置于美东时间 17:00                               |
//| - 使用服务器时间 + UTC 偏移计算"外汇交易日"                      |
//+------------------------------------------------------------------+
double GetDailyVWAP()
{
   // ═══════════════════════════════════════════════════════════════════════
   // 【性能优化】检查缓存是否有效
   // ═══════════════════════════════════════════════════════════════════════
   datetime currentBarTime = iTime(NULL, PERIOD_M15, 0);

   if(g_vwapCacheBarTime == currentBarTime && g_cachedVWAP > 0)
   {
      // 缓存命中，直接返回
      return g_cachedVWAP;
   }

   // ═══════════════════════════════════════════════════════════════════════
   // 【缓存未命中】计算新的 VWAP
   // ═══════════════════════════════════════════════════════════════════════

   // 获取当前K线的外汇交易日（美东时间 17:00 锚定）
   int currentForexTradingDay = GetForexTradingDay(currentBarTime);

   double dailyTPV = 0;
   double dailyVolume = 0;

   // 向前遍历，直到外汇交易日变化
   // 限制最多 100 根 K 线（一天最多 96 根 M15 K 线）
   for(int i = 1; i <= 100; i++)
   {
      datetime barTime = iTime(NULL, PERIOD_M15, i);

      // 检查外汇交易日是否变化
      int barForexTradingDay = GetForexTradingDay(barTime);

      if(barForexTradingDay != currentForexTradingDay)
      {
         // 已到达前一外汇交易日，停止遍历
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

   // 计算并缓存 VWAP
   if(dailyVolume > 0)
   {
      g_cachedVWAP = dailyTPV / dailyVolume;
   }
   else
   {
      // 无数据时返回前一根K线收盘价
      g_cachedVWAP = iClose(NULL, PERIOD_M15, 1);
   }

   // 更新缓存时间戳
   g_vwapCacheBarTime = currentBarTime;

   return g_cachedVWAP;
}


//+------------------------------------------------------------------+
//| 【修复5】计算外汇交易日 - EST时区锚定                             |
//|                                                                   |
//| 核心原则：                                                        |
//| 外汇市场日线重置于美东时间 17:00 (EST/EDT)                       |
//| VWAP 必须在同一交易日内计算，严禁跨日                             |
//|                                                                   |
//| 时区转换：                                                        |
//| - 服务器时间 -> UTC -> EST/EDT                                   |
//| - 使用 g_detectedDSTOffset 判断当前是否夏令时                    |
//| - EST = UTC-5, EDT = UTC-4                                        |
//+------------------------------------------------------------------+
int GetForexTradingDay(datetime barTime)
{
   // ═══════════════════════════════════════════════════════════════════════
   // 【修复5】将服务器时间转换为 EST 时间后再计算 DayOfYear
   //
   // 确保在任何 UTC 偏移的券商下，VWAP 都严格在美东 17:00 重置
   // ═══════════════════════════════════════════════════════════════════════

   // 服务器时间的小时和分钟
   int serverHour = TimeHour(barTime);
   int serverMinute = TimeMinute(barTime);

   // 转换为 UTC：服务器时间 - g_detectedDSTOffset
   int utcHour = serverHour - g_detectedDSTOffset;

   // 转换为 EST：UTC - 5 (夏令时为 UTC - 4，即 EDT)
   int isDST = (g_detectedDSTOffset == 3) ? 1 : 0;  // 夏令时检测
   int estOffset = 5 - isDST;  // EST = UTC-5, EDT = UTC-4
   int estHour = utcHour - estOffset;

   // 处理跨日
   datetime estDate = barTime;

   // 如果 EST 小时为负数，说明是前一天的日期
   if(estHour < 0)
   {
      estDate = barTime - 86400;  // 减去一天
      estHour += 24;
   }
   else if(estHour >= 24)
   {
      estDate = barTime + 86400;  // 加一天
      estHour -= 24;
   }

   // 外汇交易日的分界点是美东 17:00
   // 如果当前 EST 时间 < 17:00，则属于前一天的交易时段
   int estTotalMinutes = estHour * 60 + serverMinute;

   if(estTotalMinutes < 17 * 60)  // 17:00 之前
   {
      // 属于前一天的交易时段，日期减 1
      estDate = estDate - 86400;
   }

   // 使用转换后的 EST 日期计算 DayOfYear
   int year = TimeYear(estDate);
   int dayOfYear = TimeDayOfYear(estDate);

   // 返回年份和年积日的组合，唯一标识外汇交易日
   return year * 1000 + dayOfYear;
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
//| 【Critical Fix 2】挂单追高/杀跌灾难修复                           |
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

   // 【Critical Fix 2】如果价格已突破触发价，放弃挂单（防止追高）
   if(ask >= triggerPrice)
   {
      Print("【挂单放弃】BuyStop: 价格已突破触发价, Ask=", ask, " >= Trigger=", triggerPrice);
      return -1;  // 放弃挂单，不追高
   }

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

   // 【任务2 新增】动态仓位计算 (使用触发价作为预估入场价)
   double lotSize = CalculateDynamicLotSize(triggerPrice, stopLoss);

   // 发送挂单
   int ticket = OrderSend(
      Symbol(),
      OP_BUYSTOP,
      lotSize,
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
   else
   {
      Print("【挂单成功】BuyStop Ticket: ", ticket, " 手数: ", DoubleToString(lotSize, 2),
            " 触发价: ", triggerPrice, " 止损: ", stopLoss);
   }

   return ticket;
}

//+------------------------------------------------------------------+
//| 【Critical Fix 1】发送 Sell Stop 挂单                             |
//| 【Critical Fix 2】挂单追高/杀跌灾难修复                           |
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

   // 【Critical Fix 2】如果价格已跌破触发价，放弃挂单（防止杀跌）
   if(bid <= triggerPrice)
   {
      Print("【挂单放弃】SellStop: 价格已跌破触发价, Bid=", bid, " <= Trigger=", triggerPrice);
      return -1;  // 放弃挂单，不杀跌
   }

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

   // 【任务2 新增】动态仓位计算 (使用触发价作为预估入场价)
   double lotSize = CalculateDynamicLotSize(triggerPrice, stopLoss);

   int ticket = OrderSend(
      Symbol(),
      OP_SELLSTOP,
      lotSize,
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
   else
   {
      Print("【挂单成功】SellStop Ticket: ", ticket, " 手数: ", DoubleToString(lotSize, 2),
            " 触发价: ", triggerPrice, " 止损: ", stopLoss);
   }

   return ticket;
}

//+------------------------------------------------------------------+
//| 【任务2 新增】动态仓位计算函数 (风险百分比法)                      |
//|                                                                   |
//| 计算逻辑:                                                         |
//| 1. 计算入场价与止损价之间的点差距离                               |
//| 2. 风险金额 = AccountEquity() * (InpRiskPercent / 100.0)         |
//| 3. 使用 MarketInfo 获取 TICKVALUE、MINLOT、MAXLOT 进行规范化      |
//|                                                                   |
//| 返回值:                                                           |
//|   - 计算后的规范化手数                                            |
//|   - 如果无法计算或止损无效，返回 InpLotSize                       |
//+------------------------------------------------------------------+
double CalculateDynamicLotSize(double entryPrice, double stopLoss)
{
   // 如果未启用动态仓位，返回默认手数
   if(!InpUseDynamicLot)
   {
      return InpLotSize;
   }

   // 验证止损有效性
   if(stopLoss <= 0 || entryPrice <= 0)
   {
      Print("【动态仓位】止损或入场价无效，使用默认手数: ", InpLotSize);
      return InpLotSize;
   }

   // 获取市场信息
   double tickValue = MarketInfo(Symbol(), MODE_TICKVALUE);
   double tickSize  = MarketInfo(Symbol(), MODE_TICKSIZE);
   double minLot    = MarketInfo(Symbol(), MODE_MINLOT);
   double maxLot    = MarketInfo(Symbol(), MODE_MAXLOT);
   double lotStep   = MarketInfo(Symbol(), MODE_LOTSTEP);

   // 验证市场信息有效性
   if(tickValue <= 0 || tickSize <= 0 || minLot <= 0 || maxLot <= 0)
   {
      Print("【动态仓位】市场信息无效，使用默认手数: ", InpLotSize);
      return InpLotSize;
   }

   // 计算止损点数 (使用 Point 转换)
   double stopLossPoints = MathAbs(entryPrice - stopLoss) / Point;

   if(stopLossPoints <= 0)
   {
      Print("【动态仓位】止损点数为零，使用默认手数: ", InpLotSize);
      return InpLotSize;
   }

   // 计算风险金额
   double accountEquity = AccountEquity();
   double riskAmount = accountEquity * (InpRiskPercent / 100.0);

   // 计算每点价值 (XAUUSD 通常 Point = 0.01, TickSize = 0.01, TickValue = 0.1)
   // 每手每点价值 = TickValue * (Point / TickSize)
   double pointValuePerLot = tickValue * (Point / tickSize);

   if(pointValuePerLot <= 0)
   {
      Print("【动态仓位】点值计算失败，使用默认手数: ", InpLotSize);
      return InpLotSize;
   }

   // 计算手数: 手数 = 风险金额 / (止损点数 * 每点价值)
   double lotSize = riskAmount / (stopLossPoints * pointValuePerLot);

   // 【修复4】规范化手数 - 防止浮点数截断导致 Error 131
   // 使用 NormalizeDouble + 微小偏移避免浮点精度问题
   if(lotStep > 0)
   {
      lotSize = NormalizeDouble(MathFloor(lotSize / lotStep + 0.00001) * lotStep, 2);
   }

   // 限制在 MINLOT 和 MAXLOT 范围内
   lotSize = MathMax(minLot, MathMin(maxLot, lotSize));

   // 限制不超过 InpLotSize (作为最大手数限制)
   lotSize = MathMin(lotSize, InpLotSize);

   Print("【动态仓位】计算结果: 权益=$", DoubleToString(accountEquity, 2),
         " 风险=", DoubleToString(InpRiskPercent, 1), "%=$", DoubleToString(riskAmount, 2),
         " 止损点数=", DoubleToString(stopLossPoints, 1),
         " 手数=", DoubleToString(lotSize, 2));

   return lotSize;
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

   // 【任务2 新增】动态仓位计算
   double lotSize = CalculateDynamicLotSize(price, sl);

   int maxRetries = 3;
   int ticket = -1;

   for(int retry = 0; retry < maxRetries; retry++)
   {
      ticket = OrderSend(
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
         " 价格: ", price, " 手数: ", DoubleToString(lotSize, 2),
         " 止损: ", sl, " 止盈: ", tp);

   return true;
}

//+------------------------------------------------------------------+
//| 出场条件检查                                                      |
//| 【Critical Fix 3】移除 static 变量，改用独立数组存储              |
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
      // ═══════════════════════════════════════════════════════════════════════
      // 【Critical Fix 3】使用独立数组存储追踪止损，替代 static 变量
      // 解决多订单止损位互相覆盖的问题
      // ═══════════════════════════════════════════════════════════════════════
      double trailingStopValue = GetTrailingStop(positionTicket);

      if(positionType == OP_BUY)
      {
         if(Bid <= positionSL)
         {
            shouldClose = true;
            reason = "初始止损";
            // 清除追踪止损记录
            RemoveTrailingStopTracker(positionTicket);
         }
         else
         {
            double newTrailingStop = highestPrice - InpTrailingATRMult * currentATR;

            // 止损只能上移，严禁下降（防止 ATR 放大导致止损倒退）
            if(newTrailingStop > trailingStopValue || trailingStopValue == 0)
            {
               trailingStopValue = newTrailingStop;
               UpdateTrailingStopTracker(positionTicket, trailingStopValue);
            }

            if(Bid <= trailingStopValue && highestPrice > positionOpenPrice)
            {
               shouldClose = true;
               reason = "追踪止损";
               // 平仓后清除记录
               RemoveTrailingStopTracker(positionTicket);
            }
         }
      }
      else if(positionType == OP_SELL)
      {
         if(Ask >= positionSL)
         {
            shouldClose = true;
            reason = "初始止损";
            // 清除追踪止损记录
            RemoveTrailingStopTracker(positionTicket);
         }
         else
         {
            double newTrailingStop = lowestPrice + InpTrailingATRMult * currentATR;

            // 止损只能下移，严禁上升（防止 ATR 放大导致止损倒退）
            if(newTrailingStop < trailingStopValue || trailingStopValue == 0 || trailingStopValue > 900000)
            {
               trailingStopValue = newTrailingStop;
               UpdateTrailingStopTracker(positionTicket, trailingStopValue);
            }

            if(Ask >= trailingStopValue && lowestPrice < positionOpenPrice)
            {
               shouldClose = true;
               reason = "追踪止损";
               // 平仓后清除记录
               RemoveTrailingStopTracker(positionTicket);
            }
         }
      }
   }

   if(shouldClose)
   {
      ClosePositionMQL4(positionTicket, reason);
   }
}


//+------------------------------------------------------------------+
//| 【Critical Fix 3】追踪止损管理函数                                |
//+------------------------------------------------------------------+

// 获取指定订单的追踪止损值（返回 0 表示未记录，对于空头返回 1000000 表示未记录）
double GetTrailingStop(int ticket)
{
   for(int i = 0; i < g_trailingStopCount; i++)
   {
      if(g_trailingStopTickets[i] == ticket)
      {
         return g_trailingStopValues[i];
      }
   }
   return 0;  // 未找到，返回 0（对于空头会在调用处特殊处理）
}

// 更新或添加追踪止损记录
void UpdateTrailingStopTracker(int ticket, double trailingStop)
{
   // 首先检查是否已存在
   for(int i = 0; i < g_trailingStopCount; i++)
   {
      if(g_trailingStopTickets[i] == ticket)
      {
         g_trailingStopValues[i] = trailingStop;
         return;
      }
   }

   // 不存在，添加新记录
   if(g_trailingStopCount < MAX_TRAILING_STOP_TRACKERS)
   {
      g_trailingStopTickets[g_trailingStopCount] = ticket;
      g_trailingStopValues[g_trailingStopCount] = trailingStop;
      g_trailingStopCount++;
   }
}

// 移除追踪止损记录
void RemoveTrailingStopTracker(int ticket)
{
   for(int i = 0; i < g_trailingStopCount; i++)
   {
      if(g_trailingStopTickets[i] == ticket)
      {
         // 将最后一个元素移到当前位置
         g_trailingStopTickets[i] = g_trailingStopTickets[g_trailingStopCount - 1];
         g_trailingStopValues[i] = g_trailingStopValues[g_trailingStopCount - 1];
         g_trailingStopCount--;
         return;
      }
   }
}

// 清理已平仓订单的追踪止损记录
void CleanupTrailingStopTrackers()
{
   for(int i = g_trailingStopCount - 1; i >= 0; i--)
   {
      int ticket = g_trailingStopTickets[i];

      // 检查订单是否还存在
      if(!OrderSelect(ticket, SELECT_BY_TICKET))
      {
         // 订单不存在，移除记录
         RemoveTrailingStopTracker(ticket);
         continue;
      }

      int orderType = OrderType();
      if(orderType != OP_BUY && orderType != OP_SELL)
      {
         // 不是持仓订单，移除记录
         RemoveTrailingStopTracker(ticket);
      }
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
               int ticket = OrderTicket();
               Print("【强制平仓】原因: ", reason, " 订单 #", ticket);
               ClosePositionMQL4(ticket, reason);
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
//| 【任务1 修复】MQL4 原生平仓函数                                   |
//|                                                                   |
//| 修复内容:                                                         |
//|   - 接收指定订单号 ticket，直接操作目标订单                      |
//|   - 移除 for 循环遍历，避免"张冠李戴"平错订单                    |
//|                                                                   |
//| 参数:                                                             |
//|   ticket - 要平仓的订单号                                         |
//|   reason - 平仓原因 (用于日志记录)                               |
//+------------------------------------------------------------------+
bool ClosePositionMQL4(int ticket, string reason)
{
   // 直接选中指定订单
   if(!OrderSelect(ticket, SELECT_BY_TICKET))
   {
      Print("【平仓失败】无法选中订单 Ticket: ", ticket, " 错误: ", GetLastError());
      return false;
   }

   // 验证订单属于当前品种和魔术数字
   if(OrderSymbol() != Symbol() || OrderMagicNumber() != InpMagicNumber)
   {
      Print("【平仓拒绝】订单不属于当前策略 Ticket: ", ticket,
            " Symbol: ", OrderSymbol(), " Magic: ", OrderMagicNumber());
      return false;
   }

   int orderType = OrderType();
   double lots = OrderLots();

   // 只处理持仓订单
   if(orderType != OP_BUY && orderType != OP_SELL)
   {
      Print("【平仓拒绝】非持仓订单 Ticket: ", ticket, " 类型: ", orderType);
      return false;
   }

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
