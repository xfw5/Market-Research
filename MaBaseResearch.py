Debug_On = True

def PD(level, *msg):
    if Debug_On:
        if level == 0:
            log.info(*msg)
        elif level == 1:
            log.warn(*msg)
        elif level == 2:
            log.error(*msg)

def Clamp(value, min, max):
    if value < min: return min
    elif value > max: return max
    return value

#大盘信息
class MarketInfo:
    Ma_60 = 0 #大盘60日均线
    Ma_20 = 0 # 大盘20日均线

    _current_price = 0 #大盘当前市场价
    _market_index = '' #大盘指数ID

    def __init__(self, marketIndex):
        if isinstance(marketIndex, basestring):
            self._market_index = marketIndex
            
    def PrintInfo(self):
        PD(0, 'Market current price: ', self._current_price)
        PD(0, 'Market Ma 60: ' , self.Ma_60)
        PD(0, 'Market Ma 20: ' , self.Ma_20)

    #实时获取当前大盘市场价
    def GetCurrentPrice(self):
        data = get_current_data()
        self._current_price = data[self._market_index].day_open
        return self._current_price

    #更新日均线，按天调度
    def RefreshMa(self):
        self.Ma_20 = GetMarketMaIndexByDay(self._market_index, 20, 'close')
        self.Ma_60 = GetMarketMaIndexByDay(self._market_index, 60, 'close')

#个股操作
class StockHandler:
    #个股是否符合卖出条件
    @staticmethod
    def IsNeedSellOff(position, context, data, MaSamplingDays, stopLossThreshold):
        security = data[position.security]
        current_price = security.close
        Ma = security.mavg(MaSamplingDays, 'close')
        flow = position.price - position.avg_cost

        if current_price < Ma: return True
        if flow < 0 and -flow / position.avg_cost > stopLossThreshold: return True
        return False

    #个股是否符合买入条件
    @staticmethod
    def IsNeedOrderIn(context, data, stockCode, MaSamplingDays, flowingThresholdMin, flowingThresholdMax):
        return True

    #按照当前市场价计算购买个股Amount数量所需要的资金
    @staticmethod
    def GetOrderCurrentValue(data, security, amount = 100):
        return amount * data[security].close
        
    #根据现金流，动态调整下单的金额，使得下单的金额永远满足大于100单（大于100单才能交易）
    @staticmethod
    def ClampOrderValue(data, security, desireValue, cash):
        if cash < desireValue: 
            PD(2, 'Cash no enough: ', cash, ' Desire order: ', desireValue)
            return desireValue
            
        oneDeal = StockHandler.GetOrderCurrentValue(data, security, 100)
        return Clamp(desireValue, oneDeal, cash)

    #过滤掉已经持有的股票
    @staticmethod
    def FilterHoldingStocks(context):
        filterResults = []
        stocks = context.target_securities
        holdingStocks = context.portfolio.positions

        for stock in stocks:
            if not holdingStocks.has_key(stock):
                filterResults.append(stock)

        return filterResults
    
    #记录交易、下单信息
    @staticmethod
    def RecordOrder(title, msg, orderStatus):
        record(title = orderStatus.amount)
        log.info(msg ,'[' + orderStatus.security + ']:' , orderStatus.status ,' Amount:', orderStatus.amount)

