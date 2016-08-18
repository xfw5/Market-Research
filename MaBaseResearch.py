# https://github.com/xfw5/Market-Research/blob/master/MaBaseResearch.py
# 修改记录：
# -2016-8-18
# 1.引入Cache，解决GetCurrentPrice和GetCurrentMarketCap调用消耗过大的问题，目前性能上提升67%
# 2.为仓位水平添加误差容忍度
# 3.将所有的默认设置从Option中抽出来
#
# -2016-8-17
# 1. 修正涨跌幅度的计算，统一使用涨跌幅度的百分比来衡量个股的变化。
# 2. 分别为是否过滤涨停和跌停设置开关
# 3. 每次每股买入时，添加仓位检测，避免买入第N股时，仓位过高
# 4. 调整ClampOrderValue函数，估算100股的总价时，默认溢出20股。
#    实际交易（必须是100的倍数）会自动平掉该溢出的20股
# 5. 添加WaterLine类，当到达设置的水位时，触发信号，通知监听者某个事件已发生
# 6. 添加SecurityProfitStatus，监视所持有的个股的盈利状态，并触发相应策略处理事件。
#
# -2016-8-15
# 1.将买入个股的前提条件从选股的过滤规则中分离出来
# 2.对所有满足买入条件的个股，按照期望涨幅排序，优先买入符合理想条件的个股。
#   如果此时仍然无法满足仓位要求， 将会按照设置的最低和最大上下线买入，直到满足为止。
#   如果仍然没有满足，说明策略有缺陷，此时应该调整买入个股策略的涨幅上下限，或者添加其他备选方案。
#
# -2016-8-12
# 1.添加选股过滤条件：去掉未上市、停牌的个股
# 2.添加买股过滤条件：去掉涨停、跌停的个股（涨停价与当前市场价的阀值Delta=当前价格的0.05，
#                     即是如果当前市场价和涨停价相差Delta，则认为该股已经涨停）
# 3.当前市场价：使用get_price函数，代替data和get_current_data()
# 如果按分钟回测，get_price更为精准，只是这个API的调用比较耗。
# 如果按天回测，这个API的数据就是前一天的收盘数据，因此效果跟data和get_current_data()无区别。
#
# 已知问题：
# 1. 资金分为十份，理想状态每股一份。但由于个股买进的时候价格的差异，会导致在保持
#    某个仓位水平的前提下，已经持有10股了。如果这个时候，看好市场，需要提高仓位，就会导致
#    无法买进，因为这个时候持有的股票已经到达上限。
#
# 奇怪现象：
# 1.某个时间点，获取到的个股的数据跟交易软件里看到的数据不一样，而且差距很大，但有些时间段又是正确
#  例如平安银行2016-6-1的数据不一致，2016-7-13的数据一致

# 性能分析，如果不需要，请屏蔽该行
enable_profile()

# 调试信息开关
Debug_On = True

# 默认选股策略值
DEF_FILTER_ST = True  # 是否过滤ST
DEF_FILTER_LIMIT_UP = True  # 是否过滤涨停
DEF_FILTER_LIMIT_DOWN = False  # 是否过滤跌停
DEF_LIMIT_TOLERANCE_PRECENT = 0.01  # 涨跌停容忍度
DEF_MARKET_CAP_MIN = 0  # 最低市值
DEF_MARKET_CAP_MAX = 3000  # 最高市值

# 默认买入策略值
DEF_FILTER_HOLDING_SECURITIES = True  # 是否过滤已经持有的个股
DEF_MA_SAMPLING_DAYS_FOR_SECURITY = 5  # 个股均线采样时间
DEF_CHANGE_PERCENT_LOW = 1  # 最低涨幅
DEF_CHANGE_PERCENT_HIGH = 11  # 最高涨幅
# 期望买入涨幅点，优先买入该涨幅点至最高涨幅点之间的个股，
# 如果不足，使用该涨幅点至其次最低涨幅之间的个股来补充。
DEF_CHANGE_PERCENT_DESIRE = 3

# 默认资金管理策略值
DEF_CAP_TOTAL_SHARE = 10  # 资金总共分为几份
DEF_CAP_SHARE_PRE_STOCK = 1  # 每支股票配多少份
DEF_CAP_STOPLOSS_THRESHOLD = 5 * 0.01  # 个股止损阀值
DEF_TOTAL_OPENING_POSITION_PRE_DAY = 2  # 每次开仓的数量，按多少支个股来衡量

# 默认盈利点信号值
DEF_PROFIT_LINE_HIGH = 15  # 最高盈利点
DEF_PROFIT_LINE_LOW = 10  # 最低盈利点

DEF_WATER_LINE = 15  # 默认水位