#资金管理
class CapitalManager:
    _totalShare = 10 #资金分割等份
    _sharesPreStock = 1 #按份配股：每支股票配多少份(share)
    _stopLossThreshold = 7.86 * 0.01 #个股止损阀值
    _MaSamplingDaysForStock = 6 #个股均线采样时间
    _totalOpenPositionPreDay = 2 #每天最大开仓的数量

    _currentCapitalPosition = 0.0 #当前仓位

    def __init__(self, totalShare=10, sharesPreStock=1, stopLossPoint=7.86 * 0.01, \
                    samplingDays=6, openPositionPreDay=2):
        self._totalShare = totalShare
        self._sharePreStock = sharesPreStock
        self._stopLossThreshold
        self._MaSamplingDaysForStock = samplingDays
        self._totalOpenPositionPreDay = openPositionPreDay

    #更新仓位
    def UpdateCapital(self, context):
        cash = context.portfolio.cash
        capital_used = context.portfolio.capital_used
        self._currentCapitalPosition = capital_used / (capital_used + cash)
        
        PD(0, 'Current cash:', cash, ' used:', capital_used)
        PD(0, 'Current capital position: ', self._currentCapitalPosition)

    #检测是否有股票需要止损
    def StopLoss(self, context, data):
        positions = context.portfolio.positions.values()
        
        if len(positions) > 0:
            self.OnActionStopLoss(positions, context, data)

    #保持仓位在position水平
    def TryHoldingOnPosition(self, context, data, desirePosition, isBullish):
        self.UpdateCapital(context)
        
        if self._currentCapitalPosition > desirePosition and isBullish == False:
            self.OnActionBearishHandle(context, data, desirePosition) #熊市
        elif self._currentCapitalPosition < desirePosition and isBullish:
            self.OnActionBullishHandle(context, data, desirePosition) #牛市

    #看涨
    def OnActionBullishHandle(self, context, data, desirePosition):
        PD(1, 'Bullish: try holding position on: ', desirePosition)
        
        self.UpdateCapital(context)
        stocks = context.target_securities
        currentHoldingStocks = len(context.portfolio.positions.values())
        fillingPosition = desirePosition - self._currentCapitalPosition
        desireTotalOrderCash = (context.portfolio.capital_used + context.portfolio.cash) * fillingPosition
        orderCashPreStock = desireTotalOrderCash / (self._totalShare - currentHoldingStocks)

        #过滤掉已经持有的个股
        backupStocks = StockHandler.FilterHoldingStocks(context)
        openPositionCount = 0
        #从备选股中，开仓
        for stock in backupStocks:
            if openPositionCount >= self._totalOpenPositionPreDay: break
            
            #安装当前市场价，计算下单的金额
            finalValue = StockHandler.ClampOrderValue(data, stock, orderCashPreStock, context.portfolio.cash)
            #调高下单金额%20, 提高下单成功率，溢出的20%会被自动平掉
            orderStatus = order_target_value(stock, finalValue * 1.2, MarketOrderStyle())
            if orderStatus: 
                StockHandler.RecordOrder('OpenPosition', 'OpenPosition', orderStatus)
                #如果下单成功，增加开仓计数器，以保证每天的开仓数量
                if orderStatus.status == OrderStatus.held:
                    openPositionCount = openPositionCount + 1
                self.UpdateCapital(context)

    #看跌
    def OnActionBearishHandle(self, context, data, position):
        PD(1, 'Bearish: try cutdown position on: ', position)
        
        self.UpdateCapital()
        positions = context.portfolio.positions.values()
        
        #根据收益，对持有的个股排序
        positions.sort(lambda x, y: cmp(x.price - x.avg_cost, y.price - y.avg_cost))
        #在保证仓位水平的前提下，优先卖掉获利最多的股票
        self.OnActionStopLossByPosition(positions, context, position)
        #在保证仓位水平的前提下，卖掉需要止损的股票
        self.OnActionStopLoss(positions, context, data)

    #根据期望的仓位平仓
    def OnActionStopLossByPosition(self, positions, context, data, stopLossPoint):
        while self._currentCapitalPosition > stopLossPoint and len(positions) > 0:
            position = positions[0]
            orderStatus = order_target(position.security, 0, MarketOrderStyle())
            positions.remove(position)
            self.UpdateCapital()

    #平掉所有需要止损的个股
    def OnActionStopLoss(self, positions, context, data):
        PD(0, 'OnActionStopLoss')

        while len(positions) > 0:
            position = positions[0]

            if StockHandler.IsNeedSellOff(position, context, data, \
                    self._MaSamplingDaysForStock, self._stopLossThreshold):
                orderStatus = order_target(position.security, 0, MarketOrderStyle())
                if orderStatus:
                    StockHandler.RecordOrder('StopLoss', 'StopLoss', orderStatus)
            positions.remove(position)

    #无条件清仓
    def OnActionSellOff(self, context):
        for position in context.portfolio.positions.values():
            orderStatus = order_target(position.security, 0, MarketOrderStyle())
            if orderStatus:
                StockHandler.RecordOrder('SellOff', 'SellOff', orderStatus)