# 默认大盘策略值
DEF_MARKET_INDEX = '000001.XSHG'
DEF_MARKET_MA_SAMPLING_DAYS_1 = 20  # 第一条均线为20日均线
DEF_MARKET_MA_SAMPLING_DAYS_2 = 60  # 第二条均线为60日均线
DEF_POSITION_IF_MMA_BREAKOUT_LINE1 = 0.6  # 突破第一条均线时，保持仓位在6成
DEF_POSITION_IF_MMA_BREAKOUT_LINE2 = 0.8  # 突破第二条均线时，保持仓位在8成
DEF_POSITION_IF_MMA_FALLINGDOWN_LINE1 = 0.2  # 跌破第一条均线，保持仓位在2成
DEF_POSITION_IF_MMA_FALLINGDOWN_LINE2 = 0.0  # 跌破第二条均线，保持仓位在0成

# 仓位误差的容忍阀值
POSITION_TOLERANCE = 0.05


# 调试信息的级别，级别越高，信息越明显
def PD(level, *msg):
    if Debug_On:
        if level == 0:
            log.info(*msg)
        elif level == 1:
            log.warn(*msg)
        elif level == 2:
            log.error(*msg)


# 滑动条函数，返回一个处于min和max之间的数。
def Clamp(value, min, max):
    if value < min:
        return min
    elif value > max:
        return max
    return value


# 判断输入值（inputValue）是否在测量值（measure）可以容忍的误差（tolerance）之内
def IsHit(inputValue, measure, tolerance):
    return abs(inputValue - measure) < tolerance


class CacheInfo:
    Security = ''
    MakretCap = -1
    CurrentPrice = -1

    def __init__(self, security, marketCap=-1, currentPrice=-1):
        self.Security = security
        self.MarketCap = marketCap
        self.CurrentPrice = currentPrice


class CacheHandler:
    Cache = {}

    def __init__(self):
        self.Cache = {}

    def CacheCurrentPrice(self, securities, currentDate):
        panel = get_price(securities, end_date=currentDate, fields=['close'], frequency='1m', count=1)
        closePD = panel['close']
        for security in securities:
            info = self.Cache.get(security)
            if not info: info = CacheInfo(security)
            info.CurrentPrice = closePD[security][0]
            self.Cache[security] = info

    def CacheMarketCap(self, securities, currentDate):
        q = query(
            valuation.code, valuation.market_cap
        ).filter(
            valuation.code.in_(securities)
        )

        df = get_fundamentals(q, currentDate)
        if not df.empty:
            for oneline in df.values:
                security = oneline[0]
                cap = oneline[1]
                info = self.Cache.get(security)
                if not info: info = CacheInfo(security)
                info.MarketCap = cap
                self.Cache[security] = info


CacheHolder = CacheHandler()


# 选股策略
class SecuritiesSelectionFilterOption:
    Filter_ST = DEF_FILTER_ST  # 是否过滤ST
    FilterLimitUP = DEF_FILTER_LIMIT_UP  # 是否过滤涨停的个股
    FilterLimitDown = DEF_FILTER_LIMIT_DOWN  # 是否过滤跌停的个股

    LimitToleranceInPercentage = DEF_LIMIT_TOLERANCE_PRECENT  # 涨跌停价格差的容忍度：为当前价格的百分比

    MarketCapitalMin = DEF_MARKET_CAP_MIN  # 市值下限
    MarketCapitalMax = DEF_MARKET_CAP_MAX  # 市值上限

    def __init__(self, filter_ST=DEF_FILTER_ST, filterLimitUp=DEF_FILTER_LIMIT_UP, \
                 filterLimitDown=DEF_FILTER_LIMIT_DOWN, toleranceInPercentage=DEF_LIMIT_TOLERANCE_PRECENT, \
                 marketCapitalMin=DEF_MARKET_CAP_MIN, marketCapitalMax=DEF_MARKET_CAP_MAX):
        self.Filter_ST = filter_ST
        self.FilterLimitUp = filterLimitUp
        self.FilterLimitDown = filterLimitDown
        self.LimitToleranceInPercentage = toleranceInPercentage
        self.MarketCapitalMin = marketCapitalMin
        self.MarketCapitalMax = marketCapitalMax


# 买入策略
class SecuritiesOrderInFilterOption:
    FilterHoldingSecurities = DEF_FILTER_HOLDING_SECURITIES  # 是否过滤掉已经持有的个股

    MaSamplingDays = DEF_MA_SAMPLING_DAYS_FOR_SECURITY  # 个股均线采样时间

    # 百分比数值
    ChangePercentLow = DEF_CHANGE_PERCENT_LOW  # 涨幅下限
    ChangePercentHigh = DEF_CHANGE_PERCENT_HIGH  # 涨幅上限
    ChangePercentDesire = DEF_CHANGE_PERCENT_DESIRE  # 希望买进的涨幅点

    def __init__(self, filterHoldingSecurities=DEF_FILTER_HOLDING_SECURITIES,
                 maSamplingDays=DEF_MA_SAMPLING_DAYS_FOR_SECURITY, \
                 changePercentLow=DEF_CHANGE_PERCENT_LOW, changePercentHigh=DEF_CHANGE_PERCENT_HIGH,
                 changePercentDesire=DEF_CHANGE_PERCENT_DESIRE):
        self.FilterHoldingSecurities = filterHoldingSecurities
        self.MaSamplingDays = maSamplingDays
        self.ChangePercentLow = changePercentLow
        self.ChangePercentHigh = changePercentHigh
        self.ChangePercentDesire = changePercentDesire


# 资金管理策略
class CapitalManagerOption:
    TotalShare = DEF_CAP_TOTAL_SHARE  # 资金分割等份
    SharesPreStock = DEF_CAP_SHARE_PRE_STOCK  # 按份配股：每支股票配多少份(share)
    StopLossThreshold = DEF_CAP_STOPLOSS_THRESHOLD  # 个股止损阀值
    MaSamplingDaysForStock = DEF_MA_SAMPLING_DAYS_FOR_SECURITY  # 个股均线采样时间
    TotalOpenPositionPreDay = DEF_TOTAL_OPENING_POSITION_PRE_DAY  # 每天最大开仓的数量

    def __init__(self, totalShare=DEF_CAP_TOTAL_SHARE, sharesPreStock=DEF_CAP_SHARE_PRE_STOCK,
                 stopLossThreshold=DEF_CAP_STOPLOSS_THRESHOLD, \
                 maSamplingDaysForStock=DEF_MA_SAMPLING_DAYS_FOR_SECURITY,
                 totalOpenPositionPreDay=DEF_TOTAL_OPENING_POSITION_PRE_DAY):
        self.TotalShare = totalShare
        self.SharesPreStock = sharesPreStock
        self.StopLossThreshold = stopLossThreshold
        self.MaSamplingDaysForStock = maSamplingDaysForStock
        self.TotalOpenPositionPreDay = totalOpenPositionPreDay


# 水位,一般用来设置个股的上涨或下跌的警告线
class WaterLine:
    Line = DEF_WATER_LINE  # 设置的目标水位
    IsReverse = False  # 是否反转，默认为False，表示高于设置的水位时，IsHit状态为True，否则低于水位时，才设置IsHit状态

    Active = False  # 激活状态
    IsHit = False  # 水位是否超过设置的Line
    HighestHit = Line  # 历史最高水位，辅助信息，用来跟踪某段时间内最高或最低的水位

    def __init__(self, line, isReverse, active):
        self.Line = line
        self.IsReverse = isReverse
        self.IsHit = False
        self.Active = active
        self.HighestHit = self.Line

    def Reset(self, active=False):  # 重置水位
        self.IsHit = False
        self.Active = active
        self.HighestHit = self.Line

    def Update(self, newLine):  # 更新水位
        if self.Active and self.__isHitWithLine(newLine):
            self.IsHit = True
            self.__updateHighestHitLine()

    def __isHitWithLine(self, line):  # 私有函数，测试水位是否溢出
        if self.IsReverse:
            return line < self.Line
        else:
            return line > self.Line

    def __updateHighestHitLine(self, line):  # 私有函数，测试历史最高水位是否需要更新
        if self.IsReverse:
            if line < self.HighestHit: self.HighestHit = line
        else:
            if line > self.HighestHit: self.HighestHit = line


# 个股盈利状态跟踪
class SecurityProfitStatus:
    Security = ''  # 个股ID

    HighLimitLine = WaterLine(DEF_PROFIT_LINE_HIGH, False, True)  # 设置个股盈利最高水位
    LowLimitLine = WaterLine(DEF_PROFIT_LINE_LOW, False, False)  # 设置个股盈利最低水位

    # 当个股盈利到达最高水位后，如果盈利下跌到设置的最低值，发出该信号。
    _signalRaised = False

    def __init__(self, security, highLine, lowLine):
        self.Security = security
        self.HighLimitLine = highLine
        self.LowLimitLine = lowLine

    def Update(self, profit, clearStatus=False):
        self.HighLimitLine.Update(profit)
        if self.HighLimitLine.IsHit:
            self.LowLimitLine.Active = True

        self.LowLimitLine.Update(profit)

        self._signalRaised = not self.HighLimitLine.IsHit and self.LowLimitLine.IsHit
        if self._signalRaised:
            PD(1, 'Security Profit signal raised:', self.Security)
        if ClearStatus: self.ClearStatus()
        return self._signalRaised

    def IsSignalRaisedUp(self, isClear):
        raised = self._signalRaised
        if isClear: self.ClearStatus()
        return raised

    def ClearStatus(self):
        self.HighLimitLine.Reset(True)
        self.LowLimitLine.Reset(False)


# 自定义的个股排名信息
class OrderRankInfo:
    Flow = 0
    Security = ''

    def __init__(self, flow, security):
        self.Flow = flow
        self.Security = security

    @staticmethod
    def PrintList(rankList):
        if type(rankList) == list:
            for info in rankList:
                PD(0, info.Security, info.Flow)