#市场信息处理
class MarketInfoHandler:
    _marketInfo = MarketInfo('') #大盘信息
    _capitalManager = CapitalManager() #资金管理

    def __init__(self, market, capitalManager):
        if isinstance(market, MarketInfo) and isinstance(capitalManager, CapitalManager):
            self._marketInfo = market
            self._capitalManager = capitalManager

    #根据策略处理市场信息
    def Execute(self, context, data):
        #获取当前最新的市场价格
        currentMarketPrice = self._marketInfo.GetCurrentPrice()
        
        self._marketInfo.PrintInfo()        

        #如果当前市场价格低于大盘60日均线，无条件清仓
        if currentMarketPrice < self._marketInfo.Ma_60:
            PD(1, 'Market price less than Ma60')
            self._capitalManager.OnActionSellOff(context)

        #检测是否有个股需要止损
        self._capitalManager.StopLoss(context, data)

        #如果当前市场价格高于大盘20均线，保持仓位在6成
        if currentMarketPrice > self._marketInfo.Ma_20:
            PD(1, 'Market prices bigger than Ma20')
            self._capitalManager.TryHoldingOnPosition(context, data, 0.6, True)
        
        if currentMarketPrice > self._marketInfo.Ma_60:
            PD(1, 'Market prices bigger than Ma60')
            self._capitalManager.TryHoldingOnPosition(context, data, 0.8, True)

#获取个股的市值
def GetCurrentMarketCap(security, currrentDate):
    q = query(
        valuation
    ).filter(
        valuation.code == security
    )

    df = get_fundamentals(q, currrentDate)
    if not df.empty:
        cap = df['market_cap'][0]
        return cap
    else: return 0

#获取大盘的days均线
def GetMarketMaIndexByDay(indexCode, days, field):
    marketIndexHistory = attribute_history(indexCode, days, '1d', field)
    return marketIndexHistory.mean().values[0]

#获取个股所属的行业
def GetIndustryOrder(industryCode):
    return True

#设置策略监控的security：市场所有股票
def SetupSecurityPool():
    securities = get_all_securities(types=['stock']).index
    set_universe(securities)

#根据策略，过滤掉不满足条件的股票
def FilterSecurity(context, data, flowingThresholdMin, flowingThresholdMax, marketCapMin, marketCapMax):
    currrentDate = context.current_dt.strftime("%Y-%m-%d")
    securities = context.universe

    target_securities = []

    for security in securities:
        securityData = data[security]
        currentData = get_current_data()

        currentPrice = securityData.close
        prePrice = securityData.pre_close
        deltaPrice = currentPrice - prePrice
        ma20 = data[security].mavg(20, 'close')
        
        #如果当前价格低于20日均线，过滤掉
        #如果涨幅低于flowingThresholdMin或者高于flowingThresholdMax， 过滤掉
        #如果是ST过滤掉
        if ma20 < currentPrice or deltaPrice < flowingThresholdMin or \
            deltaPrice > flowingThresholdMax or currentData[security].is_st: continue

        #如果市值低于marketCapMin，过滤掉
        #如果市值高于marketCapMax，过滤掉
        currentMarketCap = GetCurrentMarketCap(security, currrentDate)
        if currentMarketCap < marketCapMin or currentMarketCap > marketCapMax: continue

        target_securities.append(security)
    return target_securities

#大盘：上证指数
XSHG_info = MarketInfo('000001.XSHG')
CapitalMgr = CapitalManager()

#更新大盘MA均线
def RefreshMarketInfo(context):
    XSHG_info.RefreshMa()

def initialize(context):
    #监控所有的股票
    SetupSecurityPool()

    #每天开盘前，按天更新大盘MA均线信息
    run_daily(RefreshMarketInfo, time='before_open')

# # 每个单位时间(如果按天回测,则每天调用一次,如果按分钟,则每分钟调用一次)调用一次
def handle_data(context, data):
    #过滤掉不符合策略的个股
    context.target_securities = FilterSecurity(context, data, 3, 30, 100, 300)
    
    #调试信息，显示符合个股策略的股票
    PD(0, 'Monitor securities:', context.target_securities)
    
    #初始化市场信息
    marketHandler = MarketInfoHandler(XSHG_info, CapitalMgr)
    #执行处理
    marketHandler.Execute(context, data)