# 选股处理（包括选股、买入、卖出）
class SecuritiesFilter:
    _selectFilterOpt = SecuritiesSelectionFilterOption()  # 选股
    _orderInFilterOpt = SecuritiesOrderInFilterOption()  # 买入

    def __init__(self, selectFilterOption, orderInFilterOption):
        self._selectFilterOpt = selectFilterOption
        self._orderInFilterOpt = orderInFilterOption

    # 筛选目标个股
    def OnFilterSelect(self, securities, context, data):
        currrentDate = context.current_dt.strftime("%Y-%m-%d")
        target_securities = []

        for security in securities:
            currentData = get_current_data()
            securityStatus = currentData[security]

            # 过滤掉停牌的个股
            if securityStatus.paused: continue

            # 如果是ST牌，过滤掉
            if self._selectFilterOpt.Filter_ST and securityStatus.is_st: continue

            # 如果市值低于marketCapMin，过滤掉
            # 如果市值高于marketCapMax，过滤掉
            currentMarketCap = GetCurrentMarketCap(security, currrentDate)
            if currentMarketCap < self._selectFilterOpt.MarketCapitalMin or \
                            currentMarketCap > self._selectFilterOpt.MarketCapitalMax: continue

            target_securities.append(security)

        # 根据策略决定是否去掉涨停、跌停的个股
        target_securities = SecurityHandler.FilterLimitStocks(target_securities, self._selectFilterOpt, context)
        return target_securities

    # 筛选符合买入策略的个股
    def OnFilterOrderIn(self, securities, holdingSecurities, context, data):
        target_securities = []

        for security in securities:
            securityData = data[security]
            currentPrice = securityData.close
            prePrice = securityData.pre_close

            # 涨跌幅
            changePercentage = (currentPrice - prePrice) / prePrice * 100

            # 均线
            ma = securityData.mavg(self._orderInFilterOpt.MaSamplingDays, 'close')

            # 如果当前价格低于MA日均线或高于均线过多，过滤掉
            if ma < currentPrice or ma > currentPrice * 1.1: continue

            # 如果涨幅低于或者高于ChangePercentLow/High， 过滤掉
            if changePercentage < self._orderInFilterOpt.ChangePercentLow or \
                            changePercentage > self._orderInFilterOpt.ChangePercentHigh: continue

            target_securities.append(security)

        if self._orderInFilterOpt.FilterHoldingSecurities:
            target_securities = SecurityHandler.FilterHoldingStocks(target_securities, holdingSecurities)
        return target_securities

    # 根据期望的涨幅点对所有符合条件的待买入的个股排序
    def OnRankByOrderInOption(self, securities, data, measure=None):
        if securities and len(securities) > 0:
            if measure == None: measure = self._orderInFilterOpt.ChangePercentDesire

            flowList = []
            lossList = []
            for security in securities:
                flow = SecurityHandler.GetChangePercent(security, data)
                if flow >= measure:
                    flowList.append(OrderRankInfo(flow, security))
                else:
                    lossList.append(OrderRankInfo(flow, security))

            # 高于测量值：从低到高排序(如：0, 1，2...)
            flowList.sort(lambda x, y: cmp(x.Flow, y.Flow), reverse=False)
            # 低于测量值：从高到低(如：-1, -2, -3...)
            lossList.sort(lambda x, y: cmp(x.Flow, y.Flow), reverse=True)
            flowList.extend(lossList)

            return flowList


# 大盘信息
class MarketInfo:
    Ma_1 = 0  # 大盘第一条均线
    Ma_2 = 0  # 大盘第二条均线

    MA_SAMPLING_DAYS_1 = DEF_MARKET_MA_SAMPLING_DAYS_1
    MA_SAMPLING_DAYS_2 = DEF_MARKET_MA_SAMPLING_DAYS_2

    _current_price = 0  # 大盘当前市场价
    _market_index = DEF_MARKET_INDEX  # 大盘指数ID

    # 初始化函数，类似C++的构造函数，当声明该类时，自动被调用
    def __init__(self, marketIndex=DEF_MARKET_INDEX, maSamplingDays_1=DEF_MARKET_MA_SAMPLING_DAYS_1, \
                 maSamplingDays_2=DEF_MARKET_MA_SAMPLING_DAYS_2):
        # 检测markIndex参数是否是一个basestring类型的实例
        if isinstance(marketIndex, basestring):
            self._market_index = marketIndex
            self.MA_SAMPLING_DAYS_1 = maSamplingDays_1
            self.MA_SAMPLING_DAYS_2 = maSamplingDays_2

    # 打印调试信息
    def PrintInfo(self):
        PD(0, '[Market]current price:', self._current_price, 'Ma', self.MA_SAMPLING_DAYS_1, ':', \
           self.Ma_1, 'Ma', self.MA_SAMPLING_DAYS_2, ':', self.Ma_2)

    # 实时获取当前大盘市场价
    def GetMarketPrice(self, context):
        self._current_price = GetCurrentPrice(self._market_index, context.current_dt)
        return self._current_price

    # 更新日均线，按天调度
    def RefreshMa(self):
        self.Ma_1 = GetMarketMaIndexByDay(self._market_index, self.MA_SAMPLING_DAYS_1, 'close')
        self.Ma_2 = GetMarketMaIndexByDay(self._market_index, self.MA_SAMPLING_DAYS_2, 'close')


# 个股操作
class SecurityHandler:
    # 个股是否符合卖出条件
    @staticmethod
    def IsNeedSellOff(position, context, data, profitHolder, MaSamplingDays, stopLossThreshold):
        security = data[position.security]
        current_price = GetCurrentPrice(position.security, context.current_dt)
        Ma = security.mavg(MaSamplingDays, 'close')
        flow = position.price - position.avg_cost

        if current_price < Ma:
            PD(0, '[IsNeedSellOff] Less then Ma[', MaSamplingDays, ']:', position.security)
            return True

        flowPercentage = -flow / position.avg_cost
        if flow < 0 and flowPercentage > stopLossThreshold:
            PD(0, '[IsNeedSellOff] Stop loss hit:', flow, flowPercentage, position.security)
            return True

        profitStatus = profitHolder.get(security)
        if profitStatus:
            return profitStatus.Update(flow, True)

        return False

    # 个股是否符合买入条件
    @staticmethod
    def IsNeedOrderIn(context, data, stockCode, MaSamplingDays, flowingThresholdMin, flowingThresholdMax):
        return True

    # 按照当前市场价计算购买个股Amount数量所需要的资金
    @staticmethod
    def GetOrderCurrentValue(data, security, amount=100):
        return amount * data[security].close

    # 根据现金流，动态调整下单的金额，使得下单的金额永远满足大于100单（大于100单才能交易）
    @staticmethod
    def ClampOrderValue(data, security, desireValue, cash, flow=20):
        if cash < desireValue:
            PD(2, 'Cash no enough: ', cash, ' Desire order: ', desireValue)
            return desireValue

        oneDeal = SecurityHandler.GetOrderCurrentValue(data, security, 100 + flow)
        return Clamp(desireValue, oneDeal, cash)

    @staticmethod
    def GetChangePercent(security, data):
        securityData = data[security]
        currentPrice = securityData.close
        prePrice = securityData.pre_close
        return (currentPrice - prePrice) / prePrice * 100

    # 过滤掉已经持有的股票
    @staticmethod
    def FilterHoldingStocks(targetSecurities, holdingStocks):
        filterResults = []

        for stock in targetSecurities:
            if not holdingStocks.has_key(stock):
                filterResults.append(stock)

        # if len(targetSecurities) != len(filterResults):
        #     PD(0, 'before holding filter:', targetSecurities)
        #     PD(0, 'after holding filter:', filterResults)

        return filterResults

    # 过滤掉涨停、跌停的个股
    @staticmethod
    def FilterLimitStocks(targetSecurities, filterOption, context):
        if not filterOption.FilterLimitUp and not filterOption.FilterLimitDown: return targetSecurities

        filterResults = []
        cd = get_current_data()

        for stock in targetSecurities:
            currentPrice = GetCurrentPrice(stock, context.current_dt)
            high_limit = cd[stock].high_limit
            low_limit = cd[stock].low_limit

            # 设置涨停（跌停）与当前价格之间的允许波动阀值，为当天开盘价的0.01
            tolerance = cd[stock].day_open * filterOption.LimitToleranceInPercentage

            # 高于涨停或接近涨停容忍度，过滤掉
            if filterOption.FilterLimitUp:
                if currentPrice >= high_limit or high_limit - currentPrice < tolerance: continue

            # 低于跌停或接近跌停容忍度，过滤掉
            if filterOption.FilterLimitDown:
                if currentPrice <= low_limit or currentPrice - low_limit < tolerance: continue

            filterResults.append(stock)

        # if len(targetSecurities) != len(filterResults):
        #     PD(0, 'before limit filter:', targetSecurities)
        #     PD(0, 'after limit filter:', filterResults)
        return filterResults

    # 记录交易、下单信息
    @staticmethod
    def RecordOrder(title, msg, orderStatus):
        record(title=orderStatus.amount)
        log.info(msg, '[' + orderStatus.security + ']:', orderStatus.status, \
                 ' mount:', orderStatus.amount, 'Price:', orderStatus.price, 'avg_cost:', orderStatus.avg_cost)


# 资金管理
class CapitalManager:
    CMOption = CapitalManagerOption()
    ProfitHolder = {}
    _securitiesFilter = SecuritiesFilter('', '')  # 策略过滤器

    _currentCapitalPosition = 0.0  # 当前仓位

    def __init__(self, managerOption, securitiesFilter):
        if isinstance(managerOption, CapitalManagerOption) and \
                isinstance(securitiesFilter, SecuritiesFilter):
            self.CMOption = managerOption
            self._securitiesFilter = securitiesFilter

    # 更新仓位
    def UpdateCapital(self, context):
        cash = context.portfolio.cash
        capital_used = context.portfolio.capital_used
        portfolio_value = context.portfolio.portfolio_value
        self._currentCapitalPosition = capital_used / (capital_used + cash)

        PD(0, 'portfolio: ', portfolio_value, 'Current cash:', cash, 'used:', capital_used, 'position: ',
           self._currentCapitalPosition)

    # 打开盈利监视器
    def ActiveProfitMonitor(self, positions):
        securities = positions.values()
        for security in securities:
            profitStatus = self.ProfitHolder.get(security)
            if profitStatus:
                profitStatus = SecurityProfitStatus()
                self.ProfitHolder[security] = profitStatus

        for security in self.ProfitHolder.keys():
            if not positions.has_key(security):
                del self.ProfitHolder[security]

    # 检测是否有股票需要止损
    def StopLoss(self, context, data):
        positions = context.portfolio.positions.values()

        if len(positions) > 0:
            self.OnActionStopLoss(positions, context, data)

    # 保持仓位在position水平
    def TryHoldingOnPosition(self, context, data, desirePosition, isBullish):
        self.UpdateCapital(context)

        if self._currentCapitalPosition > desirePosition and isBullish == False:
            self.OnActionBearishHandle(context, data, desirePosition)  # 熊市
        elif self._currentCapitalPosition < desirePosition and isBullish:
            self.OnActionBullishHandle(context, data, desirePosition)  # 牛市

        if IsHit(self._currentCapitalPosition, desirePosition, POSITION_TOLERANCE):
            PD(1, 'Try holding position FAILED, desire:', desirePosition, 'current:', self._currentCapitalPosition)

    # 看涨，
    # @desirePosition：希望保持的仓位水平
    def OnActionBullishHandle(self, context, data, desirePosition):
        PD(1, 'Bullish: try holding position on: ', desirePosition)

        # 获取当前持有的股票
        currentHoldingStocks = len(context.portfolio.positions.values())
        # # 计算当前允许新开仓的个股数量
        # availShare = self.CMOption.TotalShare - currentHoldingStocks

        # # 如果开仓的个股已经达到上限
        # if availShare == 0:
        #     PD(2, 'Full opening position.')
        #     self.UpdateCapital(context)
        #     return

        # 更新资金
        self.UpdateCapital(context)

        # 取得符合买进条件的所有个股
        stocks = context.target_securities
        if len(stocks) <= 0: return

        # 计算应该需要补多少仓
        fillingPosition = desirePosition - self._currentCapitalPosition
        # 计算该次补仓所需要的资金
        desireTotalOrderCash = (context.portfolio.capital_used + context.portfolio.cash) * fillingPosition
        # 计算每股的平均资金
        orderCashPreStock = desireTotalOrderCash / self.CMOption.TotalOpenPositionPreDay

        # 过滤掉已经持有的个股
        backupSecurities = self._securitiesFilter.OnFilterOrderIn(stocks, context.portfolio.positions, context, data)

        # 如果没有符合条件的个股，直接返回
        if len(backupSecurities) <= 0: return

        # 按照期望的涨幅排序：小->大
        targetSecurities = self._securitiesFilter.OnRankByOrderInOption(backupSecurities, data)
        # PD(0, 'Backup order in stocks:')
        # OrderRankInfo.PrintList(targetSecurities)

        openPositionCount = 0
        # 从备选股中，开仓
        for info in targetSecurities:
            security = info.Security
            # 如果达到或接近仓位水平
            if IsHit(self._currentCapitalPosition, desirePosition, POSITION_TOLERANCE): break
            # 如果达到开仓数量，而仓位还没有满足要求
            if openPositionCount >= self.CMOption.TotalOpenPositionPreDay:
                PD(1, 'Opening position has reached max setting, but capital position still under require:',
                   self._currentCapitalPosition)

            # 按照当前市场价，计算下单的金额
            finalValue = SecurityHandler.ClampOrderValue(data, security, orderCashPreStock, context.portfolio.cash)
            orderStatus = order_target_value(security, finalValue, MarketOrderStyle())
            if orderStatus:
                SecurityHandler.RecordOrder('OpenPosition', 'OpenPosition', orderStatus)
                # 如果下单成功，增加开仓计数器，以保证每天的开仓数量
                if orderStatus.status == OrderStatus.held:
                    openPositionCount = openPositionCount + 1
                self.UpdateCapital(context)
        self.ActiveProfitMonitor(context.portfolio.positions)

    # 看跌
    def OnActionBearishHandle(self, context, data, position):
        PD(1, 'Bearish: try cutdown position on: ', position)

        self.UpdateCapital()
        positions = context.portfolio.positions.values()

        # 根据收益，对持有的个股排序
        positions.sort(lambda x, y: cmp(x.price - x.avg_cost, y.price - y.avg_cost), reverse=True)

        # 在保证仓位水平的前提下，优先卖掉获利最多的股票
        self.OnActionStopLossByPosition(positions, context, position)
        # 在保证仓位水平的前提下，卖掉需要止损的股票
        self.OnActionStopLoss(positions, context, data)

    # 根据期望的仓位平仓
    def OnActionStopLossByPosition(self, positions, context, data, stopLossPoint):
        while IsHit(self._currentCapitalPosition, stopLossPoint, POSITION_TOLERANCE) and len(positions) > 0:
            position = positions[0]
            orderStatus = order_target(position.security, 0, MarketOrderStyle())
            positions.remove(position)
            self.UpdateCapital()

    # 平掉所有需要止损的个股
    def OnActionStopLoss(self, positions, context, data):
        PD(0, 'OnActionStopLoss')

        while len(positions) > 0:
            position = positions[0]

            if SecurityHandler.IsNeedSellOff(position, context, data, self.ProfitHolder, \
                                             self.CMOption.MaSamplingDaysForStock, self.CMOption.StopLossThreshold):
                orderStatus = order_target(position.security, 0, MarketOrderStyle())
                if orderStatus:
                    SecurityHandler.RecordOrder('StopLoss', 'StopLoss', orderStatus)
            positions.remove(position)

    # 无条件清仓
    def OnActionSellOff(self, context):
        for position in context.portfolio.positions.values():
            orderStatus = order_target(position.security, 0, MarketOrderStyle())
            if orderStatus:
                SecurityHandler.RecordOrder('SellOff', 'SellOff', orderStatus)

    # 卖掉所有盈利的个股
    def OnActionSellOffOverflowOnly(self, context):
        positions = context.portfolio.positions.values()

        # 按照盈利排序:大->小
        positions.sort(lambda x, y: cmp(x.price - x.avg_cost, y.price - y.avg_cost), reverse=True)

        for position in positions:
            # 如果盈利，清掉
            if position.price - x.avg_cost > 0:
                orderStatus = order_target(position.security, 0, MarketOrderStyle())
                if orderStatus:
                    SecurityHandler.RecordOrder('SellOffOverflowOnly', 'SellOffOverflowOnly', orderStatus)
            else:
                break

    # 卖掉所有不盈利的个股
    def OnActionSellOffLossOnly(self, context):
        positions = context.portfolio.positions.values()

        # 按照盈利排序： 小->大
        positions.sort(lambda x, y: cmp(x.price - x.avg_cost, y.price - y.avg_cost))

        for position in positions:
            # 如果不盈利，清掉
            if position.price - x.avg_cost < 0:
                orderStatus = order_target(position.security, 0, MarketOrderStyle())
                if orderStatus:
                    SecurityHandler.RecordOrder('SellOffLossOnly', 'SellOffLossOnly', orderStatus)
            else:
                break


# 市场信息处理
class MarketInfoHandler:
    _marketInfo = MarketInfo('')  # 大盘信息
    _capitalManager = CapitalManager('', '')  # 资金管理

    PositionIfBreakoutLine1 = DEF_POSITION_IF_MMA_BREAKOUT_LINE1
    PositionIfBreakoutLine2 = DEF_POSITION_IF_MMA_BREAKOUT_LINE2
    PositionIfFallingdownLine1 = DEF_POSITION_IF_MMA_FALLINGDOWN_LINE1
    PositionIfFallingdownLine2 = DEF_POSITION_IF_MMA_FALLINGDOWN_LINE2

    def __init__(self, market, capitalManager,
                 positionIfBreakoutLine1=DEF_POSITION_IF_MMA_BREAKOUT_LINE1, \
                 positionIfBreakoutLine2=DEF_POSITION_IF_MMA_BREAKOUT_LINE2, \
                 positionIfFallingdownLine1=DEF_POSITION_IF_MMA_FALLINGDOWN_LINE1, \
                 positionIfFallingdownLine2=DEF_POSITION_IF_MMA_FALLINGDOWN_LINE2):
        if isinstance(market, MarketInfo) and \
                isinstance(capitalManager, CapitalManager):
            self._marketInfo = market
            self._capitalManager = capitalManager
            self.PositionIfBreakoutLine1 = positionIfBreakoutLine1
            self.PositionIfBreakoutLine2 = positionIfBreakoutLine2
            self.positionIfFallingdownLine1 = positionIfFallingdownLine1
            self.PositionIfFallingdownLine2 = positionIfFallingdownLine2

    # 根据策略处理市场信息
    def Execute(self, context, data):
        # 获取当前最新的市场价格
        currentMarketPrice = self._marketInfo.GetMarketPrice(context)

        self._marketInfo.PrintInfo()

        # 如果当前市场价格低于大盘第一条和第二条均线，无条件清仓
        if currentMarketPrice < self._marketInfo.Ma_2 and \
                        currentMarketPrice < self._marketInfo.Ma_1:
            PD(1, 'Market price less than both MA line1 and line2')
            self._capitalManager.OnActionSellOff(context)
            return

        # 检测是否有个股需要止损
        self._capitalManager.StopLoss(context, data)

        # 如果当前市场价格处于第一条和第二条均线之间，保持仓位在6成
        if currentMarketPrice >= self._marketInfo.Ma_1 and \
                        currentMarketPrice <= self._marketInfo.Ma_2:
            PD(1, 'Market prices between MA line1 and line2')
            self._capitalManager.TryHoldingOnPosition(context, data, self.PositionIfBreakoutLine1, True)

        if currentMarketPrice >= self._marketInfo.Ma_1 and \
                        currentMarketPrice >= self._marketInfo.Ma_2:
            PD(1, 'Market prices bigger than both Ma line1 and line2')
            self._capitalManager.TryHoldingOnPosition(context, data, self.PositionIfBreakoutLine2, True)


# 获取个股的市值
def GetCurrentMarketCap(security, currrentDate):
    # 先从Cache中读取
    cacheInfo = CacheHolder.Cache.get(security)
    # 如果cache没有命中
    if not cacheInfo:
        cap = GetCurrentMarketCapDir(security, currrentDate)
        cacheInfo = CacheInfo(security, cap, 0)
        CacheHolder.Cache[security] = cacheInfo
    return cacheInfo.MarketCap


def GetCurrentMarketCapDir(security, currentDate):
    q = query(
        valuation.market_cap
    ).filter(
        valuation.code == security
    )

    df = get_fundamentals(q, currentDate)
    if not df.empty:
        cap = df['market_cap'][0]
        return cap
    else:
        return -1


# 获取当前价格
def GetCurrentPrice(security, currentData):
    # 先从Cache中读取
    cacheInfo = CacheHolder.Cache.get(security)
    # 如果cache没有命中
    if not cacheInfo:
        # 查询
        priceDF = get_price(security, end_date=currentData, frequency='1m', count=1)
        price = priceDF.values[0][0]
        # 将该次查询结果写进cache中
        cacheInfo = CacheInfo(security, 0, price)
        CacheHolder.Cache[security] = cacheInfo
    return cacheInfo.CurrentPrice


# 获取大盘的days均线
def GetMarketMaIndexByDay(indexCode, days, field):
    marketIndexHistory = attribute_history(indexCode, days, '1d', field)
    return marketIndexHistory.mean().values[0]


# 获取个股所属的行业
def GetIndustryOrder(industryCode):
    return True


# 设置策略监控的security：市场所有股票
def SetupSecurityPool():
    securities = get_all_securities(types=['stock']).index
    set_universe(securities)


# 大盘：上证指数
XSHG_info = MarketInfo(DEF_MARKET_INDEX)

# 设置过滤选项
selectorFilterOption = SecuritiesSelectionFilterOption()
orderInOption = SecuritiesOrderInFilterOption()
capitalManagerOption = CapitalManagerOption()

# 定义全局过滤规则
SecFilter = SecuritiesFilter(selectorFilterOption, orderInOption)
# 定义全局资金管理
CapitalMgr = CapitalManager(capitalManagerOption, SecFilter)


# 更新大盘MA均线
def RefreshMarketInfo(context):
    XSHG_info.RefreshMa()


def initialize(context):
    # 监控所有的股票
    SetupSecurityPool()

    # 每天开盘前，按天更新大盘MA均线信息
    run_daily(RefreshMarketInfo, time='before_open')

    cashofOneHandPreSecuirty = context.portfolio.starting_cash / capitalManagerOption.TotalShare * capitalManagerOption.SharesPreStock

    # 为了使得资金的仓位水平保持良好，要求每手（100一手）买入个股的资金大于500*100
    if cashofOneHandPreSecuirty < 500 * 100:
        log.warn('starting cash less then 100*10000!')


# # 每个单位时间调用一次(如果按天回测,则每天调用一次,如果按分钟,则每分钟调用一次)
def handle_data(context, data):
    g.context = context
    g.data = data

    # 每次运行，都必须要清空cache，防止数据过时
    CacheHolder.Cache = {}
    # CacheHolder.CacheMarketCap(context.universe, context.current_dt)
    # CacheHolder.CacheCurrentPrice(context.universe, context.current_dt)

    # 过滤掉不符合策略的个股
    context.target_securities = SecFilter.OnFilterSelect(context.universe, context, data)

    # 调试信息，显示符合个股策略的股票
    # PD(0, 'Monitor securities:', context.target_securities)

    # 初始化市场信息
    marketHandler = MarketInfoHandler(XSHG_info, CapitalMgr)
    # 执行处理
    marketHandler.Execute(context, data)
