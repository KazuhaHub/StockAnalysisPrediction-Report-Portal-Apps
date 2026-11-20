"""
股票数据MCP服务器 - 集成优化版本

功能说明:
- 提供股票行情数据查询功能
- 提供技术指标分析功能（本地计算 + 服务端计算）
- 支持交易日历查询（含上/下一交易日）
- 支持股票基本信息查询
- 支持公司研究数据查询（概览、档案、财务、股东、估值等）
- 支持行业研究数据查询（分类、成分、指数分析等）

优化要点:
- 统一输入验证：stock_code、日期、instrument_id格式校验
- 统一异常处理：MCP工具层捕获所有异常，防止工具崩溃
- 统一返回格式：所有工具确保返回dict，兼容MCP structured_content
- 请求重试机制：网络瞬断自动重试（最多3次）
- 日志记录：关键操作和错误均记录日志，便于排查
- 代码去重：提取公共逻辑，消除重复代码
"""

import inspect
import logging
import os
import sys
import time
from functools import wraps

import numpy as np
import pandas as pd
import requests
from datetime import datetime
from typing import Optional, Dict, Any, List, Union, Literal

from fastmcp import FastMCP


# ==================== 日志配置 ====================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("StockMCP")


# ==================== 常量定义 ====================

# 后端API基础地址
API_BASE = "http://47.237.204.217:8000/api/v1"

# 交易所代码映射：股票代码前缀 -> (标准exchange, 后端instrument_id后缀)
EXCHANGE_MAP = {
    "6": ("SSE", "SH"),   # 沪市主板
    "0": ("SZSE", "SZ"),  # 深市主板
    "3": ("SZSE", "SZ"),  # 创业板
    "5": ("SSE", "SH"),   # 沪市ETF（510300/588000等）
    "1": ("SZSE", "SZ"),  # 深市ETF（159xxx）
    "8": ("BSE", "BJ"),   # 北交所
    "4": ("BSE", "BJ"),   # 北交所
}

# 上海指数代码判断：以0开头但属于上交所的指数代码
# 深交所股票代码从000001开始（如000002万科），与上交所指数代码重叠
# 因此需要白名单区分：白名单中的代码为上交所指数，其余0开头为深交所股票
# 如果不在白名单中的0开头代码作为基准使用，会自动尝试SH后缀
SSE_INDEX_CODES = {
    "000001",  # 上证指数
    "000009",  # 上证380
    "000010",  # 上证180
    "000011",  # 上证全指
    "000012",  # 上证国债
    "000013",  # 上证企债
    "000015",  # 上证红利
    "000016",  # 上证50
    "000017",  # 上证公司债
    "000018",  # 上证沪企债
    "000019",  # 上证综债
    "000025",  # 上证沪企
    "000032",  # 上证能源
    "000042",  # 上证消费80
    "000043",  # 上证医药
    "000044",  # 上证金融
    "000045",  # 上证电信
    "000046",  # 上证公用
    "000050",  # 50ETF
    "000051",  # 沪深300ETF
    "000052",  # 中证500ETF
    "000053",  # 中证1000ETF
    "000054",  # 上证50ETF
    "000055",  # 上证180ETF
    "000056",  # 上证红利ETF
    "000100",  # 上证新指数
    "000125",  # 上证转债
    "000133",  # 上证城投债
    "000150",  # 上证地方政府债
    "000155",  # 上证分离债
    "000159",  # 上证企业债
    "000171",  # 上证回购
    "000180",  # 上证基金
    "000188",  # 上证B股
    "000200",  # 上证规模
    "000250",  # 上证高股息
    "000255",  # 上证低波动
    "000300",  # 沪深300
    "000500",  # 中证流通
    "000800",  # 中证800
    "000801",  # 中证小盘
    "000802",  # 中证500
    "000803",  # 中证100
    "000804",  # 中证超大
    "000805",  # 中证A股
    "000806",  # 中证消费
    "000807",  # 中证食品
    "000808",  # 中证医药
    "000809",  # 中证金融
    "000810",  # 中证信息
    "000811",  # 中证电信
    "000812",  # 中证能源
    "000813",  # 中证材料
    "000814",  # 中证工业
    "000815",  # 中证可选
    "000816",  # 中证公用
    "000817",  # 中证新兴
    "000818",  # 中证环保
    "000819",  # 中证军工
    "000820",  # 中证红利
    "000821",  # 中证TMT
    "000822",  # 中证消费服务
    "000823",  # 中证高端装备
    "000824",  # 中证新能源汽车
    "000825",  # 中证人工智能
    "000826",  # 中证生物医药
    "000827",  # 中证半导体
    "000828",  # 中证云计算
    "000829",  # 中证物联网
    "000830",  # 中证5G通信
    "000831",  # 中证光伏
    "000832",  # 中证风电
    "000833",  # 中证储能
    "000834",  # 中证氢能
    "000835",  # 中证碳中和
    "000836",  # 中证创新药
    "000837",  # 中证医疗器械
    "000838",  # 中证医疗服务
    "000839",  # 中证中药
    "000840",  # 中证银行
    "000841",  # 中证证券
    "000842",  # 中证保险
    "000843",  # 中证房地产
    "000844",  # 中证建筑
    "000845",  # 中证煤炭
    "000846",  # 中证钢铁
    "000847",  # 中证有色金属
    "000848",  # 中证石化
    "000849",  # 中证电力
    "000850",  # 中证汽车
    "000851",  # 中证家电
    "000852",  # 中证1000
    "000853",  # 中证2000
    "000854",  # 中证全指
    "000855",  # 中证国企
    "000856",  # 中证民企
    "000857",  # 中证央企
    "000858",  # 中证沪港深
    "000859",  # 中证港股通
    "000860",  # 中证科创
    "000861",  # 中证北交所
    "000862",  # 中证REITs
    "000863",  # 中证ESG
    "000864",  # 中证绿色
    "000865",  # 中证数字经济
    "000866",  # 中证元宇宙
    "000867",  # 中证机器人
    "000868",  # 中证数据要素
    "000869",  # 中证算力
    "000870",  # 中证信创
    "000871",  # 中证央企科技
    "000872",  # 中证央企创新
    "000873",  # 中证央企红利
    "000874",  # 中证国企改革
    "000875",  # 中证民企活力
    "000876",  # 中证成长
    "000877",  # 中证价值
    "000878",  # 中证质量
    "000879",  # 中证低波
    "000880",  # 中证高股息
    "000881",  # 中证动量
    "000882",  # 中证红利低波
    "000883",  # 中证红利成长
    "000884",  # 中证红利质量
    "000885",  # 中证红利动量
    "000886",  # 中证红利价值
    "000887",  # 中证红利低波100
    "000888",  # 中证红利100
    "000889",  # 中证红利200
    "000890",  # 中证红利300
    "000891",  # 中证红利500
    "000892",  # 中证红利1000
    "000893",  # 中证红利全收益
    "000894",  # 中证高股息全收益
    "000895",  # 中证低波全收益
    "000896",  # 中证质量全收益
    "000897",  # 中证成长全收益
    "000898",  # 中证价值全收益
    "000899",  # 中证动量全收益
    "000900",  # 中证流通
    "000901",  # 中证小盘全收益
    "000902",  # 中证大盘
    "000903",  # 中证全指
    "000904",  # 中证龙头
    "000905",  # 中证500
    "000906",  # 中证800
    "000907",  # 中证1000
    "000908",  # 中证2000
    "000909",  # 中证全指
    "000910",  # 中证国企
    "000911",  # 中证民企
    "000912",  # 中证央企
    "000913",  # 中证沪港深
    "000914",  # 中证港股通
    "000915",  # 中证科创
    "000916",  # 中证北交所
    "000917",  # 中证REITs
    "000918",  # 中证ESG
    "000919",  # 中证绿色
    "000920",  # 中证数字经济
    "000921",  # 中证元宇宙
    "000922",  # 中证机器人
    "000923",  # 中证数据要素
    "000924",  # 中证算力
    "000925",  # 中证信创
    "000926",  # 中证央企科技
    "000927",  # 中证央企创新
    "000928",  # 中证央企红利
    "000929",  # 中证国企改革
    "000930",  # 中证民企活力
    "000931",  # 中证成长
    "000932",  # 中证价值
    "000933",  # 中证质量
    "000934",  # 中证低波
    "000935",  # 中证高股息
    "000936",  # 中证动量
    "000937",  # 中证红利低波
    "000938",  # 中证红利成长
    "000939",  # 中证红利质量
    "000940",  # 中证红利动量
    "000941",  # 中证红利价值
    "000942",  # 中证红利低波100
    "000943",  # 中证红利100
    "000944",  # 中证红利200
    "000945",  # 中证红利300
    "000946",  # 中证红利500
    "000947",  # 中证红利1000
    "000948",  # 中证红利全收益
    "000949",  # 中证高股息全收益
    "000950",  # 中证低波全收益
    "000951",  # 中证质量全收益
    "000952",  # 中证成长全收益
    "000953",  # 中证价值全收益
    "000954",  # 中证动量全收益
    "000955",  # 中证流通全收益
    "000956",  # 中证小盘全收益
    "000957",  # 中证大盘全收益
    "000958",  # 中证全指全收益
    "000959",  # 中证龙头全收益
    "000960",  # 中证500全收益
    "000961",  # 中证800全收益
    "000962",  # 中证1000全收益
    "000963",  # 中证2000全收益
    "000964",  # 中证全指全收益
    "000965",  # 中证国企全收益
    "000966",  # 中证民企全收益
    "000967",  # 中证央企全收益
    "000968",  # 中证沪港深全收益
    "000969",  # 中证港股通全收益
    "000970",  # 中证科创全收益
    "000971",  # 中证北交所全收益
    "000972",  # 中证REITs全收益
    "000973",  # 中证ESG全收益
    "000974",  # 中证绿色全收益
    "000975",  # 中证数字经济全收益
    "000976",  # 中证元宇宙全收益
    "000977",  # 中证机器人全收益
    "000978",  # 中证数据要素全收益
    "000979",  # 中证算力全收益
    "000980",  # 中证信创全收益
    "000981",  # 中证央企科技全收益
    "000982",  # 中证央企创新全收益
    "000983",  # 中证央企红利全收益
    "000984",  # 中证国企改革全收益
    "000985",  # 中证民企活力全收益
    "000986",  # 中证成长全收益
    "000987",  # 中证价值全收益
    "000988",  # 中证质量全收益
    "000989",  # 中证低波全收益
    "000990",  # 中证高股息全收益
    "000991",  # 中证动量全收益
    "000992",  # 中证红利低波全收益
    "000993",  # 中证红利成长全收益
    "000994",  # 中证红利质量全收益
    "000995",  # 中证红利动量全收益
    "000996",  # 中证红利价值全收益
    "000997",  # 中证红利低波100全收益
    "000998",  # 中证红利100全收益
    "000999",  # 中证红利200全收益
}

def _is_sse_index(code: str) -> bool:
    """判断代码是否为上交所指数（白名单匹配）"""
    return code in SSE_INDEX_CODES

# 有效的交易所代码列表
VALID_EXCHANGES = ["SSE", "SZSE"]

# 请求重试配置
MAX_RETRIES = 3
RETRY_BACKOFF = 1  # 重试间隔基数（秒），实际间隔 = RETRY_BACKOFF * attempt
RATE_LIMIT_BACKOFF = 5  # 429限流重试间隔基数（秒），实际间隔 = RATE_LIMIT_BACKOFF * attempt

# 请求超时（秒）
DEFAULT_TIMEOUT = 30


# ==================== 输入验证工具函数 ====================

def validate_stock_code(stock_code: str) -> str:
    """
    验证股票代码格式

    参数:
    - stock_code: 待验证的股票代码

    返回:
    - 验证通过的股票代码

    异常:
    - ValueError: 股票代码格式不正确
    """
    if not isinstance(stock_code, str) or len(stock_code) != 6 or not stock_code.isdigit():
        raise ValueError(f"无效的股票代码 '{stock_code}'，请输入6位数字股票代码（如 600519）")
    if stock_code[0] not in EXCHANGE_MAP:
        raise ValueError(f"无法识别股票代码 '{stock_code}' 的交易所，首位应为 6(沪市)、0/3(深市)、5(沪市ETF)、1(深市ETF)、8/4(北交所)")
    return stock_code


def validate_date(date_str: str, param_name: str = "日期") -> str:
    """
    验证日期格式

    参数:
    - date_str: 待验证的日期字符串
    - param_name: 参数名称，用于错误提示

    返回:
    - 验证通过的日期字符串

    异常:
    - ValueError: 日期格式不正确
    """
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return date_str
    except (ValueError, TypeError):
        raise ValueError(f"无效的{param_name} '{date_str}'，请使用 YYYY-MM-DD 格式（如 2025-01-05）")


def validate_instrument_id(instrument_id: str) -> str:
    """
    验证instrument_id格式

    参数:
    - instrument_id: 待验证的交易品种ID

    返回:
    - 验证通过的instrument_id

    异常:
    - ValueError: instrument_id格式不正确
    """
    if not isinstance(instrument_id, str) or "." not in instrument_id:
        raise ValueError(f"无效的instrument_id '{instrument_id}'，格式应为 '代码.交易所'（如 600519.SH）")
    code, suffix = instrument_id.split(".", 1)
    if not code.isdigit() or len(code) != 6:
        raise ValueError(f"无效的instrument_id '{instrument_id}'，代码部分应为6位数字")
    if suffix.upper() not in ("SH", "SZ", "SSE", "SZSE"):
        raise ValueError(f"无效的instrument_id '{instrument_id}'，交易所后缀应为 SH/SZ/SSE/SZSE")
    return instrument_id


def validate_exchange(exchange: str) -> str:
    """
    验证交易所代码

    参数:
    - exchange: 待验证的交易所代码

    返回:
    - 验证通过的交易所代码

    异常:
    - ValueError: 交易所代码无效
    """
    if exchange not in VALID_EXCHANGES:
        raise ValueError(f"无效的交易所代码 '{exchange}'，支持的交易所：{VALID_EXCHANGES}")
    return exchange


# ==================== 返回值工具函数 ====================

def ensure_dict(result: Any, context: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    确保返回值是dict，兼容MCP的structured_content要求

    MCP协议要求工具返回值必须是dict，不能是list。
    此函数将list结果包裹在dict中，确保兼容性。

    参数:
    - result: API返回的原始数据
    - context: 上下文信息，用于包裹list结果

    返回:
    - 如果result是dict则直接返回，如果是list则包裹在dict中
    """
    if isinstance(result, list):
        return {**(context or {}), "data": result}
    if not isinstance(result, dict):
        return {**(context or {}), "data": result}
    return result


# ==================== API客户端 ====================

class StockQuoteAPI:
    """股票行情API客户端，提供股票数据查询功能"""

    def __init__(self, timeout: int = DEFAULT_TIMEOUT, max_retries: int = MAX_RETRIES):
        """
        初始化股票API客户端

        参数:
        - timeout: 请求超时时间（秒），默认30秒
        - max_retries: 最大重试次数，默认3次
        """
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})
        self.timeout = timeout
        self.max_retries = max_retries

    @staticmethod
    def get_exchange_info(stock_code: str, is_index: bool = False) -> tuple:
        """
        根据股票代码获取交易所信息

        参数:
        - stock_code: 6位股票代码
        - is_index: 是否为指数代码。True时查指数白名单（000001→SH上证指数），
          False时按股票规则映射（000001→SZ平安银行）

        返回:
        - (标准exchange代码, 后端instrument_id后缀) 例如 ('SSE', 'SH')
        """
        # 仅在指数模式下查白名单（如000300沪深300、000001上证指数）
        if is_index and _is_sse_index(stock_code):
            return ("SSE", "SH")
        prefix = stock_code[0]
        if prefix in EXCHANGE_MAP:
            return EXCHANGE_MAP[prefix]
        raise ValueError(f"无法识别股票代码 {stock_code} 的交易所")

    @staticmethod
    def get_exchange(stock_code: str, is_index: bool = False) -> str:
        """根据股票代码判断交易所（标准代码，如SSE/SZSE）"""
        return StockQuoteAPI.get_exchange_info(stock_code, is_index)[0]

    @staticmethod
    def make_instrument_id(stock_code: str, is_index: bool = False) -> str:
        """
        根据股票代码生成后端instrument_id（使用SH/SZ后缀）

        参数:
        - stock_code: 6位股票代码
        - is_index: 是否为指数代码
        """
        suffix = StockQuoteAPI.get_exchange_info(stock_code, is_index)[1]
        return f"{stock_code}.{suffix}"

    @staticmethod
    def format_date(date_str: str) -> str:
        """
        格式化日期为后端API所需的ISO格式

        参数:
        - date_str: YYYY-MM-DD格式的日期字符串

        返回:
        - ISO格式的日期字符串（带时间部分）
        """
        validate_date(date_str)
        return f"{date_str}T00:00:00"

    def _request(self, path: str, params: Dict = None, graceful: bool = False, timeout: Optional[int] = None) -> Any:
        """
        通用请求方法，支持重试和优雅错误处理

        参数:
        - path: API路径（相对于/api/v1）
        - params: 查询参数字典
        - graceful: 是否优雅处理错误（返回错误信息dict而非抛异常）
        - timeout: 单次请求超时秒数，None时使用实例默认值self.timeout

        返回:
        - JSON解析后的数据；graceful模式下出错返回包含error字段的dict

        异常:
        - graceful=False时，请求超时或失败抛出异常
        """
        url = f"{API_BASE}{path}"
        # 过滤掉值为None的参数
        if params:
            params = {k: v for k, v in params.items() if v is not None}

        req_timeout = timeout if timeout is not None else self.timeout
        last_exception = None
        for attempt in range(1, self.max_retries + 1):
            try:
                logger.debug(f"请求 {url} (第{attempt}次), 参数: {params}")
                response = self.session.get(url, params=params, timeout=req_timeout)
                response.raise_for_status()
                return response.json()
            except requests.exceptions.Timeout:
                last_exception = requests.exceptions.Timeout()
                logger.warning(f"请求超时 {url} (第{attempt}/{self.max_retries}次)")
            except requests.exceptions.ConnectionError as e:
                last_exception = e
                logger.warning(f"连接失败 {url} (第{attempt}/{self.max_retries}次): {e}")
            except requests.exceptions.HTTPError as e:
                # HTTP错误处理：429限流需重试，其他4xx/5xx不重试直接处理
                status_code = e.response.status_code if e.response is not None else 0
                try:
                    detail = e.response.json().get("detail", str(e)) if e.response is not None else str(e)
                except Exception:
                    detail = str(e)
                # 429 限流：服务器对IP限流，属于临时错误，等待后重试
                if status_code == 429 and attempt < self.max_retries:
                    wait_sec = RATE_LIMIT_BACKOFF * attempt  # 第一次5s，第二次10s
                    logger.warning(f"429限流 {url}，暂停{wait_sec}s后重试({attempt}/{self.max_retries})")
                    time.sleep(wait_sec)
                    last_exception = e
                    continue  # 回到循环顶部重试
                # 非429错误或429重试已耗尽，直接处理
                logger.error(f"HTTP错误 {status_code} {url}: {detail}")
                if graceful:
                    return {"error": detail, "status_code": status_code, "path": path}
                raise Exception(f"请求失败({status_code}): {detail}")
            except requests.exceptions.RequestException as e:
                last_exception = e
                logger.warning(f"请求异常 {url} (第{attempt}/{self.max_retries}次): {e}")
            except ValueError:
                msg = "JSON解析失败，请检查API返回格式"
                logger.error(f"{msg} {url}")
                if graceful:
                    return {"error": msg, "path": path}
                raise Exception(msg)

            # 重试前等待（指数退避）
            if attempt < self.max_retries:
                wait_time = RETRY_BACKOFF * attempt
                logger.info(f"等待{wait_time}秒后重试...")
                time.sleep(wait_time)

        # 所有重试均失败
        msg = f"请求失败（已重试{self.max_retries}次）: {last_exception}"
        logger.error(msg)
        if graceful:
            return {"error": msg, "path": path}
        raise Exception(msg)

    def _research_request(self, path: str, params: Dict = None, timeout: Optional[int] = None) -> Any:
        """
        公司研究接口请求，优雅处理404/503等错误

        Research系列接口可能返回404（数据不存在）、503（模块禁用）、500（内部错误），
        统一使用graceful模式，返回包含error字段的dict而非抛异常。

        参数:
        - path: API路径
        - params: 查询参数字典
        - timeout: 单次请求超时秒数，None时使用实例默认值

        返回:
        - API数据或包含error字段的dict
        """
        return self._request(path, params, graceful=True, timeout=timeout)

    # ==================== 行情数据 ====================

    def get_daily_quotes(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
        adjust: Optional[str] = None,
        return_format: str = "json",
        is_index: bool = False,
        include_suspended: Optional[bool] = None,
        min_quality_score: Optional[float] = None,
        is_complete: Optional[bool] = None,
        min_volume: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        获取股票日度行情数据，返回原始JSON格式

        参数:
        - stock_code: 6位股票代码
        - start_date: 开始日期，格式 YYYY-MM-DD
        - end_date: 结束日期，格式 YYYY-MM-DD
        - adjust: 复权类型，可选 "qfq"(前复权)/"hfq"(后复权)/None(不复权)
        - return_format: 返回格式，默认json
        - is_index: 是否为指数代码，默认False
        - include_suspended: 是否包含停牌日（后端参数，透传；实测当前未生效，见下）
        - min_quality_score: 最低质量分过滤（后端参数，透传；实测当前未生效，见下）
        - is_complete: 是否只要完整交易日（后端参数，实测生效：传 true 可剔除停牌日）
        - min_volume: 最小成交量过滤（后端参数，实测生效：传 1 可剔除零成交的停牌日）

        停牌日说明（实测 000002.SZ / 2016-06-01~07-31）:
        - 停牌日以零成交量行存在：volume=0、OHLC 全等前收、tradestatus=0、
          is_complete=false、quality_score=0.4，共 21/41 行。
        - 后端接受 include_suspended / min_quality_score 但当前不做过滤（仍返回 41 行）；
          可用 is_complete=true 或 min_volume=1 达到剔除停牌日的效果（均返回 20 行）。

        返回:
        - 包含股票行情数据的字典
        """
        validate_stock_code(stock_code)
        instrument_id = self.make_instrument_id(stock_code, is_index=is_index)
        params = {
            "instrument_id": instrument_id,
            "start_date": self.format_date(start_date),
            "end_date": self.format_date(end_date),
            "return_format": return_format,
            "adjust": adjust,
        }
        # 过滤类参数仅在显式传入时透传，避免把 None 序列化成字符串影响后端默认行为
        for key, value in (
            ("include_suspended", include_suspended),
            ("min_quality_score", min_quality_score),
            ("is_complete", is_complete),
            ("min_volume", min_volume),
        ):
            if value is not None:
                params[key] = value
        return self._request("/quotes/daily", params)

    def get_daily_quotes_df(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
        is_index: bool = False,
    ) -> pd.DataFrame:
        """
        获取股票日度行情数据并转换为DataFrame，用于技术分析

        参数:
        - stock_code: 6位股票代码
        - start_date: 开始日期，格式 YYYY-MM-DD
        - end_date: 结束日期，格式 YYYY-MM-DD
        - is_index: 是否为指数代码，默认False

        返回:
        - 包含股票行情数据的DataFrame
        """
        validate_stock_code(stock_code)
        instrument_id = self.make_instrument_id(stock_code, is_index=is_index)
        params = {
            "instrument_id": instrument_id,
            "start_date": self.format_date(start_date),
            "end_date": self.format_date(end_date),
            "return_format": "json",
        }
        data = self._request("/quotes/daily", params)
        df = pd.DataFrame(data.get("data", []))
        if not df.empty and "time" in df.columns:
            df["time"] = pd.to_datetime(df["time"])
            df.set_index("time", inplace=True)
            df.sort_index(inplace=True)
        return df

    def get_latest_quotes(self, stock_codes: list) -> Dict[str, Any]:
        """
        获取股票最新行情数据，支持同时查询多个股票

        参数:
        - stock_codes: 股票代码列表

        返回:
        - 包含股票最新行情数据的字典
        """
        for code in stock_codes:
            validate_stock_code(code)
        instrument_ids = [self.make_instrument_id(c) for c in stock_codes]
        params = {"instrument_ids": instrument_ids}
        return self._request("/quotes/latest", params)

    # ==================== 交易日历 ====================

    def get_trading_calendar(
        self,
        exchange: str,
        start_date: str,
        end_date: str,
        include_weekends: Optional[bool] = None,
        session_type: Optional[str] = None,
    ) -> Any:
        """
        获取交易日历数据

        参数:
        - exchange: 交易所代码（SSE或SZSE）
        - start_date: 开始日期，格式 YYYY-MM-DD
        - end_date: 结束日期，格式 YYYY-MM-DD
        - include_weekends: 是否包含周末
        - session_type: 交易时段类型

        返回:
        - 包含交易日历数据的字典或列表
        """
        validate_exchange(exchange)
        params = {
            "exchange": exchange,
            "start_date": self.format_date(start_date),
            "end_date": self.format_date(end_date),
            "include_weekends": include_weekends,
            "session_type": session_type,
        }
        return self._request("/calendar/trading", params)

    def get_next_trading_day(self, exchange: str, date: str) -> Any:
        """
        获取指定日期之后的下一个交易日

        参数:
        - exchange: 交易所代码（SSE或SZSE）
        - date: 参考日期，格式 YYYY-MM-DD

        返回:
        - 下一交易日数据
        """
        validate_exchange(exchange)
        validate_date(date, "参考日期")
        params = {
            "exchange": exchange,
            "date": self.format_date(date),
        }
        return self._request("/calendar/trading/next", params, graceful=True)

    def get_previous_trading_day(self, exchange: str, date: str) -> Any:
        """
        获取指定日期之前的上一个交易日

        参数:
        - exchange: 交易所代码（SSE或SZSE）
        - date: 参考日期，格式 YYYY-MM-DD

        返回:
        - 上一交易日数据
        """
        validate_exchange(exchange)
        validate_date(date, "参考日期")
        params = {
            "exchange": exchange,
            "date": self.format_date(date),
        }
        return self._request("/calendar/trading/previous", params, graceful=True)

    # ==================== 交易品种 ====================

    def get_instruments(
        self,
        exchange: Optional[str] = None,
        instrument_type: Optional[str] = None,
        industry: Optional[str] = None,
        sector: Optional[str] = None,
        market: Optional[str] = None,
        is_active: Optional[bool] = None,
        is_st: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0,
        sort_by: str = "symbol",
        sort_order: str = "asc",
    ) -> Any:
        """
        获取交易品种列表，支持多维度筛选

        参数:
        - exchange: 交易所代码
        - instrument_type: 品种类型
        - industry: 行业
        - sector: 板块
        - market: 市场
        - is_active: 是否活跃
        - is_st: 是否ST股
        - limit: 返回数量限制
        - offset: 偏移量
        - sort_by: 排序字段
        - sort_order: 排序方向

        返回:
        - 交易品种列表
        """
        params = {
            "exchange": exchange,
            "type": instrument_type,
            "industry": industry,
            "sector": sector,
            "market": market,
            "is_active": is_active,
            "is_st": is_st,
            "limit": limit,
            "offset": offset,
            "sort_by": sort_by,
            "sort_order": sort_order,
        }
        return self._request("/instruments", params)

    def get_instrument_info(self, stock_code: str) -> Dict[str, Any]:
        """
        获取股票基本信息（根据交易代码查询）

        参数:
        - stock_code: 6位股票代码

        返回:
        - 包含股票基本信息的字典
        """
        validate_stock_code(stock_code)
        return self._request(f"/instruments/symbol/{stock_code}")

    def get_instrument_by_id(self, instrument_id: str) -> Dict[str, Any]:
        """
        根据instrument_id获取交易品种信息

        参数:
        - instrument_id: 交易品种ID，例如 "600000.SH"

        返回:
        - 包含交易品种信息的字典
        """
        validate_instrument_id(instrument_id)
        return self._request(f"/instruments/{instrument_id}", graceful=True)

    # ==================== 公司研究 ====================

    def get_company_overview(
        self,
        instrument_id: str,
        include_profile_snapshot: bool = False,
        include_industry_snapshot: bool = False,
        include_financial_snapshot: bool = False,
    ) -> Any:
        """获取公司概览数据"""
        validate_instrument_id(instrument_id)
        params = {
            "include_profile_snapshot": include_profile_snapshot,
            "include_industry_snapshot": include_industry_snapshot,
            "include_financial_snapshot": include_financial_snapshot,
        }
        return self._research_request(f"/research/company/{instrument_id}/overview", params)

    def get_company_profile(self, instrument_id: str, include_snapshot: bool = True) -> Any:
        """获取公司档案数据"""
        validate_instrument_id(instrument_id)
        return self._research_request(
            f"/research/company/{instrument_id}/profile", {"include_snapshot": include_snapshot}
        )

    def get_company_industry(self, instrument_id: str, include_snapshot: bool = True) -> Any:
        """获取公司行业归属数据"""
        validate_instrument_id(instrument_id)
        return self._research_request(
            f"/research/company/{instrument_id}/industry", {"include_snapshot": include_snapshot}
        )

    def get_financial_indicators(self, instrument_id: str, include_snapshot: bool = True) -> Any:
        """获取公司财务指标摘要"""
        validate_instrument_id(instrument_id)
        return self._research_request(
            f"/research/company/{instrument_id}/financial-indicators", {"include_snapshot": include_snapshot}
        )

    def get_financial_statements(
        self,
        instrument_id: str,
        include_statements: Optional[bool] = None,
        report_period: Optional[str] = None,
    ) -> Any:
        """获取公司财务报表数据"""
        validate_instrument_id(instrument_id)
        params = {
            "include_statements": include_statements,
            "report_period": report_period,
        }
        return self._research_request(f"/research/company/{instrument_id}/financial-statements", params)

    def get_financial_statements_history(
        self,
        instrument_id: str,
        period_window: Optional[str] = "latest",
        rolling_quarters: Optional[int] = 12,
        include_statements: Optional[bool] = False,
    ) -> Any:
        """
        获取公司财务报表历史数据，支持多报告期对比

        参数:
        - instrument_id: 交易品种ID，例如 "600030.SH"
        - period_window: 报告期窗口模式，目前后端支持 "latest"（默认）
        - rolling_quarters: 最近报告期数量，1-40，默认12
        - include_statements: 是否包含原始报表详情，默认False（轻量模式）
          注意：True模式会拉取完整报表详情，响应较慢，建议按需开启

        返回:
        - 包含多报告期财务数据的字典

        说明:
        - 后端该接口响应较慢（约60秒），已设置120秒超时
        - include_statements=False 时仅返回汇总字段，响应更快
        """
        validate_instrument_id(instrument_id)
        params = {
            "period_window": period_window,
            "rolling_quarters": rolling_quarters,
            "include_statements": include_statements,
        }
        # 财报历史接口响应较慢，使用120秒超时
        return self._research_request(
            f"/research/company/{instrument_id}/financial-statements/history",
            params,
            timeout=120,
        )

    def get_shareholders(self, instrument_id: str, include_snapshot: bool = True) -> Any:
        """获取公司股东信息"""
        validate_instrument_id(instrument_id)
        return self._research_request(
            f"/research/company/{instrument_id}/shareholders", {"include_snapshot": include_snapshot}
        )

    def get_valuation_history(
        self,
        instrument_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 120,
        include_details: bool = True,
    ) -> Any:
        """
        获取公司估值历史数据，包含PE/PB/PS等估值指标的时间序列

        参数:
        - instrument_id: 交易品种ID
        - start_date: 开始日期，格式 YYYY-MM-DD
        - end_date: 结束日期，格式 YYYY-MM-DD
        - limit: 返回数据点数量，默认120
        - include_details: 是否包含详情，默认True

        说明: 该接口响应较慢（约30秒），已设置90秒超时
        """
        validate_instrument_id(instrument_id)
        params = {
            "start_date": self.format_date(start_date) if start_date else None,
            "end_date": self.format_date(end_date) if end_date else None,
            "limit": limit,
            "include_details": include_details,
        }
        # 估值历史接口响应较慢，使用90秒超时
        return self._research_request(
            f"/research/company/{instrument_id}/valuation/history", params, timeout=90
        )

    def get_server_beta(
        self,
        instrument_id: str,
        benchmark_family: Optional[str] = None,
        benchmark_instrument_id: Optional[str] = None,
        window_days: Optional[int] = None,
        as_of_date: Optional[str] = None,
        include_details: bool = True,
    ) -> Any:
        """
        获取服务端计算的Beta值，支持多窗口（60/120/252天）和多基准族

        参数:
        - instrument_id: 交易品种ID，例如 "600519.SH"
        - benchmark_family: 基准族，可选 market_default/market_broad/board/industry_sw_l2/custom
        - benchmark_instrument_id: 显式基准标的ID，与 benchmark_family=custom 配合使用
        - window_days: Beta窗口天数；为空时返回配置默认的60/120/252
        - as_of_date: 计算截止日期，格式 YYYY-MM-DD
        - include_details: 是否包含计算诊断，默认True
        """
        validate_instrument_id(instrument_id)
        params = {
            "benchmark_family": benchmark_family,
            "benchmark_instrument_id": benchmark_instrument_id,
            "window_days": window_days,
            "as_of_date": self.format_date(as_of_date) if as_of_date else None,
            "include_details": include_details,
        }
        return self._research_request(f"/research/company/{instrument_id}/beta", params)

    def get_valuation_percentile(
        self,
        instrument_id: str,
        as_of_date: Optional[str] = None,
        quarters: int = 12,
        metrics: Optional[str] = None,
        min_points: int = 60,
        negative_policy: str = "flag",
        include_series: bool = False,
    ) -> Any:
        """
        获取公司估值分位数，衡量当前估值在历史区间中的相对位置

        参数:
        - instrument_id: 交易品种ID，例如 "600519.SH"
        - as_of_date: 估值日期，默认使用最新可得日，格式 YYYY-MM-DD
        - quarters: 历史窗口季度数，默认12
        - metrics: 逗号分隔的估值指标口径，默认 "pe_ttm,pb_mrq,ps_ttm"
        - min_points: 最小有效样本数，默认60
        - negative_policy: 负值估值处理策略，flag/include/exclude，默认 flag
        - include_series: 是否返回样本序列，默认False
        """
        validate_instrument_id(instrument_id)
        params = {
            "as_of_date": self.format_date(as_of_date) if as_of_date else None,
            "quarters": quarters,
            "metrics": metrics,
            "min_points": min_points,
            "negative_policy": negative_policy,
            "include_series": include_series,
        }
        return self._research_request(
            f"/research/company/{instrument_id}/valuation/percentile", params
        )

    def get_relative_valuation(self, instrument_id: str) -> Any:
        """获取公司相对估值数据"""
        validate_instrument_id(instrument_id)
        return self._research_request(f"/research/company/{instrument_id}/valuation/relative")

    def get_dcf_valuation(
        self,
        instrument_id: str,
        growth_rate: Optional[float] = None,
        discount_rate: Optional[float] = None,
        terminal_growth: Optional[float] = None,
        projection_years: Optional[int] = None,
    ) -> Any:
        """获取公司DCF估值数据"""
        validate_instrument_id(instrument_id)
        params = {
            "growth_rate": growth_rate,
            "discount_rate": discount_rate,
            "terminal_growth": terminal_growth,
            "projection_years": projection_years,
        }
        return self._research_request(f"/research/company/{instrument_id}/valuation/dcf", params)

    def get_analyst_coverage(self, instrument_id: str, include_details: bool = False) -> Any:
        """获取公司分析师覆盖数据"""
        validate_instrument_id(instrument_id)
        return self._research_request(
            f"/research/company/{instrument_id}/analyst-coverage", {"include_details": include_details}
        )

    def get_research_reports(
        self,
        instrument_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 20,
        include_details: bool = False,
    ) -> Any:
        """获取公司研究报告"""
        validate_instrument_id(instrument_id)
        params = {
            "start_date": self.format_date(start_date) if start_date else None,
            "end_date": self.format_date(end_date) if end_date else None,
            "limit": limit,
            "include_details": include_details,
        }
        return self._research_request(f"/research/company/{instrument_id}/research-reports", params)

    def get_company_events(
        self,
        instrument_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        event_types: Optional[str] = None,
        limit: int = 50,
        include_details: bool = False,
    ) -> Any:
        """获取公司情绪事件数据"""
        validate_instrument_id(instrument_id)
        params = {
            "start_date": self.format_date(start_date) if start_date else None,
            "end_date": self.format_date(end_date) if end_date else None,
            "event_types": event_types,
            "limit": limit,
            "include_details": include_details,
        }
        return self._research_request(f"/research/company/{instrument_id}/events", params)

    def get_company_risk(self, instrument_id: str, include_details: bool = False) -> Any:
        """获取公司风险分析数据"""
        validate_instrument_id(instrument_id)
        return self._research_request(
            f"/research/company/{instrument_id}/risk", {"include_details": include_details}
        )

    def get_technical_summary(self, instrument_id: str, adjust: Optional[str] = None) -> Any:
        """获取公司技术分析摘要（服务端计算）"""
        validate_instrument_id(instrument_id)
        return self._research_request(
            f"/research/company/{instrument_id}/technical/summary", {"adjust": adjust}
        )

    def get_technical_indicators(
        self,
        instrument_id: str,
        adjust: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 100,
    ) -> Any:
        """获取公司技术指标数据（服务端计算）"""
        validate_instrument_id(instrument_id)
        params = {
            "adjust": adjust,
            "start_date": self.format_date(start_date) if start_date else None,
            "end_date": self.format_date(end_date) if end_date else None,
            "limit": limit,
        }
        return self._research_request(f"/research/company/{instrument_id}/technical/indicators", params)

    # ==================== 行业研究 ====================

    def get_industry_taxonomy(
        self,
        taxonomy_system: Optional[str] = None,
        taxonomy_version: Optional[str] = None,
        industry_level: Optional[int] = None,
        parent_code: Optional[str] = None,
        industry_code: Optional[str] = None,
        sw_index_code: Optional[str] = None,
        active_only: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Any:
        """获取行业分类体系数据"""
        params = {
            "taxonomy_system": taxonomy_system,
            "taxonomy_version": taxonomy_version,
            "industry_level": industry_level,
            "parent_code": parent_code,
            "industry_code": industry_code,
            "sw_index_code": sw_index_code,
            "active_only": active_only,
            "limit": limit,
            "offset": offset,
        }
        return self._research_request("/research/industry/taxonomy", params)

    def get_industry_component_sets(
        self,
        taxonomy_system: Optional[str] = None,
        taxonomy_version: Optional[str] = None,
        industry_code: Optional[str] = None,
        sw_index_code: Optional[str] = None,
        max_age_days: Optional[int] = None,
        include_symbols: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Any:
        """获取行业成分股数据"""
        params = {
            "taxonomy_system": taxonomy_system,
            "taxonomy_version": taxonomy_version,
            "industry_code": industry_code,
            "sw_index_code": sw_index_code,
            "max_age_days": max_age_days,
            "include_symbols": include_symbols,
            "limit": limit,
            "offset": offset,
        }
        return self._research_request("/research/industry/component-sets", params)

    def get_industry_index_analysis(
        self,
        taxonomy_system: Optional[str] = None,
        taxonomy_version: Optional[str] = None,
        sw_index_code: Optional[str] = None,
        index_type: Optional[str] = None,
        trade_date: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        include_payload: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Any:
        """获取行业指数分析数据"""
        params = {
            "taxonomy_system": taxonomy_system,
            "taxonomy_version": taxonomy_version,
            "sw_index_code": sw_index_code,
            "index_type": index_type,
            "trade_date": self.format_date(trade_date) if trade_date else None,
            "start_date": self.format_date(start_date) if start_date else None,
            "end_date": self.format_date(end_date) if end_date else None,
            "include_payload": include_payload,
            "limit": limit,
            "offset": offset,
        }
        return self._research_request("/research/industry/index-analysis", params)

    def get_industry_index_analysis_latest(
        self,
        sw_index_code: str,
        taxonomy_system: Optional[str] = None,
        taxonomy_version: Optional[str] = None,
        include_payload: Optional[bool] = None,
    ) -> Any:
        """获取行业指数最新分析数据"""
        params = {
            "taxonomy_system": taxonomy_system,
            "taxonomy_version": taxonomy_version,
            "include_payload": include_payload,
        }
        return self._research_request(
            f"/research/industry/index-analysis/{sw_index_code}/latest", params
        )

    # ==================== 期货数据接口 ====================

    def get_futures_instruments(self, active_only: bool = True) -> Any:
        """
        获取期货品种列表

        参数:
        - active_only: 仅返回活跃品种，默认True

        返回:
        - 期货品种列表，含 instrument_id/symbol/name/exchange/category 等
        """
        return self._research_request(
            "/research/futures/instruments",
            params={"active_only": active_only},
        )

    def get_futures_instrument_detail(self, instrument_id: str) -> Any:
        """
        获取期货品种详情

        参数:
        - instrument_id: 期货品种ID，例如 "CNF.AG.SHFE"（上海白银）

        返回:
        - 期货品种详情，含合约规格、最小变动价位等
        """
        return self._research_request(f"/research/futures/instruments/{instrument_id}")

    def get_futures_contracts(
        self,
        instrument_id: Optional[str] = None,
        exchange: Optional[str] = None,
        contract_month: Optional[str] = None,
        active_only: bool = True,
    ) -> Any:
        """
        获取期货合约列表

        参数:
        - instrument_id: 期货品种ID（可选），例如 "CNF.AG.SHFE"
        - exchange: 交易所（可选），如 SHFE/DCE/CZCE/INE/GFEX
        - contract_month: 合约月份（可选），格式 YYYYMM
        - active_only: 仅返回活跃合约，默认True

        返回:
        - 期货合约列表
        """
        params = {
            "instrument_id": instrument_id,
            "exchange": exchange,
            "contract_month": contract_month,
            "active_only": active_only,
        }
        return self._research_request("/research/futures/contracts", params=params)

    def get_futures_contract_prices(
        self,
        contract_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Any:
        """
        获取期货合约价格序列

        参数:
        - contract_id: 合约ID，例如 "CNF.AG.SHFE.AG2506"
        - start_date: 开始日期，格式 YYYY-MM-DD（可选）
        - end_date: 结束日期，格式 YYYY-MM-DD（可选）
        - limit: 返回数据点数量限制

        返回:
        - 合约价格序列，含 open/high/low/close/volume 等
        """
        params = {"start_date": start_date, "end_date": end_date, "limit": limit}
        return self._research_request(
            f"/research/futures/contracts/{contract_id}/prices", params=params
        )

    def get_futures_series(
        self,
        instrument_id: Optional[str] = None,
        series_type: Optional[str] = None,
        active_only: bool = True,
    ) -> Any:
        """
        获取期货连续序列列表

        参数:
        - instrument_id: 期货品种ID（可选）
        - series_type: 序列类型（可选），如 main_continuous
        - active_only: 仅返回活跃序列，默认True

        返回:
        - 连续序列列表，含 series_id/symbol/source 等
        """
        params = {
            "instrument_id": instrument_id,
            "series_type": series_type,
            "active_only": active_only,
        }
        return self._research_request("/research/futures/series", params=params)

    def get_futures_series_prices(
        self,
        series_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Any:
        """
        获取期货连续序列价格

        参数:
        - series_id: 序列ID，例如 "CNF.AG.SHFE.main"
        - start_date: 开始日期，格式 YYYY-MM-DD（可选）
        - end_date: 结束日期，格式 YYYY-MM-DD（可选）
        - limit: 返回数据点数量限制

        返回:
        - 序列价格，数据量较大（约4MB/序列），建议限定日期范围

        说明:
        - series_id 含点号，已在内部处理 URL 编码
        - 该接口响应较慢（约30秒），请耐心等待
        """
        import urllib.parse
        encoded_sid = urllib.parse.quote(series_id, safe="")
        params = {"start_date": start_date, "end_date": end_date, "limit": limit}
        return self._research_request(
            f"/research/futures/{encoded_sid}/prices", params=params, timeout=120
        )

    def get_futures_series_mapping(
        self,
        series_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Any:
        """
        获取期货连续序列主力映射

        参数:
        - series_id: 序列ID，例如 "CNF.AG.SHFE.main"
        - start_date: 开始日期，格式 YYYY-MM-DD（可选）
        - end_date: 结束日期，格式 YYYY-MM-DD（可选）
        - limit: 返回数据点数量限制

        返回:
        - 主力映射，记录每个交易日主力合约的切换历史
        """
        import urllib.parse
        encoded_sid = urllib.parse.quote(series_id, safe="")
        params = {"start_date": start_date, "end_date": end_date, "limit": limit}
        return self._research_request(
            f"/research/futures/{encoded_sid}/mapping", params=params, timeout=120
        )

    def get_futures_cycle_diagnostics(
        self,
        series_id: str,
        as_of_date: Optional[str] = None,
    ) -> Any:
        """
        获取期货连续序列周期诊断

        参数:
        - series_id: 序列ID，例如 "CNF.AG.SHFE.main"
        - as_of_date: 诊断截止日期，格式 YYYY-MM-DD（可选）

        返回:
        - 周期诊断数据，含主力合约切换周期、移仓换月统计等
        """
        import urllib.parse
        encoded_sid = urllib.parse.quote(series_id, safe="")
        params = {"as_of_date": as_of_date}
        return self._research_request(
            f"/research/futures/{encoded_sid}/cycle-diagnostics", params=params
        )

    def get_futures_default_prices(
        self,
        instrument_id: str,
        series_type: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: Optional[int] = None,
        include_lineage: bool = False,
    ) -> Any:
        """
        获取期货默认价格序列（按品种ID查询，后端自动选择主连序列）

        参数:
        - instrument_id: 期货品种ID，例如 "CNF.AG.SHFE"
        - series_type: 序列类型（可选），默认由后端选择主连
        - start_date: 开始日期，格式 YYYY-MM-DD（可选）
        - end_date: 结束日期，格式 YYYY-MM-DD（可选）
        - limit: 返回数据点数量限制
        - include_lineage: 是否包含数据来源溯源，默认False

        返回:
        - 价格序列
        """
        params = {
            "instrument_id": instrument_id,
            "series_type": series_type,
            "start_date": start_date,
            "end_date": end_date,
            "limit": limit,
            "include_lineage": include_lineage,
        }
        return self._research_request("/research/futures/prices", params=params, timeout=60)

    def get_futures_calendar(
        self,
        exchange: Optional[str] = None,
        instrument_id: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        trading_only: bool = False,
    ) -> Any:
        """
        获取期货交易日历

        参数:
        - exchange: 交易所（可选），如 SHFE/DCE/CZCE/INE/GFEX
        - instrument_id: 期货品种ID（可选）
        - start_date: 开始日期，格式 YYYY-MM-DD（建议必填，否则后端拉全量会超时）
        - end_date: 结束日期，格式 YYYY-MM-DD（建议必填）
        - trading_only: 仅返回交易日，默认False

        返回:
        - 期货交易日历列表

        说明:
        - 不限定日期范围会拉取全量历史（数千条），后端响应慢易超时
        - 建议总是提供 start_date 和 end_date
        """
        params = {
            "exchange": exchange,
            "instrument_id": instrument_id,
            "start_date": start_date,
            "end_date": end_date,
            "trading_only": trading_only,
        }
        return self._research_request(
            "/research/futures/calendar", params=params, timeout=30
        )

    def get_futures_readiness(self, exchange: Optional[str] = None) -> Any:
        """
        获取期货模块就绪状态

        参数:
        - exchange: 交易所（可选），用于过滤就绪状态

        返回:
        - 就绪状态，含 enabled_series_count/p0_ready_count/scope_selection 等
        """
        params = {"exchange": exchange}
        return self._research_request(
            "/research/futures/readiness", params=params, timeout=30
        )

    def get_futures_dictionary(self) -> Any:
        """
        获取期货字典（分类、字段说明等元数据）

        返回:
        - 字典数据，含 categories/fields 等
        """
        return self._research_request("/research/futures/dictionary")

    # ==================== 商品数据接口 ====================

    def get_commodities_dictionary(self) -> Any:
        """
        获取商品字典（含序列元数据、治理信息等）

        返回:
        - 字典数据，含 instruments/series/master_governance 等
        """
        return self._research_request("/research/commodities/dictionary")

    def get_commodities_series(self, active_only: bool = True) -> Any:
        """
        获取商品序列列表

        涵盖伦铜/伦铝/伦铅/伦镍/伦锡/伦锌(LME)、布油/WTI、动力煤/港口煤价/煤炭运价、
        国内化工现货(PTA/甲醇/PVC/纯碱等)、海外农产品(大豆/玉米/棉花等)等47个序列。

        参数:
        - active_only: 仅返回活跃序列，默认True

        返回:
        - 序列列表，含 series_id/unit/source 等
        """
        return self._research_request(
            "/research/commodities/series",
            params={"active_only": active_only},
        )

    def get_commodities_observations(
        self,
        series_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Any:
        """
        获取商品价格观测序列（必填 series_id）

        参数:
        - series_id: 商品序列ID，例如:
            "CMD.METAL.COPPER.LME3M.DAILY"        伦铜(3个月)
            "CMD.OIL.BRENT.SPOT.EIA.DAILY"        布伦特原油
            "CMD.OIL.WTI.SPOT.EIA.DAILY"          WTI原油
            "CMD.CN.COAL.THERMAL.SHANXI_BLEND_5500.NBS.TEN_DAY"  动力煤山西5500
            "CMD.CN.COAL.PORT_PRICE.BSPI.CCTDA.WEEKLY"           港口动力煤价格
            "CMD.CN.COAL.FREIGHT.CBCFI.SSE.DAILY"               煤炭运价指数
        - start_date: 开始日期 YYYY-MM-DD（可选）
        - end_date: 结束日期 YYYY-MM-DD（可选）

        返回:
        - 价格观测序列，含 observation_date/value/unit/quality_flag 等
        """
        return self._research_request(
            "/research/commodities/observations",
            params={"series_id": series_id, "start_date": start_date, "end_date": end_date},
            timeout=60,
        )

    def get_commodities_diagnostics(self) -> Any:
        """
        获取商品数据诊断信息（序列数、最新观测、缺失观测等）

        返回:
        - 诊断数据，含 series_count/latest_observations/missing_observation_series 等
        """
        return self._research_request("/research/commodities/diagnostics")

    def get_commodities_indicators(
        self,
        category: Optional[str] = None,
        series_id: Optional[str] = None,
    ) -> Any:
        """
        获取商品指标（衍生指标，如均值/分位数等）

        参数:
        - category: 指标类别（可选）
        - series_id: 序列ID（可选）

        返回:
        - 指标数据，含 category/series/observations 等
        """
        return self._research_request(
            "/research/commodities/indicators",
            params={"category": category, "series_id": series_id},
        )

    def get_commodities_policy_events(
        self,
        commodity_id: Optional[str] = None,
    ) -> Any:
        """
        获取商品政策事件（如关税、出口配额、限产政策等）

        参数:
        - commodity_id: 商品ID（可选）

        返回:
        - 政策事件列表，含 commodity_id/events/count 等
        """
        return self._research_request(
            "/research/commodities/policy-events",
            params={"commodity_id": commodity_id},
        )

    # ==================== 外汇数据接口 ====================

    def get_fx_dictionary(self) -> Any:
        """
        获取外汇字典（货币、序列、来源等元数据）

        支持货币: CNY(在岸人民币)/CNH(离岸人民币)/USD/EUR/JPY

        返回:
        - 字典数据，含 currencies/instruments/series/source_manifests 等
        """
        return self._research_request("/research/fx/dictionary")

    def get_fx_series(self, active_only: bool = True) -> Any:
        """
        获取外汇序列列表

        涵盖人民币对美元/欧元/日元的 CFETS中间价、离岸市场即期价、衍生价等9个序列。

        参数:
        - active_only: 仅返回活跃序列，默认True

        返回:
        - 序列列表，含 series_id/base_currency/quote_currency 等
        """
        return self._research_request(
            "/research/fx/series",
            params={"active_only": active_only},
        )

    def get_fx_rates(
        self,
        series_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Any:
        """
        获取外汇汇率序列（必填 series_id）

        参数:
        - series_id: 外汇序列ID，例如:
            "FX.USD_CNY.CFETS.MID.DAILY"    人民币对美元(CFETS中间价)
            "FX.EUR_CNY.CFETS.MID.DAILY"    人民币对欧元(CFETS中间价)
            "FX.JPY_CNY.CFETS.MID.DAILY"    人民币对日元(CFETS中间价)
            "FX.USD_CNH.MARKET.SPOT.DAILY"  美元兑离岸人民币(市场即期)
        - start_date: 开始日期 YYYY-MM-DD（可选）
        - end_date: 结束日期 YYYY-MM-DD（可选）
        - limit: 最大返回行数，1-10000（可选）

        返回:
        - 汇率序列，含 observation_date/value/base_currency/quote_currency 等
        """
        return self._research_request(
            "/research/fx/rates",
            params={
                "series_id": series_id,
                "start_date": start_date,
                "end_date": end_date,
                "limit": limit,
            },
            timeout=60,
        )

    def convert_fx(
        self,
        from_currency: str,
        to_currency: str,
        amount: float = 1.0,
        date: Optional[str] = None,
        max_lag_days: Optional[int] = None,
    ) -> Any:
        """
        外汇换算（将一种货币金额换算为另一种货币）

        参数:
        - from_currency: 源币种，如 "CNY"/"USD"/"EUR"/"JPY"/"CNH"
        - to_currency: 目标币种
        - amount: 源币种金额，默认1.0
        - date: 换算日期 YYYY-MM-DD（可选，默认最新）
        - max_lag_days: 最大允许滞后自然日（可选）

        返回:
        - 换算结果，含 converted_amount/rate/fx_date/source_profile 等
        """
        return self._research_request(
            "/research/fx/convert",
            params={
                "from_currency": from_currency,
                "to_currency": to_currency,
                "amount": amount,
                "date": date,
                "max_lag_days": max_lag_days,
            },
        )

    def get_fx_indices(self) -> Any:
        """
        获取外汇指数列表（如美元贸易加权指数等）

        返回:
        - 指数列表，含 index_id/series 等
        """
        return self._research_request("/research/fx/indices")

    def get_fx_index_observations(
        self,
        series_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Any:
        """
        获取外汇指数观测序列（必填 series_id）

        参数:
        - series_id: 外汇指数序列ID，如 "FXI.USD_TRADE_WEIGHTED.FRED.DAILY"
        - start_date: 开始日期 YYYY-MM-DD（可选）
        - end_date: 结束日期 YYYY-MM-DD（可选）
        - limit: 最大返回行数，1-10000（可选）

        返回:
        - 指数观测序列
        """
        return self._research_request(
            "/research/fx/index-observations",
            params={
                "series_id": series_id,
                "start_date": start_date,
                "end_date": end_date,
                "limit": limit,
            },
            timeout=60,
        )

    def get_fx_readiness(self) -> Any:
        """
        获取外汇模块就绪状态

        返回:
        - 就绪状态，含 enabled/blockers/warnings/coverage 等
        """
        return self._research_request("/research/fx/readiness")

    # ==================== 无风险利率接口 ====================

    def get_risk_free_rate_series(self) -> Any:
        """
        获取无风险利率序列列表

        当前包含: china_treasury_10y（中国10年期国债到期收益率，日度）

        返回:
        - 序列列表，含 series_id/name/tenor/currency/frequency 等
        """
        return self._research_request("/research/risk-free-rate/series")

    def get_risk_free_rate(
        self,
        series_id: str = "china_treasury_10y",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Any:
        """
        获取无风险利率观测序列（默认中国10年期国债收益率）

        参数:
        - series_id: 序列标识，默认 "china_treasury_10y"
        - start_date: 起始日期 YYYY-MM-DD（可选，含）
        - end_date: 结束日期 YYYY-MM-DD（可选，含）

        返回:
        - 利率序列，含 observation_date/value/source 等
        """
        return self._research_request(
            "/research/risk-free-rate",
            params={
                "series_id": series_id,
                "start_date": start_date,
                "end_date": end_date,
            },
            timeout=60,
        )

    # ==================== 财务 PIT 面板接口 ====================
    # 说明：PIT (Point-In-Time) 面板提供"在任意历史时点 T 返回全市场每只股票
    # 截至 T 已公告的最新一期财务横截面"，无未来函数（弱 PIT：时间严格、
    # 数值取最新口径并带更正防护）。日期参数统一 YYYYMMDD 格式。

    def get_financial_pit_cross_section(
        self,
        as_of: str,
        report_period: Optional[str] = None,
        exchange: Optional[str] = None,
        fields: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> Any:
        """
        调仓日财务横截面（主接口）：一次调用返回全市场每只股票截至 as_of 已公告的最新一期财务数据

        参数:
        - as_of: 时点 YYYYMMDD（必填），返回每票 available_at <= as_of 的最新报告期
        - report_period: 时点装配后再按报告期过滤（可选，YYYYMMDD）
        - exchange: 交易所过滤 SSE/SZSE/BSE，逗号分隔（可选）
        - fields: 字段投影，逗号分隔（可选，减少返回体积）
        - limit: 单页上限 2000（可选）
        - offset: 分页偏移（可选）

        返回:
        - guard（恒 strict）、universe_note（含 latest_complete_period 与披露窗口内
          新期的 incomplete 状态）、stats（各类质量分布）、items[]（财务字段）
        """
        params = {"as_of": as_of}
        if report_period is not None:
            params["report_period"] = report_period
        if exchange is not None:
            params["exchange"] = exchange
        if fields is not None:
            params["fields"] = fields
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset
        return self._research_request(
            "/research/financials/pit/cross-section", params=params, timeout=120
        )

    def get_financial_pit_panel(
        self,
        report_period: Optional[str] = None,
        instrument_id: Optional[str] = None,
        available_at_lte: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> Any:
        """
        财务面板原始行分页（供本地全量缓存后离线装配）

        参数:
        - report_period: 报告期过滤 YYYYMMDD（可选）
        - instrument_id: 单只股票过滤，如 "000001.SZ"（可选）
        - available_at_lte: 仅返回 available_at <= 该日期的行 YYYYMMDD（可选）
        - limit: 单页上限 2000（可选）
        - offset: 分页偏移（可选）

        返回:
        - total 总行数、items[] 面板原始行、universe_note
        """
        params = {}
        if report_period is not None:
            params["report_period"] = report_period
        if instrument_id is not None:
            params["instrument_id"] = instrument_id
        if available_at_lte is not None:
            params["available_at_lte"] = available_at_lte
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset
        return self._research_request(
            "/research/financials/pit/panel", params=params, timeout=120
        )

    def get_financial_pit_coverage(self, report_period: Optional[str] = None) -> Any:
        """
        面板覆盖与数据质量自检

        参数:
        - report_period: 仅查询指定报告期（可选，YYYYMMDD）

        返回:
        - 逐期实际数/应有数/集合差缺口、available_at_quality / attribution_quality /
          share_validation 三组分布、revised_after_publish 行数、is_complete 标记
        """
        params = {}
        if report_period is not None:
            params["report_period"] = report_period
        return self._research_request(
            "/research/financials/pit/coverage", params=params, timeout=120
        )

    def get_financial_pit_changes(
        self, cursor: Optional[str] = None, limit: Optional[int] = None
    ) -> Any:
        """
        增量变更流（游标轮询，重放幂等）

        参数:
        - cursor: 游标（首次省略，用返回的 next_cursor 继续轮询）
        - limit: 单页条数（可选）

        返回:
        - next_cursor / has_more / entries[]（含 sequence_id / instrument_id /
          report_period / change_type / dataset）
        """
        params = {}
        if cursor is not None:
            params["cursor"] = cursor
        if limit is not None:
            params["limit"] = limit
        return self._research_request(
            "/research/financials/pit/changes", params=params, timeout=120
        )

    # ==================== 时点行业接口 ====================

    def get_industries_as_of(
        self,
        as_of: str,
        taxonomy_system: Optional[str] = None,
        exchange: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> Any:
        """
        批量时点行业分类

        注意：as_of 当日无生效分类的股票不返回（不回填最新分类），
        行业中性化请严格按此关联，避免未来函数。

        参数:
        - as_of: 时点 YYYYMMDD（必填）
        - taxonomy_system: 分类体系（可选，如 sw / sw2021）
        - exchange: 交易所过滤 SSE/SZSE/BSE（可选）
        - limit: 单页上限（可选）
        - offset: 分页偏移（可选）

        返回:
        - items[]（instrument_id / industry_code / industry_name / taxonomy_system /
          effective_from / effective_to）
        """
        params = {"as_of": as_of}
        if taxonomy_system is not None:
            params["taxonomy_system"] = taxonomy_system
        if exchange is not None:
            params["exchange"] = exchange
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset
        return self._research_request(
            "/research/industries/as-of", params=params, timeout=120
        )

    def get_company_industry_as_of(
        self,
        instrument_id: str,
        as_of_date: str,
        taxonomy_system: Optional[str] = None,
        include_snapshot: bool = False,
    ) -> Any:
        """
        单票时点行业归属查询

        参数:
        - instrument_id: 交易品种ID，如 "600519.SH"（必填）
        - as_of_date: 时点日期，**必须为 YYYY-MM-DD 格式**（如 "2026-08-01"），
          传 YYYYMMDD 会触发 422；调用方可传任意格式，本方法内部转换
        - taxonomy_system: 分类体系（可选，如 "sw"）
        - include_snapshot: 是否包含行业快照明细（可选，默认 False）

        返回:
        - instrument_id / official_industry_code / industry_name / taxonomy_system /
          taxonomy_version / effective_date / expiry_date / source / source_mode 等
        """
        params = {
            "as_of_date": _to_iso_date(as_of_date),
            "include_snapshot": include_snapshot,
        }
        if taxonomy_system is not None:
            params["taxonomy_system"] = taxonomy_system
        return self._research_request(
            f"/research/company/{instrument_id}/industry/as-of",
            params=params,
            timeout=60,
        )

    def close(self):
        """关闭HTTP会话"""
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# ==================== 技术指标分析器 ====================

class TechnicalAnalyzer:
    """股票技术指标分析器（本地计算）"""

    def __init__(self, df: pd.DataFrame):
        """
        初始化分析器

        参数:
        - df: 包含行情数据的DataFrame
        """
        self.df = df.copy()
        self._prepare_numeric_columns()

    def _prepare_numeric_columns(self):
        """将价格列转换为数值类型，确保计算正确"""
        for col in ["close", "high", "low", "open"]:
            if col in self.df.columns:
                self.df[col] = pd.to_numeric(self.df[col], errors="coerce")

    def calculate_ma(self, periods: List[int] = None):
        """
        计算移动平均线

        参数:
        - periods: 周期列表，默认 [20, 50, 200]
        """
        if periods is None:
            periods = [20, 50, 200]
        for period in periods:
            self.df[f"ma{period}"] = self.df["close"].rolling(window=period).mean()
        return self.df

    def calculate_macd(self, fast_period: int = 12, slow_period: int = 26, signal_period: int = 9):
        """
        计算MACD指标

        参数:
        - fast_period: 快速EMA周期
        - slow_period: 慢速EMA周期
        - signal_period: 信号线EMA周期
        """
        ema_fast = self.df["close"].ewm(span=fast_period, adjust=False).mean()
        ema_slow = self.df["close"].ewm(span=slow_period, adjust=False).mean()
        self.df["dif"] = ema_fast - ema_slow
        self.df["dea"] = self.df["dif"].ewm(span=signal_period, adjust=False).mean()
        self.df["macd"] = 2 * (self.df["dif"] - self.df["dea"])
        return self.df

    def calculate_rsi(self, period: int = 14):
        """
        计算RSI指标

        参数:
        - period: RSI周期
        """
        delta = self.df["close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        self.df[f"rsi{period}"] = 100 - (100 / (1 + rs))
        return self.df

    def calculate_bollinger_bands(self, period: int = 20, num_std: float = 2.0):
        """
        计算布林带

        参数:
        - period: 周期
        - num_std: 标准差倍数
        """
        self.df["bb_middle"] = self.df["close"].rolling(window=period).mean()
        self.df["bb_std"] = self.df["close"].rolling(window=period).std()
        self.df["bb_upper"] = self.df["bb_middle"] + (self.df["bb_std"] * num_std)
        self.df["bb_lower"] = self.df["bb_middle"] - (self.df["bb_std"] * num_std)
        return self.df

    def calculate_kdj(self, n: int = 9, m1: int = 3, m2: int = 3):
        """
        计算KDJ指标

        参数:
        - n: RSV周期
        - m1: K值平滑周期
        - m2: D值平滑周期
        """
        self.df["high_n"] = self.df["high"].rolling(window=n).max()
        self.df["low_n"] = self.df["low"].rolling(window=n).min()
        self.df["rsv"] = (self.df["close"] - self.df["low_n"]) / (self.df["high_n"] - self.df["low_n"]) * 100
        self.df["k"] = self.df["rsv"].ewm(com=m1 - 1, adjust=False).mean()
        self.df["d"] = self.df["k"].ewm(com=m2 - 1, adjust=False).mean()
        self.df["j"] = 3 * self.df["k"] - 2 * self.df["d"]
        return self.df

    def calculate_atr(self, period: int = 14):
        """
        计算ATR指标

        参数:
        - period: ATR周期
        """
        self.df["tr1"] = self.df["high"] - self.df["low"]
        self.df["tr2"] = abs(self.df["high"] - self.df["close"].shift(1))
        self.df["tr3"] = abs(self.df["low"] - self.df["close"].shift(1))
        self.df["tr"] = self.df[["tr1", "tr2", "tr3"]].max(axis=1)
        self.df[f"atr{period}"] = self.df["tr"].rolling(window=period).mean()
        return self.df

    def calculate_all(self):
        """计算所有技术指标"""
        self.calculate_ma([20, 50, 200])
        self.calculate_macd()
        self.calculate_rsi()
        self.calculate_bollinger_bands()
        self.calculate_kdj()
        self.calculate_atr()
        return self.df


# ==================== 本地技术分析公共方法 ====================

def compute_local_technical(
    api: StockQuoteAPI,
    stock_code: str,
    start_date: str,
    end_date: str,
    calc_fn,
    max_period: int,
    **calc_kwargs,
) -> Dict[str, Any]:
    """
    本地技术分析的公共计算方法，消除重复代码

    统一处理：日期调整（提前获取预热数据）、获取行情、执行计算、
    过滤日期范围、数值精度控制。

    参数:
    - api: StockQuoteAPI实例
    - stock_code: 6位股票代码
    - start_date: 用户请求的开始日期
    - end_date: 用户请求的结束日期
    - calc_fn: 计算函数，接收analyzer和**calc_kwargs
    - max_period: 需要提前的最大数据周期
    - calc_kwargs: 传递给calc_fn的参数

    返回:
    - 包含技术分析数据的字典
    """
    user_start_datetime = pd.to_datetime(start_date)
    # 提前获取足够的历史数据用于指标预热
    days_to_advance = max(int(max_period * 2.5), 365)
    adjusted_start_date = (user_start_datetime - pd.Timedelta(days=days_to_advance)).strftime("%Y-%m-%d")

    df = api.get_daily_quotes_df(stock_code, adjusted_start_date, end_date)
    if df.empty:
        return {
            "stock_code": stock_code,
            "start_date": start_date,
            "end_date": end_date,
            "message": "未获取到数据",
            "data": [],
        }

    analyzer = TechnicalAnalyzer(df)
    calc_fn(analyzer, **calc_kwargs)

    result_df = analyzer.df.reset_index()
    result_df["time"] = result_df["time"].dt.strftime("%Y-%m-%d %H:%M:%S")

    # 过滤到用户请求的日期范围
    user_end_datetime = pd.to_datetime(end_date)
    result_df["time_datetime"] = pd.to_datetime(result_df["time"])
    filtered_df = result_df[
        (result_df["time_datetime"] >= user_start_datetime)
        & (result_df["time_datetime"] <= user_end_datetime)
    ]
    filtered_df = filtered_df.drop(columns=["time_datetime"])

    # 数值精度控制：保留2位小数
    for col in filtered_df.columns:
        if pd.api.types.is_numeric_dtype(filtered_df[col]):
            filtered_df[col] = filtered_df[col].round(2)

    return {
        "stock_code": stock_code,
        "start_date": start_date,
        "end_date": end_date,
        "data": filtered_df.to_dict(orient="records"),
    }


# ==================== MCP工具异常保护装饰器 ====================

def safe_tool(func):
    """
    MCP工具异常保护装饰器

    捕获工具函数中的所有异常，返回包含error字段的dict，
    防止MCP工具因未处理异常而崩溃。
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            result = func(*args, **kwargs)
            # 确保返回值是dict
            return ensure_dict(result)
        except ValueError as e:
            logger.warning(f"输入验证失败 [{func.__name__}]: {e}")
            return {"error": str(e)}
        except Exception as e:
            logger.error(f"工具执行异常 [{func.__name__}]: {e}", exc_info=True)
            return {"error": f"执行失败: {e}"}

    return wrapper


def _resolve_instrument_id(stock_code: Optional[str], instrument_id: Optional[str]) -> str:
    """
    统一处理 stock_code 和 instrument_id 参数，返回后端需要的 instrument_id

    调用方可能传 stock_code（6位代码如 "600519"）或 instrument_id（带后缀如 "600519.SH"），
    本函数统一转换为 instrument_id 格式。

    参数:
    - stock_code: 6位股票代码，例如 "600519"（也兼容带后缀的 "600519.SH"）
    - instrument_id: 交易品种ID，例如 "600519.SH"

    返回:
    - instrument_id 字符串

    异常:
    - ValueError: 两个参数都为空时抛出
    """
    if instrument_id:
        return instrument_id
    if stock_code:
        # 兼容用户传带后缀的 stock_code（如 "600519.SH"），去掉后缀再转换
        if "." in stock_code:
            stock_code = stock_code.split(".")[0]
        return stock_api.make_instrument_id(stock_code)
    raise ValueError("请提供 stock_code 或 instrument_id 参数")


def _normalize_pit_date(value: Optional[str]) -> Optional[str]:
    """
    归一化 PIT 面板日期参数为 YYYYMMDD 格式

    后端 PIT 系列接口要求 YYYYMMDD（如 "20260801"），但调用方常传
    "2026-08-01" 或 "2026/08/01"，本函数统一去除分隔符以避免 422 校验错误。

    参数:
    - value: 日期字符串，支持 "20260801" / "2026-08-01" / "2026/08/01"

    返回:
    - 8位纯数字日期字符串；输入为空时原样返回 None
    """
    if not value:
        return None
    # 去除常见分隔符（- / 空格），保留纯数字
    cleaned = str(value).strip().replace("-", "").replace("/", "").replace(" ", "")
    return cleaned


def _to_iso_date(value: Optional[str]) -> Optional[str]:
    """
    将日期参数转换为 ISO 格式 YYYY-MM-DD

    注意：单票时点行业接口 /research/company/{id}/industry/as-of 的 as_of_date
    参数类型为 date，只接受 YYYY-MM-DD；传 YYYYMMDD 会触发 422
    （"Datetimes provided to dates should have zero time"）。
    这与批量 /research/industries/as-of 要求 YYYYMMDD 的行为相反。

    参数:
    - value: 日期字符串，支持 "20260801" / "2026-08-01" / "2026/08/01"

    返回:
    - "YYYY-MM-DD" 格式字符串；无法解析为8位数字时原样返回；输入为空返回 None
    """
    if not value:
        return None
    raw = str(value).strip()
    cleaned = raw.replace("-", "").replace("/", "").replace(" ", "")
    # 仅当能还原出8位纯数字时才补分隔符，否则原样透传给后端做校验
    if len(cleaned) == 8 and cleaned.isdigit():
        return f"{cleaned[0:4]}-{cleaned[4:6]}-{cleaned[6:8]}"
    return raw


# ==================== MCP服务器 ====================

mcp = FastMCP("StockIntegratedMCP")
stock_api = StockQuoteAPI()


# ==================== 响应口径归一化与裁剪 ====================
# 说明：以下辅助函数用于消化后端接口的口径缺陷，只做「派生 / 标注 / 裁剪」，
# 不修改任何原始字段、不重算复权因子，保证数值可逐字段回溯。

# 行情字段单位声明（P0-2：跨接口 pct_change 单位不一致，这里显式标注）
_QUOTE_UNITS = {
    "prices": "CNY",
    "amount": "CNY",
    "volume": "shares",
    "pct_change": "percent",  # 0.0689 表示 0.0689%
    "turnover": "percent",
    "factor": "ratio",
}

# 复权行口径提示：后端在 adjust=hfq 时同一行内混用三套口径
_QUOTE_BASIS_NOTE = (
    "adjust=hfq 时 open/high/low/close/volume 为后复权口径，"
    "pre_close/change 为未复权口径，amount 恒为真实元。"
    "计算涨跌幅请用 derived.pct_change_decimal 或 close_raw/pre_close-1；"
    "计算成交均价请用 amount/derived.volume_raw。"
)

# 交易日历缓存：{key: (交易日列表, 写入时间戳)}，避免每次行情调用都多打一次后端
_CALENDAR_CACHE: Dict[str, Any] = {}


def _calendar_trading_days(start_date: str, end_date: str,
                           exchange: str = "SSE") -> Optional[List[str]]:
    """
    获取区间内的交易日日期列表（ISO 字符串，升序）

    参数:
    - start_date / end_date: YYYY-MM-DD
    - exchange: 交易所，默认 SSE

    返回:
    - 交易日列表；接口失败返回 None（调用方需自行降级）

    说明:
    - 结果按 (exchange, 起止日期) 缓存 1 小时，避免行情接口每次调用都额外请求日历
    """
    key = f"{exchange}|{start_date}|{end_date}"
    cached = _CALENDAR_CACHE.get(key)
    if cached and time.time() - cached[1] < 3600:
        return cached[0]
    try:
        resp = stock_api.get_trading_calendar(exchange, start_date, end_date)
    except Exception as e:
        logger.warning(f"交易日历获取失败 {key}: {e}")
        return None
    if not isinstance(resp, list):
        return None
    days = sorted(
        str(item.get("date", ""))[:10]
        for item in resp
        if isinstance(item, dict) and item.get("is_trading_day")
    )
    days = [d for d in days if d]
    _CALENDAR_CACHE[key] = (days, time.time())
    return days


def _trading_day_lag(quote_date: str, today: str) -> Optional[int]:
    """
    计算行情日期相对今天滞后了几个交易日（0 表示同一交易日）

    参数:
    - quote_date: 行情业务日期 YYYY-MM-DD
    - today: 今天 YYYY-MM-DD

    返回:
    - 滞后交易日数；输入不完整时返回 None

    说明:
    - 优先用后端交易日历精确统计（剔除节假日）
    - 日历不可用时退回工作日估算，可能与节假日有偏差
    """
    if not quote_date or not today:
        return None
    if quote_date >= today:
        return 0
    days = _calendar_trading_days(quote_date, today)
    if days is not None:
        return len([d for d in days if d > quote_date])
    return int(np.busday_count(quote_date, today))


def _attach_quote_normalization(payload: Any) -> Any:
    """
    为行情响应补充复权口径派生字段与单位声明（P0-1 / P0-2 / P0-3 的调用方侧防护）

    背景:
    - 后端在 adjust=hfq 时，同一行里 open/high/low/close/volume 为后复权口径，
      而 pre_close/change 为未复权口径、amount 为真实元，且无字段标识口径。
      直接用 close/pre_close-1 算收益率会得到数量级错误的结果。
    - 本函数不修改原始字段，仅在 factor 存在且不等于 1 时，为每行新增 derived 子对象。

    派生规则（均为精确换算，实测校验见下）:
    - close_raw / open_raw / high_raw / low_raw = 原值 / factor
    - pre_close_adj = pre_close * factor（与复权价同口径）
    - volume_raw = volume * factor（真实股数），volume_adj = 原 volume
    - avg_price_raw = amount / volume_raw（真实成交均价）
    - pct_change_decimal = pct_change / 100（无量纲比例）

    实测校验（600519.SH / 2026-11-06 / hfq，factor=7.671096）:
    - close/factor = 1452.9999 ≈ 真实收盘 1453.0
    - volume*factor = 4284698 ≈ 真实股数 4284700
    - amount/(volume*factor) = 1446.90 元（真实均价）
    """
    rows = None
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = payload.get("data")
        payload["units"] = _QUOTE_UNITS

    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            factor = row.get("factor")
            # 仅复权行（factor 非 0/1）才需要派生，未复权行本身就自洽
            if not isinstance(factor, (int, float)) or factor in (0, 1):
                continue
            derived: Dict[str, Any] = {
                "price_basis": "adjusted",
                "note": _QUOTE_BASIS_NOTE,
            }
            for name in ("open", "high", "low", "close"):
                val = row.get(name)
                if isinstance(val, (int, float)):
                    derived[f"{name}_raw"] = round(val / factor, 4)
            pre_close = row.get("pre_close")
            if isinstance(pre_close, (int, float)):
                derived["pre_close_adj"] = round(pre_close * factor, 4)
            volume_raw = None
            volume = row.get("volume")
            if isinstance(volume, (int, float)):
                volume_raw = int(round(volume * factor))
                derived["volume_raw"] = volume_raw
                derived["volume_adj"] = volume
            amount = row.get("amount")
            if isinstance(amount, (int, float)) and volume_raw:
                derived["avg_price_raw"] = round(amount / volume_raw, 4)
            pct = row.get("pct_change")
            if isinstance(pct, (int, float)):
                derived["pct_change_decimal"] = round(pct / 100, 8)
            close = row.get("close")
            if isinstance(close, (int, float)) and "pre_close_adj" in derived:
                derived["change_adj"] = round(close - derived["pre_close_adj"], 4)
            row["derived"] = derived
    return payload


def _attach_quote_freshness(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    为最新行情响应补充时点标识（P1-2）

    背景: action=latest 返回的 time 只是交易日（不含时辰），且可能是上一交易日收盘，
    调用方无法判断数据滞后程度，容易误当实时价使用。

    产出字段（payload["freshness"]）:
    - quote_type: 固定 "snapshot"，表示快照而非交易所逐笔实时行情
    - as_of: 本次返回数据中最大的业务日期
    - staleness_trading_days: 相对今天滞后的交易日数（0=同一交易日）
    - is_same_trading_day: 是否当日数据
    - lag_source: 滞后天数来源（calendar=交易日历精确，estimate=工作日估算）
    - note: 使用提示
    """
    rows = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or not rows:
        return payload
    dates = [
        str(row.get("time", ""))[:10]
        for row in rows
        if isinstance(row, dict) and row.get("time")
    ]
    if not dates:
        return payload
    as_of = max(dates)
    today = datetime.now().strftime("%Y-%m-%d")
    lag = _trading_day_lag(as_of, today)
    # 判断滞后天数是否由交易日历精确得出，供调用方评估可信度
    lag_source = "calendar" if _calendar_trading_days(as_of, today) is not None else "estimate"
    payload["freshness"] = {
        "quote_type": "snapshot",
        "as_of": as_of,
        "request_date": today,
        "staleness_trading_days": lag,
        "is_same_trading_day": lag == 0,
        "lag_source": lag_source,
        "note": (
            "time 字段仅到交易日、不含时辰；本接口返回最近一次入库的快照，"
            "不是交易所逐笔实时行情。盘中决策请先确认 staleness_trading_days=0。"
        ),
    }
    return payload


# 财务响应裁剪用的字段白名单
_FINANCIAL_IDENTITY_KEYS = [
    "instrument_id", "symbol", "exchange", "report_period", "publish_date",
    "fiscal_year", "fiscal_quarter", "currency", "schema_version",
    "source", "source_mode", "data_as_of", "created_at", "updated_at",
    "ingestion_run_id",
]
_FINANCIAL_SUMMARY_KEYS = _FINANCIAL_IDENTITY_KEYS + [
    "revenue", "gross_profit", "operating_profit", "pre_tax_profit", "net_income",
    "operating_cf", "total_cf", "total_assets", "total_liabilities", "equity",
    "current_assets", "current_liabilities", "inventory", "receivables",
    "fixed_assets", "intangible_assets", "shares_outstanding",
]

# 财务指标单位说明：公司财务接口用小数，PIT 面板用百分数，两者不可混用
_FINANCIAL_UNITS = {
    "indicators.gross_margin": "decimal(0.8976 表示 89.76%)",
    "indicators.operating_margin": "decimal",
    "indicators.net_margin": "decimal",
    "indicators.roe": "decimal",
    "indicators.roa": "decimal",
    "indicators.asset_liability_ratio": "decimal",
    "pit_cross_section.gross_margin": "percent(89.76 表示 89.76%)",
    "note": "同一指标在公司财务接口与 PIT 面板中单位不同，跨接口拼接前必须换算",
}


def _compact_row(row: Dict[str, Any], fields: Optional[List[str]],
                 summary_only: bool) -> Dict[str, Any]:
    """
    单条财务记录的裁剪

    参数:
    - row: 原始财务记录
    - fields: 逗号分隔解析后的字段名列表，非空时只保留白名单外的指定字段
    - summary_only: 未指定 fields 时，是否仅保留摘要字段

    返回:
    - 裁剪后的新字典（不修改入参）
    """
    if fields:
        keep = set(_FINANCIAL_IDENTITY_KEYS) | set(fields)
        return {k: v for k, v in row.items() if k in keep}
    if not summary_only:
        return row
    compacted = {k: v for k, v in row.items() if k in _FINANCIAL_SUMMARY_KEYS}
    indicators = row.get("indicators")
    if isinstance(indicators, dict):
        # indicators.details 体积与 facts 相当，摘要模式下剔除
        compacted["indicators"] = {
            k: v for k, v in indicators.items() if k != "details"
        }
    return compacted


def _compact_financial(payload: Any, fields: Optional[str] = None,
                       summary_only: bool = False) -> Any:
    """
    财务报表响应裁剪（P1-1）

    背景:
    - 后端 /financial-statements 默认返回约 190KB，其中 facts 约 95KB、
      indicators.details 约 94KB，会超出调用方单次返回上限被落盘，接口实际不可用。
    - 后端未提供字段投影参数（requested_canonical_facts 只影响内部映射，实测不减小响应）。

    参数:
    - payload: 后端原始响应（dict 或 list）
    - fields: 逗号分隔字段名，如 "revenue,net_income,roe"
    - summary_only: 是否只保留顶层科目 + indicators 概览

    返回:
    - 裁剪后的响应；顶层带 _meta 说明裁剪范围，避免调用方误判数据缺失
    """
    field_list = [f.strip() for f in fields.split(",") if f.strip()] if fields else None
    if not field_list and not summary_only:
        return payload

    omitted: List[str] = []
    if isinstance(payload, dict):
        if isinstance(payload.get("data"), list):
            # 历史序列：逐行裁剪
            payload["data"] = [
                _compact_row(r, field_list, summary_only) if isinstance(r, dict) else r
                for r in payload["data"]
            ]
            omitted = ["data[].facts", "data[].statements", "data[].indicators.details"]
        else:
            compacted = _compact_row(payload, field_list, summary_only)
            omitted = [k for k in payload.keys() if k not in compacted] + \
                      (["indicators.details"] if field_list is None else [])
            payload = compacted
        payload["_meta"] = {
            "compacted": True,
            "summary_only": bool(summary_only and not field_list),
            "fields": field_list,
            "omitted": omitted,
            "units": _FINANCIAL_UNITS,
            "hint": "需要完整明细请传 summary_only=false；需要指定科目请传 fields='revenue,net_income'",
        }
    elif isinstance(payload, list):
        payload = [
            _compact_row(r, field_list, summary_only) if isinstance(r, dict) else r
            for r in payload
        ]
    return payload


# ==================== 原子工具注册控制 ====================
# 保存原始 mcp.tool 注册函数
_original_mcp_tool = mcp.tool


def _disabled_tool(*args, **kwargs):
    """禁用注册的空装饰器：原子工具保留函数定义但不对外暴露为MCP工具"""
    def decorator(func):
        return func
    return decorator


# 原子工具区：禁用 @mcp.tool() 注册，仅保留函数供聚合工具内部调用
mcp.tool = _disabled_tool


# ==================== 行情数据工具 ====================

@mcp.tool()
@safe_tool
def get_daily_stock_data(
    stock_code: Optional[str] = None,
    instrument_id: Optional[str] = None,
    start_date: str = "",
    end_date: str = "",
    adjust: Optional[str] = None,
    include_suspended: Optional[bool] = None,
    min_quality_score: Optional[float] = None,
    is_complete: Optional[bool] = None,
    min_volume: Optional[float] = None,
) -> Dict[str, Any]:
    """
    获取股票日度行情数据

    参数:
    - stock_code: 6位股票代码，例如 "601126"（与 instrument_id 二选一）
    - instrument_id: 交易品种ID，例如 "601126.SH"（与 stock_code 二选一）
    - start_date: 开始日期，格式 YYYY-MM-DD
    - end_date: 结束日期，格式 YYYY-MM-DD
    - adjust: 复权类型，可选 "qfq"(前复权)/"hfq"(后复权)，不传则不复权
    - include_suspended: 是否包含停牌日（透传后端；实测后端当前未按该参数过滤）
    - min_quality_score: 最低质量分（透传后端；实测后端当前未按该参数过滤）
    - is_complete: 是否只取完整交易日，传 true 可剔除停牌日（实测生效）
    - min_volume: 最小成交量，传 1 可剔除零成交的停牌日（实测生效）

    返回:
    - 包含股票行情数据的字典
    """
    # 统一解析股票标识，兼容 stock_code 和 instrument_id 两种传参方式
    iid = _resolve_instrument_id(stock_code, instrument_id)
    # get_daily_quotes 接受6位代码，从 instrument_id 中提取
    code = iid.split(".")[0]
    result = stock_api.get_daily_quotes(
        code, start_date, end_date, adjust=adjust,
        include_suspended=include_suspended,
        min_quality_score=min_quality_score,
        is_complete=is_complete,
        min_volume=min_volume,
    )
    # 复权行情补充派生字段（真实价/真实股数/真实均价），避免调用方跨口径误算
    result = _attach_quote_normalization(result)
    return ensure_dict(result, {"stock_code": code, "start_date": start_date, "end_date": end_date})


@mcp.tool()
@safe_tool
def get_latest_stock_data(
    stock_code: Optional[Union[str, list]] = None,
    instrument_id: Optional[Union[str, list]] = None,
) -> Dict[str, Any]:
    """
    获取股票最新行情数据，支持单个或多个股票

    参数:
    - stock_code: 6位股票代码，支持单个字符串或列表
      例如 "600519" 或 ["000001", "600000", "300708"]
    - instrument_id: 交易品种ID（带交易所后缀），支持单个或列表
      例如 "300285.SZ" 或 ["600519.SH", "000001.SZ"]

    说明: stock_code 和 instrument_id 二选一即可，工具会自动识别并处理

    返回:
    - 包含股票最新行情数据的字典
    """
    # 合并两个参数，优先使用 stock_code
    raw = stock_code if stock_code is not None else instrument_id
    if raw is None:
        return {"error": "请提供 stock_code 或 instrument_id 参数"}

    # 兼容单个字符串输入，自动转为列表
    if isinstance(raw, str):
        raw = [raw]
    else:
        raw = list(raw)

    # 统一转为6位纯数字代码（去掉 .SH/.SZ 等后缀）
    codes = []
    for item in raw:
        if isinstance(item, str) and "." in item:
            item = item.split(".")[0]  # 去掉交易所后缀
        codes.append(item)

    result = stock_api.get_latest_quotes(codes)
    result = ensure_dict(result, {"stock_codes": codes})
    # 补充单位声明 + 时点标识（quote_type/as_of/staleness_trading_days）
    result = _attach_quote_normalization(result)
    result = _attach_quote_freshness(result)
    return result


# ==================== 交易日历工具 ====================

@mcp.tool()
@safe_tool
def get_trading_calendar_data(
    exchange: str,
    start_date: str,
    end_date: str,
    include_weekends: Optional[bool] = None,
    session_type: Optional[str] = None,
) -> Dict[str, Any]:
    """
    获取交易日历数据

    参数:
    - exchange: 交易所代码，例如 "SSE" (上海证券交易所) 或 "SZSE" (深圳证券交易所)
    - start_date: 开始日期，格式 YYYY-MM-DD
    - end_date: 结束日期，格式 YYYY-MM-DD
    - include_weekends: 是否包含周末，默认不包含
    - session_type: 交易时段类型

    返回:
    - 包含交易日历数据的字典
    """
    result = stock_api.get_trading_calendar(
        exchange, start_date, end_date,
        include_weekends=include_weekends, session_type=session_type,
    )
    return ensure_dict(result, {"exchange": exchange, "start_date": start_date, "end_date": end_date})


# 本地降级方案：后端 /calendar/trading/next 和 /calendar/trading/previous 接口存在
# datetime类型不兼容的500 bug，改用 /calendar/trading 接口获取数据后本地计算

def _find_next_trading_day(api: StockQuoteAPI, exchange: str, date_str: str) -> Dict[str, Any]:
    """
    本地计算下一交易日（降级方案）

    通过获取参考日期前后15天的交易日历数据，
    筛选is_trading_day=True且日期>参考日期的记录。

    参数:
    - api: StockQuoteAPI实例
    - exchange: 交易所代码
    - date_str: 参考日期，格式 YYYY-MM-DD

    返回:
    - 包含下一交易日信息的字典
    """
    validate_exchange(exchange)
    validate_date(date_str, "参考日期")

    ref_date = pd.to_datetime(date_str)
    start = (ref_date - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    end = (ref_date + pd.Timedelta(days=15)).strftime("%Y-%m-%d")

    result = api.get_trading_calendar(exchange, start, end)
    items = result.get("data", []) if isinstance(result, dict) else result

    for item in items:
        item_date = pd.to_datetime(item.get("date", ""))
        if item.get("is_trading_day") and item_date > ref_date:
            return {
                "exchange": exchange,
                "reference_date": date_str,
                "next_trading_day": item_date.strftime("%Y-%m-%d"),
                "is_trading_day": True,
            }

    return {"exchange": exchange, "reference_date": date_str, "next_trading_day": None, "message": "未找到下一交易日"}


def _find_previous_trading_day(api: StockQuoteAPI, exchange: str, date_str: str) -> Dict[str, Any]:
    """
    本地计算上一交易日（降级方案）

    通过获取参考日期前后15天的交易日历数据，
    筛选is_trading_day=True且日期<参考日期的记录，取最近的一个。

    参数:
    - api: StockQuoteAPI实例
    - exchange: 交易所代码
    - date_str: 参考日期，格式 YYYY-MM-DD

    返回:
    - 包含上一交易日信息的字典
    """
    validate_exchange(exchange)
    validate_date(date_str, "参考日期")

    ref_date = pd.to_datetime(date_str)
    start = (ref_date - pd.Timedelta(days=15)).strftime("%Y-%m-%d")
    end = (ref_date - pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    result = api.get_trading_calendar(exchange, start, end)
    items = result.get("data", []) if isinstance(result, dict) else result

    prev_day = None
    for item in items:
        item_date = pd.to_datetime(item.get("date", ""))
        if item.get("is_trading_day") and item_date < ref_date:
            if prev_day is None or item_date > pd.to_datetime(prev_day):
                prev_day = item_date.strftime("%Y-%m-%d")

    if prev_day:
        return {
            "exchange": exchange,
            "reference_date": date_str,
            "previous_trading_day": prev_day,
            "is_trading_day": True,
        }

    return {"exchange": exchange, "reference_date": date_str, "previous_trading_day": None, "message": "未找到上一交易日"}


@mcp.tool()
@safe_tool
def get_next_trading_day(exchange: str, date: str) -> Dict[str, Any]:
    """
    获取指定日期之后的下一个交易日

    参数:
    - exchange: 交易所代码，例如 "SSE" 或 "SZSE"
    - date: 参考日期，格式 YYYY-MM-DD

    返回:
    - 包含下一交易日信息的字典
    """
    return _find_next_trading_day(stock_api, exchange, date)


@mcp.tool()
@safe_tool
def get_previous_trading_day(exchange: str, date: str) -> Dict[str, Any]:
    """
    获取指定日期之前的上一个交易日

    参数:
    - exchange: 交易所代码，例如 "SSE" 或 "SZSE"
    - date: 参考日期，格式 YYYY-MM-DD

    返回:
    - 包含上一交易日信息的字典
    """
    return _find_previous_trading_day(stock_api, exchange, date)


# ==================== 交易品种工具 ====================

@mcp.tool()
@safe_tool
def get_instruments(
    exchange: Optional[str] = None,
    instrument_type: Optional[str] = None,
    industry: Optional[str] = None,
    sector: Optional[str] = None,
    market: Optional[str] = None,
    is_active: Optional[bool] = None,
    is_st: Optional[bool] = None,
    limit: int = 100,
    offset: int = 0,
    sort_by: str = "symbol",
    sort_order: str = "asc",
) -> Dict[str, Any]:
    """
    获取交易品种列表，支持多维度筛选

    参数:
    - exchange: 交易所代码，例如 "SSE" 或 "SZSE"
    - instrument_type: 品种类型
    - industry: 行业
    - sector: 板块
    - market: 市场
    - is_active: 是否活跃
    - is_st: 是否ST股
    - limit: 返回数量限制，默认100，最大1000
    - offset: 偏移量，默认0
    - sort_by: 排序字段，默认 "symbol"
    - sort_order: 排序方向，默认 "asc"

    返回:
    - 包含交易品种列表的字典
    """
    result = stock_api.get_instruments(
        exchange=exchange, instrument_type=instrument_type,
        industry=industry, sector=sector, market=market,
        is_active=is_active, is_st=is_st,
        limit=limit, offset=offset, sort_by=sort_by, sort_order=sort_order,
    )
    return ensure_dict(result, {"exchange": exchange, "limit": limit, "offset": offset})


@mcp.tool()
@safe_tool
def get_stock_info(stock_code: str) -> Dict[str, Any]:
    """
    获取股票基本信息（根据6位股票代码查询）

    参数:
    - stock_code: 6位股票代码，例如 "300708" 或 "601126"

    返回:
    - 包含股票基本信息的字典
    """
    result = stock_api.get_instrument_info(stock_code)
    return ensure_dict(result, {"stock_code": stock_code})


@mcp.tool()
@safe_tool
def get_instrument_by_id(
    stock_code: Optional[str] = None,
    instrument_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    根据交易品种ID获取信息

    参数:
    - stock_code: 6位股票代码，例如 "600000"（与 instrument_id 二选一）
    - instrument_id: 交易品种ID，例如 "600000.SH"（与 stock_code 二选一）

    返回:
    - 包含交易品种信息的字典
    """
    iid = _resolve_instrument_id(stock_code, instrument_id)
    return stock_api.get_instrument_by_id(iid)


# ==================== 公司研究工具 ====================

# [后端500: instrument_id验证错误，暂不暴露]
# @mcp.tool()
# @safe_tool
# def get_company_overview(
#     instrument_id: str,
#     include_profile_snapshot: bool = False,
#     include_industry_snapshot: bool = False,
#     include_financial_snapshot: bool = False,
# ) -> Dict[str, Any]:
#     """
#     获取公司概览数据，包含公司基本信息、行业归属和财务摘要
# 
#     参数:
#     - instrument_id: 交易品种ID，例如 "600519.SH"
#     - include_profile_snapshot: 是否包含公司档案详情，默认False
#     - include_industry_snapshot: 是否包含行业归属详情，默认False
#     - include_financial_snapshot: 是否包含财务摘要详情，默认False
# 
#     返回:
#     - 包含公司概览数据的字典
#     """
#     return stock_api.get_company_overview(
#         instrument_id,
#         include_profile_snapshot=include_profile_snapshot,
#         include_industry_snapshot=include_industry_snapshot,
#         include_financial_snapshot=include_financial_snapshot,
#     )


# [后端404: 数据不存在，暂不暴露]
# @mcp.tool()
# @safe_tool
# def get_company_profile(instrument_id: str, include_snapshot: bool = True) -> Dict[str, Any]:
#     """
#     获取公司档案数据，包含公司基本信息、主营业务、经营范围等
# 
#     参数:
#     - instrument_id: 交易品种ID，例如 "600519.SH"
#     - include_snapshot: 是否包含详情快照，默认True
# 
#     返回:
#     - 包含公司档案数据的字典
#     """
#     return stock_api.get_company_profile(instrument_id, include_snapshot=include_snapshot)


@mcp.tool()
@safe_tool
def get_company_industry(
    stock_code: Optional[str] = None,
    instrument_id: Optional[str] = None,
    include_snapshot: bool = True,
) -> Dict[str, Any]:
    """
    获取公司行业归属数据，包含申万行业分类等

    参数:
    - stock_code: 6位股票代码，例如 "688403"（与 instrument_id 二选一）
    - instrument_id: 交易品种ID，例如 "688403.SH"（与 stock_code 二选一）
    - include_snapshot: 是否包含标准化归属详情，默认True

    返回:
    - 包含行业归属数据的字典
    """
    iid = _resolve_instrument_id(stock_code, instrument_id)
    return stock_api.get_company_industry(iid, include_snapshot=include_snapshot)


# [后端404: 数据不存在，暂不暴露]
# @mcp.tool()
# @safe_tool
# def get_financial_indicators(instrument_id: str, include_snapshot: bool = True) -> Dict[str, Any]:
#     """
#     获取公司财务指标摘要，包含核心财务指标数据
# 
#     参数:
#     - instrument_id: 交易品种ID，例如 "600519.SH"
#     - include_snapshot: 是否包含详情快照，默认True
# 
#     返回:
#     - 包含财务指标数据的字典
#     """
#     return stock_api.get_financial_indicators(instrument_id, include_snapshot=include_snapshot)


@mcp.tool()
@safe_tool
def get_financial_statements(
    stock_code: Optional[str] = None,
    instrument_id: Optional[str] = None,
    report_period: Optional[str] = None,
    include_statements: Optional[bool] = None,
    fields: Optional[str] = None,
    summary_only: bool = True,
) -> Dict[str, Any]:
    """
    获取公司财务报表数据，包含资产负债表、利润表、现金流量表等

    参数:
    - stock_code: 6位股票代码，例如 "600519"（与 instrument_id 二选一）
    - instrument_id: 交易品种ID，例如 "600519.SH"（与 stock_code 二选一）
    - report_period: 报告期，格式 YYYY-MM-DD
    - include_statements: 是否包含报表详情
    - fields: 逗号分隔的字段投影，如 "revenue,net_income,roe"；指定后只返回这些科目
    - summary_only: 是否只返回摘要（默认True），可把约190KB的响应压到约5KB

    返回:
    - 包含财务报表数据的字典；裁剪时带 _meta 说明被省略的字段

    说明:
    - 裁剪只影响返回体积，不改动任何数值；需要完整 facts / indicators.details
      明细时传 summary_only=false
    """
    iid = _resolve_instrument_id(stock_code, instrument_id)
    data = stock_api.get_financial_statements(
        iid, include_statements=include_statements, report_period=report_period
    )
    return _compact_financial(data, fields=fields, summary_only=summary_only)


# [后端已修复: 需 period_window=latest 参数，响应约60秒，已设120秒超时]
@mcp.tool()
@safe_tool
def get_financial_statements_history(
    stock_code: Optional[str] = None,
    instrument_id: Optional[str] = None,
    period_window: str = "latest",
    rolling_quarters: int = 12,
    include_statements: bool = False,
    fields: Optional[str] = None,
    summary_only: bool = False,
) -> Dict[str, Any]:
    """
    获取公司财务报表历史数据，支持多报告期对比

    参数:
    - stock_code: 6位股票代码，例如 "600519"（与 instrument_id 二选一）
    - instrument_id: 交易品种ID，例如 "600519.SH"（与 stock_code 二选一）
    - period_window: 报告期窗口模式，目前后端支持 "latest"（默认）
    - rolling_quarters: 最近报告期数量，范围1-40，默认12
    - include_statements: 是否包含原始报表详情，默认False
      True会拉取完整报表详情（响应更慢），按需开启
    - fields: 逗号分隔的字段投影，逐期只保留指定科目
    - summary_only: 是否只保留摘要字段，默认False（保持原有完整返回）

    返回:
    - 包含多报告期财务数据的字典，字段包括 revenue/net_income/total_assets 等

    说明:
    - 该接口后端响应较慢（约60秒），请耐心等待
    - include_statements=False 为轻量模式，仅返回汇总字段
    """
    iid = _resolve_instrument_id(stock_code, instrument_id)
    data = stock_api.get_financial_statements_history(
        iid,
        period_window=period_window,
        rolling_quarters=rolling_quarters,
        include_statements=include_statements,
    )
    return _compact_financial(data, fields=fields, summary_only=summary_only)


# [后端已修复: 股东快照数据已可用，600186.SH/600519.SH/600030.SH 验证通过]
@mcp.tool()
@safe_tool
def get_shareholders(
    stock_code: Optional[str] = None,
    instrument_id: Optional[str] = None,
    include_snapshot: bool = True,
) -> Dict[str, Any]:
    """
    获取公司股东信息，包含十大股东、股东变化等

    参数:
    - stock_code: 6位股票代码，例如 "600186"（与 instrument_id 二选一）
    - instrument_id: 交易品种ID，例如 "600186.SH"（与 stock_code 二选一）
    - include_snapshot: 是否包含详情快照，默认True

    返回:
    - 包含股东信息的字典，字段包括 holder_count/top_holders_count/control_owner_name 等
    """
    iid = _resolve_instrument_id(stock_code, instrument_id)
    return stock_api.get_shareholders(iid, include_snapshot=include_snapshot)


# [后端已修复: 200 OK，估值历史时间序列可用，响应约30秒]
@mcp.tool()
@safe_tool
def get_valuation_history(
    stock_code: Optional[str] = None,
    instrument_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 120,
    include_details: bool = True,
) -> Dict[str, Any]:
    """
    获取公司估值历史数据，包含PE/PB/PS等估值指标的时间序列

    参数:
    - stock_code: 6位股票代码，例如 "600519"（与 instrument_id 二选一）
    - instrument_id: 交易品种ID，例如 "600519.SH"（与 stock_code 二选一）
    - start_date: 开始日期，格式 YYYY-MM-DD（可选）
    - end_date: 结束日期，格式 YYYY-MM-DD（可选）
    - limit: 返回数据点数量，默认120
    - include_details: 是否包含详情，默认True

    返回:
    - 包含估值历史时间序列的字典，字段包括 pe_ratio/pb_ratio/ps_ratio/close_price 等

    说明:
    - 该接口后端响应较慢（约30秒），请耐心等待
    - 返回的 items 为逐日估值数据点列表
    """
    iid = _resolve_instrument_id(stock_code, instrument_id)
    return stock_api.get_valuation_history(
        iid, start_date=start_date, end_date=end_date,
        limit=limit, include_details=include_details,
    )


# [服务端Beta: 支持多窗口(60/120/252天)和多基准族，与本地回归Beta互补]
@mcp.tool()
@safe_tool
def get_server_beta(
    stock_code: Optional[str] = None,
    instrument_id: Optional[str] = None,
    benchmark_family: Optional[str] = None,
    benchmark_instrument_id: Optional[str] = None,
    window_days: Optional[int] = None,
    as_of_date: Optional[str] = None,
    include_details: bool = True,
) -> Dict[str, Any]:
    """
    获取服务端计算的Beta值，支持多窗口和多基准族

    与本地 get_regression_beta 不同，本工具调用后端服务，一次性返回
    60/120/252天多窗口Beta，并支持按市场默认/板块/行业等基准族切换。

    参数:
    - stock_code: 6位股票代码，例如 "600519"（与 instrument_id 二选一）
    - instrument_id: 交易品种ID，例如 "600519.SH"（与 stock_code 二选一）
    - benchmark_family: 基准族，可选:
        market_default(市场默认)、market_broad(宽基)、board(板块)、
        industry_sw_l2(申万二级行业)、custom(自定义)
    - benchmark_instrument_id: 显式基准标的ID，仅在 benchmark_family=custom 时生效
    - window_days: Beta窗口天数；为空时返回默认的60/120/252三个窗口
    - as_of_date: 计算截止日期，格式 YYYY-MM-DD（可选）
    - include_details: 是否包含计算诊断，默认True

    返回:
    - 包含Beta数据的字典，windows 字段为各窗口的 beta/alpha/r_squared 等
    """
    iid = _resolve_instrument_id(stock_code, instrument_id)
    return stock_api.get_server_beta(
        iid,
        benchmark_family=benchmark_family,
        benchmark_instrument_id=benchmark_instrument_id,
        window_days=window_days,
        as_of_date=as_of_date,
        include_details=include_details,
    )


# [估值分位数: 衡量当前估值在历史区间中的相对位置]
@mcp.tool()
@safe_tool
def get_valuation_percentile(
    stock_code: Optional[str] = None,
    instrument_id: Optional[str] = None,
    as_of_date: Optional[str] = None,
    quarters: int = 12,
    metrics: Optional[str] = None,
    min_points: int = 60,
    negative_policy: str = "flag",
    include_series: bool = False,
) -> Dict[str, Any]:
    """
    获取公司估值分位数，衡量当前估值在历史区间中的相对位置

    参数:
    - stock_code: 6位股票代码，例如 "600519"（与 instrument_id 二选一）
    - instrument_id: 交易品种ID，例如 "600519.SH"（与 stock_code 二选一）
    - as_of_date: 估值日期，默认使用最新可得日，格式 YYYY-MM-DD（可选）
    - quarters: 历史窗口季度数，默认12
    - metrics: 逗号分隔的估值指标口径，默认 "pe_ttm,pb_mrq,ps_ttm"
    - min_points: 最小有效样本数，默认60
    - negative_policy: 负值估值处理策略:
        flag(标记，默认)、include(包含)、exclude(排除)
    - include_series: 是否返回样本序列，默认False

    返回:
    - 包含估值分位数的字典，metrics 字段含各指标的
      current_value/percentile_rank/sample_count 等
    """
    iid = _resolve_instrument_id(stock_code, instrument_id)
    return stock_api.get_valuation_percentile(
        iid,
        as_of_date=as_of_date,
        quarters=quarters,
        metrics=metrics,
        min_points=min_points,
        negative_policy=negative_policy,
        include_series=include_series,
    )


# [后端已修复: 200 OK，已恢复]
@mcp.tool()
@safe_tool
def get_relative_valuation(
    stock_code: Optional[str] = None,
    instrument_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    获取公司相对估值数据，包含与同行业公司的估值对比

    参数:
    - stock_code: 6位股票代码，例如 "600519"（与 instrument_id 二选一）
    - instrument_id: 交易品种ID，例如 "600519.SH"（与 stock_code 二选一）

    返回:
    - 包含相对估值数据的字典
    """
    iid = _resolve_instrument_id(stock_code, instrument_id)
    return stock_api.get_relative_valuation(iid)


# [后端已修复: 200 OK，已恢复]
@mcp.tool()
@safe_tool
def get_dcf_valuation(
    stock_code: Optional[str] = None,
    instrument_id: Optional[str] = None,
    growth_rate: Optional[float] = None,
    discount_rate: Optional[float] = None,
    terminal_growth: Optional[float] = None,
    projection_years: Optional[int] = None,
) -> Dict[str, Any]:
    """
    获取公司DCF估值数据，支持自定义参数进行贴现现金流估值

    参数:
    - stock_code: 6位股票代码，例如 "600519"（与 instrument_id 二选一）
    - instrument_id: 交易品种ID，例如 "600519.SH"（与 stock_code 二选一）
    - growth_rate: 增长率
    - discount_rate: 折现率
    - terminal_growth: 永续增长率
    - projection_years: 预测年数

    返回:
    - 包含DCF估值数据的字典
    """
    iid = _resolve_instrument_id(stock_code, instrument_id)
    return stock_api.get_dcf_valuation(
        iid, growth_rate=growth_rate,
        discount_rate=discount_rate, terminal_growth=terminal_growth,
        projection_years=projection_years,
    )


# [后端503: 分析师预测模块禁用，暂不暴露]
# @mcp.tool()
# @safe_tool
# def get_analyst_coverage(instrument_id: str, include_details: bool = False) -> Dict[str, Any]:
#     """
#     获取公司分析师覆盖数据，包含分析师评级、目标价等
# 
#     参数:
#     - instrument_id: 交易品种ID，例如 "600519.SH"
#     - include_details: 是否包含详情，默认False
# 
#     返回:
#     - 包含分析师覆盖数据的字典
#     """
#     return stock_api.get_analyst_coverage(instrument_id, include_details=include_details)


# [后端503: 研报模块禁用，暂不暴露]
# @mcp.tool()
# @safe_tool
# def get_research_reports(
#     instrument_id: str,
#     start_date: Optional[str] = None,
#     end_date: Optional[str] = None,
#     limit: int = 20,
#     include_details: bool = False,
# ) -> Dict[str, Any]:
#     """
#     获取公司研究报告列表
# 
#     参数:
#     - instrument_id: 交易品种ID，例如 "600519.SH"
#     - start_date: 开始日期，格式 YYYY-MM-DD
#     - end_date: 结束日期，格式 YYYY-MM-DD
#     - limit: 返回数量限制，默认20
#     - include_details: 是否包含详情，默认False
# 
#     返回:
#     - 包含研究报告数据的字典
#     """
#     return stock_api.get_research_reports(
#         instrument_id, start_date=start_date, end_date=end_date,
#         limit=limit, include_details=include_details,
#     )


# [后端503: 情绪事件模块禁用，暂不暴露]
# @mcp.tool()
# @safe_tool
# def get_company_events(
#     instrument_id: str,
#     start_date: Optional[str] = None,
#     end_date: Optional[str] = None,
#     event_types: Optional[str] = None,
#     limit: int = 50,
#     include_details: bool = False,
# ) -> Dict[str, Any]:
#     """
#     获取公司情绪事件数据，包含重大事件、公告等
# 
#     参数:
#     - instrument_id: 交易品种ID，例如 "600519.SH"
#     - start_date: 开始日期，格式 YYYY-MM-DD
#     - end_date: 结束日期，格式 YYYY-MM-DD
#     - event_types: 事件类型
#     - limit: 返回数量限制，默认50
#     - include_details: 是否包含详情，默认False
# 
#     返回:
#     - 包含情绪事件数据的字典
#     """
#     return stock_api.get_company_events(
#         instrument_id, start_date=start_date, end_date=end_date,
#         event_types=event_types, limit=limit, include_details=include_details,
#     )


# [后端404: 数据不存在，暂不暴露]
# @mcp.tool()
# @safe_tool
# def get_company_risk(instrument_id: str, include_details: bool = False) -> Dict[str, Any]:
#     """
#     获取公司风险分析数据
# 
#     参数:
#     - instrument_id: 交易品种ID，例如 "600519.SH"
#     - include_details: 是否包含详情，默认False
# 
#     返回:
#     - 包含风险分析数据的字典
#     """
#     return stock_api.get_company_risk(instrument_id, include_details=include_details)


# ==================== 技术分析工具（服务端计算） ====================

@mcp.tool()
@safe_tool
def get_server_technical_summary(
    stock_code: Optional[str] = None,
    instrument_id: Optional[str] = None,
    adjust: Optional[str] = None,
) -> Dict[str, Any]:
    """
    获取服务端计算的技术分析摘要，包含趋势、动量、波动等综合评估

    参数:
    - stock_code: 6位股票代码，例如 "600519"（与 instrument_id 二选一）
    - instrument_id: 交易品种ID，例如 "600519.SH"（与 stock_code 二选一）
    - adjust: 复权类型，可选 "qfq"(前复权)/"hfq"(后复权)

    返回:
    - 包含技术分析摘要的字典
    """
    iid = _resolve_instrument_id(stock_code, instrument_id)
    return stock_api.get_technical_summary(iid, adjust=adjust)


@mcp.tool()
@safe_tool
def get_server_technical_indicators(
    stock_code: Optional[str] = None,
    instrument_id: Optional[str] = None,
    adjust: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 100,
) -> Dict[str, Any]:
    """
    获取服务端计算的技术指标数据，包含MACD、RSI、KDJ等

    参数:
    - stock_code: 6位股票代码，例如 "600519"（与 instrument_id 二选一）
    - instrument_id: 交易品种ID，例如 "600519.SH"（与 stock_code 二选一）
    - adjust: 复权类型，可选 "qfq"(前复权)/"hfq"(后复权)
    - start_date: 开始日期，格式 YYYY-MM-DD
    - end_date: 结束日期，格式 YYYY-MM-DD
    - limit: 返回数量限制，默认100

    返回:
    - 包含技术指标数据的字典
    """
    iid = _resolve_instrument_id(stock_code, instrument_id)
    return stock_api.get_technical_indicators(
        iid, adjust=adjust, start_date=start_date, end_date=end_date, limit=limit
    )


# ==================== 行业研究工具 ====================

@mcp.tool()
@safe_tool
def get_industry_taxonomy(
    taxonomy_system: Optional[str] = None,
    industry_level: Optional[int] = None,
    parent_code: Optional[str] = None,
    active_only: Optional[bool] = None,
    limit: int = 100,
    offset: int = 0,
) -> Dict[str, Any]:
    """
    获取行业分类体系数据，支持申万行业分类等

    参数:
    - taxonomy_system: 分类体系，例如 "sw2021"
    - industry_level: 行业层级（1-一级行业，2-二级行业，3-三级行业）
    - parent_code: 父级行业代码
    - active_only: 仅返回活跃行业，默认True
    - limit: 返回数量限制，默认100
    - offset: 偏移量，默认0

    返回:
    - 包含行业分类数据的字典
    """
    return stock_api.get_industry_taxonomy(
        taxonomy_system=taxonomy_system, industry_level=industry_level,
        parent_code=parent_code, active_only=active_only, limit=limit, offset=offset,
    )


@mcp.tool()
@safe_tool
def get_industry_component_sets(
    industry_code: Optional[str] = None,
    sw_index_code: Optional[str] = None,
    taxonomy_system: Optional[str] = None,
    include_symbols: Optional[bool] = None,
    limit: int = 100,
    offset: int = 0,
) -> Dict[str, Any]:
    """
    获取行业成分股数据，查询某行业下包含哪些股票

    参数:
    - industry_code: 行业代码
    - sw_index_code: 申万指数代码
    - taxonomy_system: 分类体系
    - include_symbols: 是否包含股票代码列表
    - limit: 返回数量限制，默认100
    - offset: 偏移量，默认0

    返回:
    - 包含行业成分股数据的字典
    """
    return stock_api.get_industry_component_sets(
        industry_code=industry_code, sw_index_code=sw_index_code,
        taxonomy_system=taxonomy_system, include_symbols=include_symbols,
        limit=limit, offset=offset,
    )


@mcp.tool()
@safe_tool
def get_industry_index_analysis(
    sw_index_code: Optional[str] = None,
    taxonomy_system: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    include_payload: Optional[bool] = None,
    limit: int = 100,
    offset: int = 0,
) -> Dict[str, Any]:
    """
    获取行业指数分析数据，包含行业指数的行情和指标

    参数:
    - sw_index_code: 申万指数代码
    - taxonomy_system: 分类体系
    - start_date: 开始日期，格式 YYYY-MM-DD
    - end_date: 结束日期，格式 YYYY-MM-DD
    - include_payload: 是否包含载荷数据
    - limit: 返回数量限制，默认100
    - offset: 偏移量，默认0

    返回:
    - 包含行业指数分析数据的字典
    """
    return stock_api.get_industry_index_analysis(
        sw_index_code=sw_index_code, taxonomy_system=taxonomy_system,
        start_date=start_date, end_date=end_date,
        include_payload=include_payload, limit=limit, offset=offset,
    )


# [后端404: 数据不存在，暂不暴露]
# @mcp.tool()
# @safe_tool
# def get_industry_index_analysis_latest(
#     sw_index_code: str,
#     taxonomy_system: Optional[str] = None,
#     include_payload: Optional[bool] = None,
# ) -> Dict[str, Any]:
#     """
#     获取行业指数最新分析数据
# 
#     参数:
#     - sw_index_code: 申万指数代码
#     - taxonomy_system: 分类体系
#     - include_payload: 是否包含载荷数据
# 
#     返回:
#     - 包含行业指数最新分析数据的字典
#     """
#     return stock_api.get_industry_index_analysis_latest(
#         sw_index_code, taxonomy_system=taxonomy_system, include_payload=include_payload,
#     )


# ==================== 期货数据工具 ====================


@mcp.tool()
@safe_tool
def get_futures_instruments(active_only: bool = True) -> Dict[str, Any]:
    """
    获取期货品种列表

    参数:
    - active_only: 仅返回活跃品种，默认True

    返回:
    - 期货品种列表，每个品种含 instrument_id/symbol/name/exchange/category/currency 等
    """
    return ensure_dict(stock_api.get_futures_instruments(active_only=active_only))


@mcp.tool()
@safe_tool
def get_futures_instrument_detail(instrument_id: str) -> Dict[str, Any]:
    """
    获取期货品种详情

    参数:
    - instrument_id: 期货品种ID，例如 "CNF.AG.SHFE"（上海白银）、"CNF.CU.SHFE"（上海铜）

    返回:
    - 期货品种详情，含合约规格、最小变动价位、交易时间等
    """
    return ensure_dict(stock_api.get_futures_instrument_detail(instrument_id))


@mcp.tool()
@safe_tool
def get_futures_contracts(
    instrument_id: Optional[str] = None,
    exchange: Optional[str] = None,
    contract_month: Optional[str] = None,
    active_only: bool = True,
) -> Dict[str, Any]:
    """
    获取期货合约列表

    参数:
    - instrument_id: 期货品种ID（可选），例如 "CNF.AG.SHFE"
    - exchange: 交易所（可选），如 SHFE/DCE/CZCE/INE/GFEX
    - contract_month: 合约月份（可选），格式 YYYYMM
    - active_only: 仅返回活跃合约，默认True

    返回:
    - 期货合约列表
    """
    return ensure_dict(
        stock_api.get_futures_contracts(
            instrument_id=instrument_id,
            exchange=exchange,
            contract_month=contract_month,
            active_only=active_only,
        )
    )


@mcp.tool()
@safe_tool
def get_futures_contract_prices(
    contract_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """
    获取期货合约价格序列

    参数:
    - contract_id: 合约ID，例如 "CNF.AG.SHFE.AG2506"
    - start_date: 开始日期，格式 YYYY-MM-DD（可选）
    - end_date: 结束日期，格式 YYYY-MM-DD（可选）
    - limit: 返回数据点数量限制

    返回:
    - 合约价格序列，含 open/high/low/close/volume/open_interest 等
    """
    return ensure_dict(
        stock_api.get_futures_contract_prices(
            contract_id, start_date=start_date, end_date=end_date, limit=limit
        )
    )


@mcp.tool()
@safe_tool
def get_futures_series(
    instrument_id: Optional[str] = None,
    series_type: Optional[str] = None,
    active_only: bool = True,
) -> Dict[str, Any]:
    """
    获取期货连续序列列表

    参数:
    - instrument_id: 期货品种ID（可选），例如 "CNF.AG.SHFE"
    - series_type: 序列类型（可选），如 main_continuous
    - active_only: 仅返回活跃序列，默认True

    返回:
    - 连续序列列表，含 series_id/symbol/source/series_type 等
    """
    return ensure_dict(
        stock_api.get_futures_series(
            instrument_id=instrument_id,
            series_type=series_type,
            active_only=active_only,
        )
    )


@mcp.tool()
@safe_tool
def get_futures_series_prices(
    series_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """
    获取期货连续序列价格

    参数:
    - series_id: 序列ID，例如 "CNF.AG.SHFE.main"
    - start_date: 开始日期，格式 YYYY-MM-DD（可选）
    - end_date: 结束日期，格式 YYYY-MM-DD（可选）
    - limit: 返回数据点数量限制

    返回:
    - 序列价格数据，含日期序列的 open/high/low/close/volume 等

    说明:
    - series_id 含点号（如 CNF.AG.SHFE.main），内部已处理URL编码
    - 该接口响应较慢（约30秒），请耐心等待
    - 建议提供日期范围避免拉取全量数据（约4MB/序列）
    """
    return ensure_dict(
        stock_api.get_futures_series_prices(
            series_id, start_date=start_date, end_date=end_date, limit=limit
        )
    )


@mcp.tool()
@safe_tool
def get_futures_series_mapping(
    series_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """
    获取期货连续序列主力映射

    参数:
    - series_id: 序列ID，例如 "CNF.AG.SHFE.main"
    - start_date: 开始日期，格式 YYYY-MM-DD（可选）
    - end_date: 结束日期，格式 YYYY-MM-DD（可选）
    - limit: 返回数据点数量限制

    返回:
    - 主力映射，记录每个交易日主力合约的切换历史
    """
    return ensure_dict(
        stock_api.get_futures_series_mapping(
            series_id, start_date=start_date, end_date=end_date, limit=limit
        )
    )


@mcp.tool()
@safe_tool
def get_futures_cycle_diagnostics(
    series_id: str,
    as_of_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    获取期货连续序列周期诊断

    参数:
    - series_id: 序列ID，例如 "CNF.AG.SHFE.main"
    - as_of_date: 诊断截止日期，格式 YYYY-MM-DD（可选）

    返回:
    - 周期诊断数据，含主力合约切换周期、移仓换月统计等
    """
    return ensure_dict(
        stock_api.get_futures_cycle_diagnostics(series_id, as_of_date=as_of_date)
    )


@mcp.tool()
@safe_tool
def get_futures_default_prices(
    instrument_id: str,
    series_type: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: Optional[int] = None,
    include_lineage: bool = False,
) -> Dict[str, Any]:
    """
    获取期货默认价格序列（按品种ID查询，后端自动选择主连序列）

    参数:
    - instrument_id: 期货品种ID，例如 "CNF.AG.SHFE"
    - series_type: 序列类型（可选），默认由后端选择主连
    - start_date: 开始日期，格式 YYYY-MM-DD（可选）
    - end_date: 结束日期，格式 YYYY-MM-DD（可选）
    - limit: 返回数据点数量限制
    - include_lineage: 是否包含数据来源溯源，默认False

    返回:
    - 价格序列
    """
    return ensure_dict(
        stock_api.get_futures_default_prices(
            instrument_id,
            series_type=series_type,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            include_lineage=include_lineage,
        )
    )


@mcp.tool()
@safe_tool
def get_futures_calendar(
    exchange: Optional[str] = None,
    instrument_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    trading_only: bool = False,
) -> Dict[str, Any]:
    """
    获取期货交易日历

    参数:
    - exchange: 交易所（可选），如 SHFE/DCE/CZCE/INE/GFEX
    - instrument_id: 期货品种ID（可选）
    - start_date: 开始日期，格式 YYYY-MM-DD（强烈建议填写）
    - end_date: 结束日期，格式 YYYY-MM-DD（强烈建议填写）
    - trading_only: 仅返回交易日，默认False

    返回:
    - 期货交易日历列表

    说明:
    - 不限定日期范围会拉取全量历史（数千条），后端响应慢易超时
    """
    return ensure_dict(
        stock_api.get_futures_calendar(
            exchange=exchange,
            instrument_id=instrument_id,
            start_date=start_date,
            end_date=end_date,
            trading_only=trading_only,
        )
    )


@mcp.tool()
@safe_tool
def get_futures_readiness(exchange: Optional[str] = None) -> Dict[str, Any]:
    """
    获取期货模块就绪状态

    参数:
    - exchange: 交易所（可选），用于过滤就绪状态

    返回:
    - 就绪状态，含 enabled_series_count/p0_ready_count/scope_selection 等
    """
    return ensure_dict(stock_api.get_futures_readiness(exchange=exchange))


@mcp.tool()
@safe_tool
def get_futures_dictionary() -> Dict[str, Any]:
    """
    获取期货字典（分类、字段说明等元数据）

    返回:
    - 字典数据，含 categories/fields 等
    """
    return ensure_dict(stock_api.get_futures_dictionary())


# ==================== 技术分析工具（本地计算） ====================

@mcp.tool()
@safe_tool
def get_technical_analysis(
    stock_code: str,
    start_date: str,
    end_date: str,
    ma_periods: List[int] = None,
    calculate_macd: bool = True,
    calculate_rsi: bool = True,
    rsi_period: int = 14,
    calculate_bollinger: bool = True,
    bollinger_period: int = 20,
    bollinger_std: float = 2.0,
    calculate_kdj: bool = True,
    kdj_n: int = 9,
    kdj_m1: int = 3,
    kdj_m2: int = 3,
    calculate_atr: bool = True,
    atr_period: int = 14,
) -> Dict[str, Any]:
    """
    获取股票技术分析数据（本地计算），支持MA、MACD、RSI、布林带、KDJ、ATR等指标

    参数:
    - stock_code: 6位股票代码，例如 "601126" 或 "300708"
    - start_date: 开始日期，格式 YYYY-MM-DD
    - end_date: 结束日期，格式 YYYY-MM-DD
    - ma_periods: 移动平均线周期列表，默认 [20, 50, 200]
    - calculate_macd: 是否计算MACD指标，默认 True
    - calculate_rsi: 是否计算RSI指标，默认 True
    - rsi_period: RSI周期，默认 14
    - calculate_bollinger: 是否计算布林带，默认 True
    - bollinger_period: 布林带周期，默认 20
    - bollinger_std: 布林带标准差倍数，默认 2.0
    - calculate_kdj: 是否计算KDJ指标，默认 True
    - kdj_n: KDJ的RSV周期，默认 9
    - kdj_m1: KDJ的K值平滑周期，默认 3
    - kdj_m2: KDJ的D值平滑周期，默认 3
    - calculate_atr: 是否计算ATR指标，默认 True
    - atr_period: ATR周期，默认 14

    返回:
    - 包含技术分析数据的字典
    """
    validate_stock_code(stock_code)
    validate_date(start_date, "开始日期")
    validate_date(end_date, "结束日期")

    if ma_periods is None:
        ma_periods = [20, 50, 200]

    # 计算需要提前获取数据的最大周期
    max_period = 0
    if ma_periods:
        max_period = max(max_period, max(ma_periods))
    if calculate_macd:
        max_period = max(max_period, 26)
    if calculate_rsi:
        max_period = max(max_period, rsi_period)
    if calculate_bollinger:
        max_period = max(max_period, bollinger_period)
    if calculate_kdj:
        max_period = max(max_period, kdj_n, kdj_m1, kdj_m2)
    if calculate_atr:
        max_period = max(max_period, atr_period)

    def _calc(analyzer, **kw):
        if ma_periods:
            analyzer.calculate_ma(ma_periods)
        if calculate_macd:
            analyzer.calculate_macd()
        if calculate_rsi:
            analyzer.calculate_rsi(rsi_period)
        if calculate_bollinger:
            analyzer.calculate_bollinger_bands(bollinger_period, bollinger_std)
        if calculate_kdj:
            analyzer.calculate_kdj(kdj_n, kdj_m1, kdj_m2)
        if calculate_atr:
            analyzer.calculate_atr(atr_period)

    return compute_local_technical(stock_api, stock_code, start_date, end_date, _calc, max_period)


@mcp.tool()
@safe_tool
def get_ma_analysis(
    stock_code: str,
    start_date: str,
    end_date: str,
    periods: List[int] = None,
) -> Dict[str, Any]:
    """
    获取移动平均线分析（本地计算）

    参数:
    - stock_code: 6位股票代码
    - start_date: 开始日期，格式 YYYY-MM-DD
    - end_date: 结束日期，格式 YYYY-MM-DD
    - periods: 移动平均线周期列表，默认 [20, 50, 200]

    返回:
    - 包含移动平均线数据的字典
    """
    validate_stock_code(stock_code)
    validate_date(start_date, "开始日期")
    validate_date(end_date, "结束日期")

    if periods is None:
        periods = [20, 50, 200]
    max_period = max(periods) if periods else 20
    return compute_local_technical(
        stock_api, stock_code, start_date, end_date,
        lambda a, **kw: a.calculate_ma(periods), max_period,
    )


@mcp.tool()
@safe_tool
def get_macd_analysis(
    stock_code: str,
    start_date: str,
    end_date: str,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> Dict[str, Any]:
    """
    获取MACD分析（本地计算）

    参数:
    - stock_code: 6位股票代码
    - start_date: 开始日期，格式 YYYY-MM-DD
    - end_date: 结束日期，格式 YYYY-MM-DD
    - fast_period: 快速EMA周期
    - slow_period: 慢速EMA周期
    - signal_period: 信号EMA周期

    返回:
    - 包含MACD数据的字典
    """
    validate_stock_code(stock_code)
    validate_date(start_date, "开始日期")
    validate_date(end_date, "结束日期")

    max_period = max(fast_period, slow_period, signal_period)
    return compute_local_technical(
        stock_api, stock_code, start_date, end_date,
        lambda a, **kw: a.calculate_macd(fast_period, slow_period, signal_period), max_period,
    )


@mcp.tool()
@safe_tool
def get_kdj_analysis(
    stock_code: str,
    start_date: str,
    end_date: str,
    n: int = 9,
    m1: int = 3,
    m2: int = 3,
) -> Dict[str, Any]:
    """
    获取KDJ分析（本地计算）

    参数:
    - stock_code: 6位股票代码
    - start_date: 开始日期，格式 YYYY-MM-DD
    - end_date: 结束日期，格式 YYYY-MM-DD
    - n: RSV周期
    - m1: K值平滑周期
    - m2: D值平滑周期

    返回:
    - 包含KDJ数据的字典
    """
    validate_stock_code(stock_code)
    validate_date(start_date, "开始日期")
    validate_date(end_date, "结束日期")

    max_period = max(n, m1, m2)
    return compute_local_technical(
        stock_api, stock_code, start_date, end_date,
        lambda a, **kw: a.calculate_kdj(n, m1, m2), max_period,
    )


@mcp.tool()
@safe_tool
def get_regression_beta(
    stock_code: str,
    start_date: str,
    end_date: str,
    benchmark_code: str = "000300",
    period: int = 60,
) -> Dict[str, Any]:
    """
    计算回归Beta（本地计算）

    通过个股与基准指数的日收益率线性回归计算Beta系数。
    Beta > 1 表示个股波动大于市场，Beta < 1 表示个股波动小于市场。

    参数:
    - stock_code: 6位股票代码，例如 "600519"
    - start_date: 开始日期，格式 YYYY-MM-DD
    - end_date: 结束日期，格式 YYYY-MM-DD
    - benchmark_code: 基准指数代码，默认 "000300"（沪深300），
      也可选 "000016"（上证50）、"000905"（中证500）
    - period: 回归窗口天数，默认60

    返回:
    - 包含Beta系数、Alpha、R-squared等回归统计量的字典
    """
    validate_stock_code(stock_code)
    validate_date(start_date, "开始日期")
    validate_date(end_date, "结束日期")

    # 提前获取更多数据以确保有足够的交易日
    user_start = pd.to_datetime(start_date)
    adjusted_start = (user_start - pd.Timedelta(days=int(period * 3))).strftime("%Y-%m-%d")

    # 获取个股日行情
    stock_df = stock_api.get_daily_quotes_df(stock_code, adjusted_start, end_date)
    if stock_df.empty:
        return {"error": f"未获取到股票 {stock_code} 的数据"}

    # 获取基准指数日行情（基准代码作为指数查询，使用is_index=True）
    bench_df = stock_api.get_daily_quotes_df(benchmark_code, adjusted_start, end_date, is_index=True)
    if bench_df.empty:
        return {"error": f"未获取到基准 {benchmark_code} 的数据"}

    # 计算日收益率
    stock_df["return"] = stock_df["close"].pct_change()
    bench_df["return"] = bench_df["close"].pct_change()

    # 合并数据，按日期对齐
    merged = pd.merge(
        stock_df[["return"]].rename(columns={"return": "stock_return"}),
        bench_df[["return"]].rename(columns={"return": "bench_return"}),
        left_index=True,
        right_index=True,
        how="inner",
    ).dropna()

    if len(merged) < 20:
        return {"error": "有效数据不足，至少需要20个交易日的数据"}

    # 过滤到用户请求的日期范围，取最近period天
    merged = merged[merged.index >= user_start]
    if len(merged) > period:
        merged = merged.tail(period)

    if len(merged) < 20:
        return {"error": f"在指定日期范围内有效数据不足（{len(merged)}天），至少需要20个交易日"}

    # 线性回归：stock_return = alpha + beta * bench_return
    x = merged["bench_return"].values
    y = merged["stock_return"].values

    # 使用最小二乘法计算
    n = len(x)
    sum_x = np.sum(x)
    sum_y = np.sum(y)
    sum_xy = np.sum(x * y)
    sum_x2 = np.sum(x ** 2)

    denominator = sum_x2 - sum_x ** 2 / n
    if abs(denominator) < 1e-12:
        return {"error": "基准收益率方差为零，无法计算Beta"}

    beta = (sum_xy - sum_x * sum_y / n) / denominator
    alpha = (sum_y - beta * sum_x) / n

    # R-squared
    y_pred = alpha + beta * x
    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0

    # 标准误差
    residuals = y - y_pred
    mse = np.sum(residuals ** 2) / (n - 2) if n > 2 else 0
    se_beta = np.sqrt(mse / denominator) if denominator > 0 else 0

    # 个股和基准的年化波动率
    stock_vol = merged["stock_return"].std() * np.sqrt(252)
    bench_vol = merged["bench_return"].std() * np.sqrt(252)

    # 相关系数
    correlation = merged["stock_return"].corr(merged["bench_return"])

    return {
        "stock_code": stock_code,
        "benchmark_code": benchmark_code,
        "start_date": merged.index[0].strftime("%Y-%m-%d"),
        "end_date": merged.index[-1].strftime("%Y-%m-%d"),
        "data_points": n,
        "period": period,
        "beta": round(float(beta), 4),
        "alpha": round(float(alpha), 6),
        "r_squared": round(float(r_squared), 4),
        "beta_se": round(float(se_beta), 4),
        "correlation": round(float(correlation), 4),
        "stock_annual_volatility": round(float(stock_vol), 4),
        "benchmark_annual_volatility": round(float(bench_vol), 4),
        "interpretation": (
            f"Beta={beta:.2f}，"
            + ("个股波动大于市场" if beta > 1 else "个股波动小于市场" if beta < 1 else "个股波动与市场一致")
            + f"，与基准相关性={correlation:.2f}"
        ),
    }


# ==================== 聚合工具（对外暴露） ====================
# 恢复 mcp.tool 注册
mcp.tool = _original_mcp_tool


@mcp.tool()
@safe_tool
def query_stock_quote(
    action: Literal["latest", "daily"],
    stock_code: Optional[str] = None,
    instrument_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    adjust: Optional[str] = None,
    include_suspended: Optional[bool] = None,
    min_quality_score: Optional[float] = None,
    is_complete: Optional[bool] = None,
    min_volume: Optional[float] = None,
) -> Dict[str, Any]:
    """
    股票行情数据查询，支持实时行情、日K线等

    参数:
    - action: 查询动作，可选:
        "latest" - 最新行情（stock_code支持6位代码或列表如"600519,000001"）
        "daily" - 日K线数据（需提供start_date/end_date）
    - stock_code: 6位股票代码，如 "600519" 或逗号分隔的多个代码
    - instrument_id: 带后缀ID如 "600519.SH"（与stock_code二选一）
    - start_date: 开始日期，格式 YYYY-MM-DD
    - end_date: 结束日期，格式 YYYY-MM-DD
    - adjust: 复权类型，"qfq"前复权/"hfq"后复权
    - include_suspended: 是否包含停牌日，仅 daily 有效（透传后端；实测未生效）
    - min_quality_score: 最低质量分，仅 daily 有效（透传后端；实测未生效）
    - is_complete: 是否只取完整交易日，仅 daily 有效；传 true 可剔除停牌日（实测生效）
    - min_volume: 最小成交量，仅 daily 有效；传 1 可剔除零成交的停牌日（实测生效）

    返回:
    - 行情数据字典

    口径提示（重要）:
    - adjust=hfq 时 open/high/low/close/volume 为后复权，pre_close/change 为未复权，
      amount 为真实元；每行附带的 derived 块给出 close_raw/volume_raw/avg_price_raw，
      以及 pct_change_decimal（无量纲比例）。请用它计算收益率与成交均价。
    - pct_change 的单位是百分数（0.0689 = 0.0689%），顶层 units 已显式声明。
    - latest 的 time 只到交易日、不含时辰，返回的是快照而非逐笔实时行情，
      可用顶层 freshness.staleness_trading_days 判断滞后几个交易日。

    停牌日（实测 000002.SZ / 2016-06-01~07-31）:
    - 停牌日不缺失，而是以零成交量行存在：volume=0、OHLC 全等前收、
      tradestatus=0、is_complete=false、quality_score=0.4（41 行中占 21 行）。
    - 做横截面/量价筛选时，建议传 is_complete=true 或 min_volume=1 剔除停牌日。
    """
    if action == "latest":
        # 解析 stock_code（支持逗号分隔的多个代码）
        if instrument_id:
            return get_latest_stock_data(instrument_id=instrument_id)
        if stock_code:
            if "," in stock_code:
                return get_latest_stock_data(stock_code=stock_code.split(","))
            return get_latest_stock_data(stock_code=stock_code)
        return {"error": "请提供 stock_code 或 instrument_id"}
    elif action == "daily":
        if not start_date or not end_date:
            return {"error": "日K线查询需要 start_date 和 end_date 参数"}
        return get_daily_stock_data(
            stock_code=stock_code, instrument_id=instrument_id,
            start_date=start_date, end_date=end_date, adjust=adjust,
            include_suspended=include_suspended,
            min_quality_score=min_quality_score,
            is_complete=is_complete,
            min_volume=min_volume,
        )
    else:
        return {"error": f"未知action '{action}'，可选: latest, daily"}


@mcp.tool()
@safe_tool
def query_stock_fundamental(
    action: Literal["financial", "financial_history", "shareholders", "industry"],
    stock_code: Optional[str] = None,
    instrument_id: Optional[str] = None,
    include_snapshot: bool = True,
    include_statements: bool = False,
    report_period: Optional[str] = None,
    period_window: str = "latest",
    rolling_quarters: int = 12,
    fields: Optional[str] = None,
    summary_only: bool = True,
) -> Dict[str, Any]:
    """
    股票基本面数据查询，包括财务报表、股东、行业归属等

    参数:
    - action: 查询动作，可选:
        "financial" - 财务报表（默认摘要模式，约5KB）
        "financial_history" - 多报告期财务历史
        "shareholders" - 股东信息
        "industry" - 行业归属
    - stock_code: 6位股票代码（与instrument_id二选一）
    - instrument_id: 带后缀ID如 "600519.SH"
    - include_snapshot: 是否含详情快照，仅对 shareholders / industry 生效；
      financial 接口后端没有该参数，传了也不会生效
    - include_statements: 是否含报表详情，默认False
    - report_period: 报告期，格式 YYYY-MM-DD
    - period_window: 报告期窗口模式，默认"latest"
    - rolling_quarters: 最近报告期数量，默认12
    - fields: 字段投影，逗号分隔，如 "revenue,net_income,roe"；
      指定后只返回这些科目 + 报告期等标识字段
    - summary_only: financial 动作是否走摘要模式，默认True
      （完整响应约190KB，摘要约5KB；明细请传 false）

    返回:
    - 基本面数据字典

    单位提示:
    - indicators 中的利润率/ROE 为小数（0.8976 = 89.76%），
      而 query_financial_pit 的 cross_section 同名字段为百分数（89.76 = 89.76%），
      跨接口拼接前必须换算
    """
    if action == "financial":
        return get_financial_statements(
            stock_code=stock_code, instrument_id=instrument_id,
            report_period=report_period, include_statements=include_statements,
            fields=fields, summary_only=summary_only,
        )
    elif action == "financial_history":
        return get_financial_statements_history(
            stock_code=stock_code, instrument_id=instrument_id,
            period_window=period_window, rolling_quarters=rolling_quarters,
            include_statements=include_statements,
            fields=fields, summary_only=False,
        )
    elif action == "shareholders":
        return get_shareholders(
            stock_code=stock_code, instrument_id=instrument_id,
            include_snapshot=include_snapshot,
        )
    elif action == "industry":
        return get_company_industry(
            stock_code=stock_code, instrument_id=instrument_id,
            include_snapshot=include_snapshot,
        )
    else:
        return {"error": f"未知action '{action}'，可选: financial, financial_history, shareholders, industry"}


@mcp.tool()
@safe_tool
def query_stock_valuation(
    action: Literal["relative", "dcf", "history", "percentile"],
    stock_code: Optional[str] = None,
    instrument_id: Optional[str] = None,
    quarters: int = 12,
    limit: int = 120,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    股票估值数据查询，包括相对估值、DCF估值、估值历史、估值分位数等

    参数:
    - action: 查询动作，可选:
        "relative" - 相对估值
        "dcf" - DCF估值
        "history" - 估值历史时间序列
        "percentile" - 估值分位数
    - stock_code: 6位股票代码（与instrument_id二选一）
    - instrument_id: 带后缀ID如 "600519.SH"
    - quarters: 历史窗口季度数，默认12
    - limit: 返回数据点数，默认120
    - start_date: 开始日期（可选）
    - end_date: 结束日期（可选）

    返回:
    - 估值数据字典
    """
    if action == "relative":
        return get_relative_valuation(stock_code=stock_code, instrument_id=instrument_id)
    elif action == "dcf":
        return get_dcf_valuation(stock_code=stock_code, instrument_id=instrument_id)
    elif action == "history":
        return get_valuation_history(
            stock_code=stock_code, instrument_id=instrument_id,
            start_date=start_date, end_date=end_date, limit=limit,
        )
    elif action == "percentile":
        return get_valuation_percentile(
            stock_code=stock_code, instrument_id=instrument_id, quarters=quarters,
        )
    else:
        return {"error": f"未知action '{action}'，可选: relative, dcf, history, percentile"}


@mcp.tool()
@safe_tool
def query_stock_beta(
    action: Literal["server", "regression"],
    stock_code: Optional[str] = None,
    instrument_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    benchmark_code: str = "000300",
    period: int = 60,
    benchmark_family: Optional[str] = None,
    window_days: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Beta系数查询，支持服务端Beta和本地回归Beta

    参数:
    - action: 查询动作，可选:
        "server" - 服务端Beta（多窗口多基准，一次返回60/120/252天）
        "regression" - 本地回归Beta（可自定义基准和窗口）
    - stock_code: 6位股票代码（与instrument_id二选一）
    - instrument_id: 带后缀ID如 "600519.SH"
    - start_date: 开始日期，格式 YYYY-MM-DD
    - end_date: 结束日期，格式 YYYY-MM-DD
    - benchmark_code: 基准指数代码（本地Beta用），默认"000300"沪深300
    - period: 回归窗口天数（本地Beta用），默认60
    - benchmark_family: 基准族（服务端Beta用），如 market_default
    - window_days: 窗口天数（服务端Beta用），空则返回60/120/252

    返回:
    - Beta数据字典
    """
    if action == "server":
        return get_server_beta(
            stock_code=stock_code, instrument_id=instrument_id,
            benchmark_family=benchmark_family, window_days=window_days,
        )
    elif action == "regression":
        if not stock_code or not start_date or not end_date:
            return {"error": "本地回归Beta需要 stock_code, start_date, end_date 参数"}
        return get_regression_beta(
            stock_code=stock_code, start_date=start_date, end_date=end_date,
            benchmark_code=benchmark_code, period=period,
        )
    else:
        return {"error": f"未知action '{action}'，可选: server, regression"}


@mcp.tool()
@safe_tool
def query_stock_technical(
    action: Literal["summary", "indicators", "full", "ma", "macd", "kdj"],
    stock_code: Optional[str] = None,
    instrument_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 100,
    adjust: Optional[str] = None,
) -> Dict[str, Any]:
    """
    技术分析数据查询，包括服务端技术摘要/指标和本地MA/MACD/KDJ等

    参数:
    - action: 查询动作，可选:
        "summary" - 服务端技术分析摘要
        "indicators" - 服务端技术指标数据
        "full" - 本地完整技术分析（需start_date/end_date）
        "ma" - 本地MA分析
        "macd" - 本地MACD分析
        "kdj" - 本地KDJ分析
    - stock_code: 6位股票代码（与instrument_id二选一）
    - instrument_id: 带后缀ID如 "600519.SH"
    - start_date: 开始日期，格式 YYYY-MM-DD
    - end_date: 结束日期，格式 YYYY-MM-DD
    - limit: 返回数量限制，默认100
    - adjust: 复权类型

    返回:
    - 技术分析数据字典
    """
    if action == "summary":
        return get_server_technical_summary(
            stock_code=stock_code, instrument_id=instrument_id, adjust=adjust,
        )
    elif action == "indicators":
        return get_server_technical_indicators(
            stock_code=stock_code, instrument_id=instrument_id,
            adjust=adjust, limit=limit,
        )
    elif action in ("full", "ma", "macd", "kdj"):
        if not stock_code or not start_date or not end_date:
            return {"error": f"本地{action}分析需要 stock_code, start_date, end_date 参数"}
        func_map = {"full": get_technical_analysis, "ma": get_ma_analysis,
                    "macd": get_macd_analysis, "kdj": get_kdj_analysis}
        return func_map[action](stock_code=stock_code, start_date=start_date, end_date=end_date)
    else:
        return {"error": f"未知action '{action}'，可选: summary, indicators, full, ma, macd, kdj"}


@mcp.tool()
@safe_tool
def query_trading_calendar(
    action: Literal["calendar", "next_day", "previous_day", "instrument", "stock_info"],
    exchange: str = "SSE",
    date: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    stock_code: Optional[str] = None,
    instrument_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    交易日历与品种信息查询

    参数:
    - action: 查询动作，可选:
        "calendar" - 交易日历（需start_date/end_date）
        "next_day" - 下一交易日
        "previous_day" - 上一交易日
        "instrument" - 交易品种信息
        "stock_info" - 股票基本信息（6位代码）
    - exchange: 交易所，默认"SSE"
    - date: 参考日期，格式 YYYY-MM-DD
    - start_date: 开始日期
    - end_date: 结束日期
    - stock_code: 6位股票代码
    - instrument_id: 带后缀ID

    返回:
    - 日历或品种信息字典
    """
    if action == "calendar":
        if not start_date or not end_date:
            return {"error": "日历查询需要 start_date 和 end_date 参数"}
        return get_trading_calendar_data(exchange=exchange, start_date=start_date, end_date=end_date)
    elif action == "next_day":
        if not date:
            return {"error": "需要 date 参数"}
        return get_next_trading_day(exchange=exchange, date=date)
    elif action == "previous_day":
        if not date:
            return {"error": "需要 date 参数"}
        return get_previous_trading_day(exchange=exchange, date=date)
    elif action == "instrument":
        return get_instrument_by_id(stock_code=stock_code, instrument_id=instrument_id)
    elif action == "stock_info":
        if not stock_code:
            return {"error": "需要 stock_code 参数"}
        return get_stock_info(stock_code=stock_code)
    else:
        return {"error": f"未知action '{action}'，可选: calendar, next_day, previous_day, instrument, stock_info"}


@mcp.tool()
@safe_tool
def query_industry_data(
    action: Literal["taxonomy", "components", "index_analysis", "as_of", "company_as_of"],
    taxonomy_system: str = "sw2021",
    industry_level: Optional[str] = None,
    sw_index_code: Optional[str] = None,
    as_of_date: Optional[str] = None,
    exchange: Optional[str] = None,
    as_of_taxonomy_system: Optional[str] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    stock_code: Optional[str] = None,
    instrument_id: Optional[str] = None,
    include_snapshot: bool = False,
) -> Dict[str, Any]:
    """
    行业研究数据查询，包括行业分类体系、成分股、指数分析、时点行业分类等

    参数:
    - action: 查询动作，可选:
        "taxonomy" - 行业分类体系
        "components" - 行业成分股（需sw_index_code）
        "index_analysis" - 行业指数分析（需sw_index_code）
        "as_of" - 批量时点行业分类（需as_of_date），用于历史时点行业中性化
        "company_as_of" - 单票时点行业归属（需stock_code/instrument_id + as_of_date）
    - taxonomy_system: 分类体系，默认"sw2021"（仅taxonomy动作用）
    - industry_level: 行业层级（可选，仅taxonomy动作用）
    - sw_index_code: 申万指数代码（可选，components/index_analysis用）
    - as_of_date: 时点日期（as_of/company_as_of用，支持"20260801"/"2026-08-01"自动适配）
    - exchange: 交易所过滤 SSE/SZSE/BSE，逗号分隔（仅as_of批量动作用）
    - as_of_taxonomy_system: 时点行业分类体系（as_of/company_as_of用，常用"sw"）
    - limit: 单页上限（仅as_of批量动作用）
    - offset: 分页偏移（仅as_of批量动作用）
    - stock_code: 6位股票代码，如"600519"（company_as_of用）
    - instrument_id: 交易品种ID，如"600519.SH"（company_as_of用；与stock_code二选一）
    - include_snapshot: 是否返回行业快照明细（company_as_of用，默认False）

    返回:
    - 行业数据字典

    注意:
    - as_of 为批量（不回填最新分类：当日无生效分类的股票不返回），
      company_as_of 为单票；两者做行业中性化都须严格按返回结果关联以避免未来函数
    - 两个接口的日期格式在后端不同（批量 YYYYMMDD / 单票 YYYY-MM-DD），
      本工具已自动适配，调用方无需关心
    - 单票返回的行业代码字段名为 official_industry_code，
      批量返回为 industry_code；单票生效区间为 effective_date/expiry_date，
      批量为 effective_from/effective_to
    """
    if action == "taxonomy":
        return get_industry_taxonomy(taxonomy_system=taxonomy_system, industry_level=industry_level)
    elif action == "components":
        if not sw_index_code:
            return {"error": "需要 sw_index_code 参数"}
        return get_industry_component_sets(sw_index_code=sw_index_code)
    elif action == "index_analysis":
        if not sw_index_code:
            return {"error": "需要 sw_index_code 参数"}
        return get_industry_index_analysis(sw_index_code=sw_index_code)
    elif action == "as_of":
        if not as_of_date:
            return {"error": "as_of 动作需要 as_of_date 参数（如 20260801）"}
        return stock_api.get_industries_as_of(
            as_of=_normalize_pit_date(as_of_date),
            taxonomy_system=as_of_taxonomy_system,
            exchange=exchange,
            limit=limit,
            offset=offset,
        )
    elif action == "company_as_of":
        if not as_of_date:
            return {"error": "company_as_of 动作需要 as_of_date 参数（如 20260801）"}
        try:
            resolved_id = _resolve_instrument_id(stock_code, instrument_id)
        except ValueError as e:
            return {"error": str(e)}
        return stock_api.get_company_industry_as_of(
            instrument_id=resolved_id,
            as_of_date=as_of_date,
            taxonomy_system=as_of_taxonomy_system,
            include_snapshot=include_snapshot,
        )
    else:
        return {
            "error": f"未知action '{action}'，可选: taxonomy, components, index_analysis, as_of, company_as_of"
        }


@mcp.tool()
@safe_tool
def query_futures_basic(
    action: Literal["instruments", "instrument_detail", "contracts", "calendar", "readiness", "dictionary"],
    instrument_id: Optional[str] = None,
    exchange: Optional[str] = None,
    active_only: bool = True,
) -> Dict[str, Any]:
    """
    期货基础数据查询，包括品种列表、品种详情、合约列表、日历、就绪状态等

    参数:
    - action: 查询动作，可选:
        "instruments" - 期货品种列表
        "instrument_detail" - 品种详情（需instrument_id，如"CNF.AG.SHFE"）
        "contracts" - 合约列表
        "calendar" - 交易日历（需start_date/end_date传入exchange参数）
        "readiness" - 模块就绪状态
        "dictionary" - 期货字典（元数据）
    - instrument_id: 期货品种ID，如 "CNF.AG.SHFE"
    - exchange: 交易所，如 SHFE/DCE/CZCE/INE/GFEX
    - active_only: 仅活跃，默认True

    返回:
    - 期货基础数据字典
    """
    if action == "instruments":
        return get_futures_instruments(active_only=active_only)
    elif action == "instrument_detail":
        if not instrument_id:
            return {"error": "需要 instrument_id 参数，如 CNF.AG.SHFE"}
        return get_futures_instrument_detail(instrument_id=instrument_id)
    elif action == "contracts":
        return get_futures_contracts(
            instrument_id=instrument_id, exchange=exchange, active_only=active_only,
        )
    elif action == "calendar":
        return get_futures_calendar(exchange=exchange)
    elif action == "readiness":
        return get_futures_readiness(exchange=exchange)
    elif action == "dictionary":
        return get_futures_dictionary()
    else:
        return {"error": f"未知action '{action}'，可选: instruments, instrument_detail, contracts, calendar, readiness, dictionary"}


@mcp.tool()
@safe_tool
def query_futures_series(
    action: Literal["series", "series_prices", "series_mapping", "cycle_diagnostics", "default_prices", "contract_prices"],
    series_id: Optional[str] = None,
    instrument_id: Optional[str] = None,
    contract_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: Optional[int] = None,
    active_only: bool = True,
) -> Dict[str, Any]:
    """
    期货序列与价格数据查询，包括连续序列、价格、主力映射、周期诊断等

    参数:
    - action: 查询动作，可选:
        "series" - 连续序列列表
        "series_prices" - 连续序列价格（需series_id，如"CNF.AG.SHFE.main"）
        "series_mapping" - 主力合约映射（需series_id）
        "cycle_diagnostics" - 周期诊断（需series_id）
        "default_prices" - 默认价格（需instrument_id）
        "contract_prices" - 合约价格（需contract_id，如"CNF.AG.SHFE.AG2506"）
    - series_id: 序列ID，如 "CNF.AG.SHFE.main"
    - instrument_id: 期货品种ID，如 "CNF.AG.SHFE"
    - contract_id: 合约ID，如 "CNF.AG.SHFE.AG2506"
    - start_date: 开始日期，格式 YYYY-MM-DD
    - end_date: 结束日期，格式 YYYY-MM-DD
    - limit: 返回数量限制
    - active_only: 仅活跃，默认True

    返回:
    - 期货序列数据字典
    """
    if action == "series":
        return get_futures_series(
            instrument_id=instrument_id, active_only=active_only,
        )
    elif action == "series_prices":
        if not series_id:
            return {"error": "需要 series_id 参数，如 CNF.AG.SHFE.main"}
        return get_futures_series_prices(
            series_id=series_id, start_date=start_date, end_date=end_date, limit=limit,
        )
    elif action == "series_mapping":
        if not series_id:
            return {"error": "需要 series_id 参数"}
        return get_futures_series_mapping(
            series_id=series_id, start_date=start_date, end_date=end_date, limit=limit,
        )
    elif action == "cycle_diagnostics":
        if not series_id:
            return {"error": "需要 series_id 参数"}
        return get_futures_cycle_diagnostics(series_id=series_id)
    elif action == "default_prices":
        if not instrument_id:
            return {"error": "需要 instrument_id 参数，如 CNF.AG.SHFE"}
        return get_futures_default_prices(
            instrument_id=instrument_id, start_date=start_date, end_date=end_date, limit=limit,
        )
    elif action == "contract_prices":
        if not contract_id:
            return {"error": "需要 contract_id 参数，如 CNF.AG.SHFE.AG2506"}
        return get_futures_contract_prices(
            contract_id=contract_id, start_date=start_date, end_date=end_date, limit=limit,
        )
    else:
        return {"error": f"未知action '{action}'，可选: series, series_prices, series_mapping, cycle_diagnostics, default_prices, contract_prices"}


@mcp.tool()
@safe_tool
def query_commodity_data(
    action: Literal["series", "observations", "dictionary", "diagnostics", "indicators", "policy_events"],
    series_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    active_only: bool = True,
    category: Optional[str] = None,
    commodity_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    商品数据查询，涵盖伦铜/伦铝/伦铅/伦镍/伦锡/伦锌(LME)、布油/WTI、动力煤/港口煤价/煤炭运价、
    国内化工现货(PTA/甲醇/PVC/纯碱等)、海外农产品(大豆/玉米/棉花等)等47个序列

    参数:
    - action: 查询动作，可选:
        "series" - 商品序列列表（47个序列，含伦铜/布油/动力煤/运价等）
        "observations" - 商品价格观测（需series_id，如伦铜/布油/动力煤价格）
        "dictionary" - 商品字典（元数据）
        "diagnostics" - 数据诊断（序列数、缺失观测等）
        "indicators" - 商品指标
        "policy_events" - 政策事件（关税、限产等）
    - series_id: 商品序列ID（observations必填），常用:
        "CMD.METAL.COPPER.LME3M.DAILY"                       伦铜(3个月)
        "CMD.METAL.ALUMINIUM.LME3M.DAILY"                    伦铝(3个月)
        "CMD.METAL.ZINC.LME3M.DAILY"                        伦锌(3个月)
        "CMD.OIL.BRENT.SPOT.EIA.DAILY"                      布伦特原油
        "CMD.OIL.WTI.SPOT.EIA.DAILY"                        WTI原油
        "CMD.CN.COAL.THERMAL.SHANXI_BLEND_5500.NBS.TEN_DAY" 动力煤山西5500
        "CMD.CN.COAL.PORT_PRICE.BSPI.CCTDA.WEEKLY"          港口动力煤价格(BSPI)
        "CMD.CN.COAL.FREIGHT.CBCFI.SSE.DAILY"               煤炭运价指数(CBCFI)
        "CMD.CN.COAL.PORT_INVENTORY.BOHAI_RIM.CCTDA.WEEKLY" 环渤海港口煤炭库存
        "CMD.CN.CHEMICAL.PTA.SPOT.100PPI.DAILY"             PTA现货
        "CMD.CN.CHEMICAL.METHANOL.SPOT.100PPI.DAILY"        甲醇现货
    - start_date: 开始日期 YYYY-MM-DD（可选）
    - end_date: 结束日期 YYYY-MM-DD（可选）
    - active_only: 仅活跃序列，默认True
    - category: 指标类别（indicators用，可选）
    - commodity_id: 商品ID（policy_events用，可选）

    返回:
    - 商品数据字典
    """
    if action == "series":
        return stock_api.get_commodities_series(active_only=active_only)
    elif action == "observations":
        if not series_id:
            return {"error": "需要 series_id 参数，如 CMD.METAL.COPPER.LME3M.DAILY（伦铜）"}
        return stock_api.get_commodities_observations(
            series_id=series_id, start_date=start_date, end_date=end_date,
        )
    elif action == "dictionary":
        return stock_api.get_commodities_dictionary()
    elif action == "diagnostics":
        return stock_api.get_commodities_diagnostics()
    elif action == "indicators":
        return stock_api.get_commodities_indicators(category=category, series_id=series_id)
    elif action == "policy_events":
        return stock_api.get_commodities_policy_events(commodity_id=commodity_id)
    else:
        return {"error": f"未知action '{action}'，可选: series, observations, dictionary, diagnostics, indicators, policy_events"}


@mcp.tool()
@safe_tool
def query_fx_data(
    action: Literal["series", "rates", "convert", "indices", "index_observations", "dictionary", "readiness"],
    series_id: Optional[str] = None,
    from_currency: Optional[str] = None,
    to_currency: Optional[str] = None,
    amount: float = 1.0,
    date: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: Optional[int] = None,
    active_only: bool = True,
) -> Dict[str, Any]:
    """
    外汇数据查询，涵盖人民币对美元/欧元/日元的CFETS中间价、离岸市场即期价等9个序列

    参数:
    - action: 查询动作，可选:
        "series" - 外汇序列列表（9个序列，含人民币对美元/欧元/日元等）
        "rates" - 外汇汇率序列（需series_id）
        "convert" - 外汇换算（需from_currency/to_currency）
        "indices" - 外汇指数列表
        "index_observations" - 外汇指数观测（需series_id）
        "dictionary" - 外汇字典（货币、序列元数据）
        "readiness" - 模块就绪状态
    - series_id: 外汇序列ID（rates/index_observations用），常用:
        "FX.USD_CNY.CFETS.MID.DAILY"     人民币对美元(CFETS中间价)
        "FX.EUR_CNY.CFETS.MID.DAILY"     人民币对欧元(CFETS中间价)
        "FX.JPY_CNY.CFETS.MID.DAILY"     人民币对日元(CFETS中间价)
        "FX.USD_CNH.MARKET.SPOT.DAILY"   美元兑离岸人民币(市场即期)
        "FXI.USD_TRADE_WEIGHTED.FRED.DAILY" 美元贸易加权指数(index_observations用)
    - from_currency: 源币种（convert用），如 CNY/USD/EUR/JPY/CNH
    - to_currency: 目标币种（convert用）
    - amount: 源币种金额（convert用），默认1.0
    - date: 换算日期 YYYY-MM-DD（convert用，可选，默认最新）
    - start_date: 开始日期（可选）
    - end_date: 结束日期（可选）
    - limit: 最大返回行数，1-10000（可选）
    - active_only: 仅活跃序列，默认True

    返回:
    - 外汇数据字典
    """
    if action == "series":
        return stock_api.get_fx_series(active_only=active_only)
    elif action == "rates":
        if not series_id:
            return {"error": "需要 series_id 参数，如 FX.USD_CNY.CFETS.MID.DAILY（人民币对美元）"}
        return stock_api.get_fx_rates(
            series_id=series_id, start_date=start_date, end_date=end_date, limit=limit,
        )
    elif action == "convert":
        if not from_currency or not to_currency:
            return {"error": "需要 from_currency 和 to_currency 参数，如 CNY/USD"}
        return stock_api.convert_fx(
            from_currency=from_currency, to_currency=to_currency,
            amount=amount, date=date,
        )
    elif action == "indices":
        return stock_api.get_fx_indices()
    elif action == "index_observations":
        if not series_id:
            return {"error": "需要 series_id 参数，如 FXI.USD_TRADE_WEIGHTED.FRED.DAILY"}
        return stock_api.get_fx_index_observations(
            series_id=series_id, start_date=start_date, end_date=end_date, limit=limit,
        )
    elif action == "dictionary":
        return stock_api.get_fx_dictionary()
    elif action == "readiness":
        return stock_api.get_fx_readiness()
    else:
        return {"error": f"未知action '{action}'，可选: series, rates, convert, indices, index_observations, dictionary, readiness"}


@mcp.tool()
@safe_tool
def query_risk_free_rate(
    action: Literal["series", "rate"],
    series_id: str = "china_treasury_10y",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    无风险利率查询（含10年期国债收益率）

    参数:
    - action: 查询动作，可选:
        "series" - 无风险利率序列列表
        "rate" - 利率观测数据（默认 china_treasury_10y 中国10年期国债收益率）
    - series_id: 序列标识，默认 "china_treasury_10y"（rate用）
    - start_date: 起始日期 YYYY-MM-DD（可选，含）
    - end_date: 结束日期 YYYY-MM-DD（可选，含）

    返回:
    - 无风险利率数据字典
    """
    if action == "series":
        return stock_api.get_risk_free_rate_series()
    elif action == "rate":
        return stock_api.get_risk_free_rate(
            series_id=series_id, start_date=start_date, end_date=end_date,
        )
    else:
        return {"error": f"未知action '{action}'，可选: series, rate"}


@mcp.tool()
@safe_tool
def query_financial_pit(
    action: Literal["cross_section", "panel", "coverage", "changes"],
    as_of: Optional[str] = None,
    report_period: Optional[str] = None,
    exchange: Optional[str] = None,
    fields: Optional[str] = None,
    instrument_id: Optional[str] = None,
    available_at_lte: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> Dict[str, Any]:
    """
    全市场财务 PIT（Point-In-Time）面板查询

    核心能力：在任意历史时点 T，一次调用返回全市场每只股票"截至 T 已公告的
    最新一期财务横截面"。每票自动回退到各自最新可知报告期，无未来函数
    （弱 PIT：时间严格 + 数值取最新口径 + 带更正防护），适用于量化回测的
    调仓日因子取数。

    参数:
    - action: 查询动作，可选:
        "cross_section" - 时点横截面（主接口，需 as_of）
        "panel" - 面板原始行分页（供本地全量缓存后离线装配）
        "coverage" - 覆盖与数据质量自检
        "changes" - 增量变更流（游标轮询，重放幂等）
    - as_of: 时点 YYYYMMDD（cross_section 必填），返回每票 available_at <= as_of 的最新报告期
    - report_period: 报告期 YYYYMMDD（可选过滤）
    - exchange: 交易所过滤 SSE/SZSE/BSE，逗号分隔（cross_section 可选）
    - fields: 字段投影，逗号分隔（cross_section 可选，减少返回体积）
    - instrument_id: 单只股票过滤，如 "000001.SZ"（panel 可选）
    - available_at_lte: 仅返回 available_at <= 该日期 YYYYMMDD（panel 可选）
    - cursor: 变更流游标（changes 用，首次省略，用返回 next_cursor 续轮询）
    - limit: 单页上限（cross_section/panel 最大 2000）
    - offset: 分页偏移

    返回:
    - 财务面板数据字典，含 guard/universe_note/stats/items 等

    关键字段说明:
    - available_at: 公告日（信息可知时点）；effective_at: 公告后次一交易日（执行时点）
    - available_at_quality: exact > exact_event > statutory_deadline > delayed_estimate
    - share_validation: consensus（可直接用）/ discrepancy（建议剔除）/ single_source / null
    - 单位：roe/gross_margin 等为百分数（15.6=15.6%）；eps/bps 为元（累计口径不预年化）

    已知限制:
    - 报告期自 2023-12-31 起 12 期，回测起点最早 2024 年初
    - universe 为当前在市股票，无退市股数据，存在存活偏差
    """
    # as_of 时点横截面（主接口）
    if action == "cross_section":
        if not as_of:
            return {"error": "cross_section 动作需要 as_of 参数（YYYYMMDD，如 20260801）"}
        return stock_api.get_financial_pit_cross_section(
            as_of=_normalize_pit_date(as_of),
            report_period=_normalize_pit_date(report_period),
            exchange=exchange,
            fields=fields,
            limit=limit,
            offset=offset,
        )
    # 面板原始行分页
    elif action == "panel":
        return stock_api.get_financial_pit_panel(
            report_period=_normalize_pit_date(report_period),
            instrument_id=instrument_id,
            available_at_lte=_normalize_pit_date(available_at_lte),
            limit=limit,
            offset=offset,
        )
    # 覆盖与质量自检
    elif action == "coverage":
        return stock_api.get_financial_pit_coverage(
            report_period=_normalize_pit_date(report_period),
        )
    # 增量变更流
    elif action == "changes":
        return stock_api.get_financial_pit_changes(cursor=cursor, limit=limit)
    else:
        return {
            "error": f"未知action '{action}'，可选: cross_section, panel, coverage, changes"
        }


# ==================== 数据健康自检工具 ====================


@mcp.tool()
@safe_tool
def query_data_health(
    sample_stock: str = "600519",
    risk_free_series_id: str = "china_treasury_10y",
) -> Dict[str, Any]:
    """
    数据健康自检：一次返回各数据集的最新业务日期、滞后交易日与新鲜度判断

    背景:
    - 各接口的时点字段命名不一致（time / as_of_date / data_as_of / observation_date），
      调用方原本只能逐个接口试才知道数据到哪一天，成本高。

    参数:
    - sample_stock: 用于探测行情最新日期的样本股，默认 600519
    - risk_free_series_id: 无风险利率序列，默认 china_treasury_10y（中国10年期国债）

    返回结构:
    - generated_at: 本次自检时间
    - backend: 后端 /health 返回的状态、数据库行数、数据任务批次
    - datasets.quotes: 最新行情日期、滞后交易日、是否新鲜
    - datasets.financial_pit: 最新完整报告期、覆盖数量
    - datasets.risk_free_rate: 最新观测日期、滞后交易日、是否新鲜
    - criteria: is_fresh 的判定口径

    说明:
    - 单个数据集探测失败不影响其他数据集，失败项返回 error 字段
    - is_fresh 口径: 行情滞后 <= 1 个交易日、利率滞后 <= 3 个交易日（容忍盘前与周末）
    """
    today = datetime.now().strftime("%Y-%m-%d")
    report: Dict[str, Any] = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "request_date": today,
        "criteria": {
            "quotes_fresh": "staleness_trading_days <= 1",
            "risk_free_fresh": "staleness_trading_days <= 3",
        },
        "datasets": {},
    }

    # 1) 后端健康状态与数据库规模
    try:
        health = stock_api._request("/health", timeout=60)
        if isinstance(health, dict):
            report["backend"] = {
                "status": health.get("status"),
                "database": health.get("database") or health.get("db"),
                "data_manager": health.get("data_manager") or health.get("progress"),
            }
        else:
            report["backend"] = {"raw": health}
    except Exception as e:
        report["backend"] = {"error": str(e)}

    # 2) 行情：用样本股最新行情反推数据截止日
    try:
        quotes = stock_api.get_latest_quotes([sample_stock])
        row = quotes[0] if isinstance(quotes, list) and quotes else {}
        if isinstance(row, dict) and row.get("time"):
            as_of = str(row["time"])[:10]
            lag = _trading_day_lag(as_of, today)
            report["datasets"]["quotes"] = {
                "sample_symbol": row.get("symbol") or sample_stock,
                "as_of": as_of,
                "staleness_trading_days": lag,
                "is_fresh": lag is not None and lag <= 1,
                "source": row.get("source"),
                "quality_score": row.get("quality_score"),
            }
        else:
            report["datasets"]["quotes"] = {"error": "样本股无行情返回", "sample_symbol": sample_stock}
    except Exception as e:
        report["datasets"]["quotes"] = {"error": str(e)}

    # 3) 财务 PIT：最新完整报告期与覆盖数量
    try:
        coverage = stock_api.get_financial_pit_coverage()
        if isinstance(coverage, dict):
            periods = coverage.get("periods") or coverage.get("items") or []
            latest = coverage.get("latest_complete_period")
            if not latest and isinstance(periods, list) and periods:
                # periods 结构未知时，取 report_period 最大的一项
                candidates = [
                    p.get("report_period") for p in periods
                    if isinstance(p, dict) and p.get("report_period")
                ]
                latest = max(candidates) if candidates else None
            report["datasets"]["financial_pit"] = {
                "latest_complete_period": latest,
                "rows": coverage.get("actual_count") or coverage.get("total"),
                "universe_note": coverage.get("universe_note"),
            }
        else:
            report["datasets"]["financial_pit"] = {"raw": coverage}
    except Exception as e:
        report["datasets"]["financial_pit"] = {"error": str(e)}

    # 4) 无风险利率：最新观测日
    try:
        rf = stock_api.get_risk_free_rate(series_id=risk_free_series_id)
        observations = []
        if isinstance(rf, dict):
            observations = rf.get("observations") or rf.get("data") or []
        if isinstance(observations, dict):
            observations = list(observations.values())
        dates = [
            str(o.get("observation_date") or o.get("date") or "")[:10]
            for o in observations if isinstance(o, dict)
        ]
        dates = [d for d in dates if d]
        if dates:
            as_of = max(dates)
            lag = _trading_day_lag(as_of, today)
            report["datasets"]["risk_free_rate"] = {
                "series_id": risk_free_series_id,
                "as_of": as_of,
                "staleness_trading_days": lag,
                "is_fresh": lag is not None and lag <= 3,
                "observations_returned": len(dates),
            }
        else:
            report["datasets"]["risk_free_rate"] = {
                "series_id": risk_free_series_id,
                "error": "未返回观测值",
            }
    except Exception as e:
        report["datasets"]["risk_free_rate"] = {"error": str(e)}

    # 统一新鲜度结论：所有已成功探测的数据集是否都新鲜
    flags = [
        d.get("is_fresh")
        for d in report["datasets"].values()
        if isinstance(d, dict) and "is_fresh" in d
    ]
    report["all_fresh"] = bool(flags) and all(flags)
    report["comment"] = (
        "行情为非实时快照，最新日期以 datasets.quotes.as_of 为准；"
        "财务 PIT 为弱 PIT（仅覆盖在市股票）。"
    )
    return report


# ==================== 会话空闲回收 ====================


def _install_session_idle_timeout() -> None:
    """
    为 Streamable HTTP 会话启用空闲回收（避免会话只增不减）。

    背景：
    - mcp 1.27.0 的 StreamableHTTPSessionManager 支持 session_idle_timeout，
      默认 None（永不回收），会话要等客户端发 DELETE 或进程退出才释放。
    - 但 FastMCP 3.2.4 的 http_app()/create_streamable_http_app() 没有透传该参数，
      直接 mcp.run(transport="http", session_idle_timeout=...) 会被当成未知参数报错。
    - 因此这里在 FastMCP 的 http 模块里把管理器类换成"补默认值"的子类：
      会话管理器是在 Starlette lifespan 启动时才实例化的，届时会从该模块的全局名
      取到子类，所以必须在 mcp.run() 之前完成替换。

    环境变量：
    - MCP_SESSION_IDLE_TIMEOUT：空闲秒数，默认 1800（30 分钟）；
      设为 0 或负数则关闭回收，恢复 FastMCP 原有行为。
    """
    raw = os.environ.get("MCP_SESSION_IDLE_TIMEOUT", "1800")
    try:
        timeout = float(raw)
    except (TypeError, ValueError):
        logger.warning(f"MCP_SESSION_IDLE_TIMEOUT='{raw}' 不是数字，回退默认 1800 秒")
        timeout = 1800.0

    if timeout <= 0:
        logger.info("会话空闲回收未启用（MCP_SESSION_IDLE_TIMEOUT<=0）")
        return

    import fastmcp.server.http as fastmcp_http

    base_cls = fastmcp_http.StreamableHTTPSessionManager

    # 兼容不同 mcp 版本：没有该参数就不要打补丁，避免启动即 TypeError
    if "session_idle_timeout" not in inspect.signature(base_cls.__init__).parameters:
        logger.warning(
            "当前 mcp 版本不支持 session_idle_timeout，跳过会话空闲回收"
        )
        return

    # 幂等：重复调用（如被多次导入）不重复打补丁
    if getattr(base_cls, "_idle_timeout_patched", False):
        logger.info(f"会话空闲回收已启用：{timeout:.0f} 秒无请求即终止会话")
        return

    class _IdleReclaimSessionManager(base_cls):
        """会话管理器子类：未显式指定空闲超时时补上默认值"""

        def __init__(self, *args, **kwargs):
            kwargs.setdefault("session_idle_timeout", timeout)
            super().__init__(*args, **kwargs)

    _IdleReclaimSessionManager._idle_timeout_patched = True
    fastmcp_http.StreamableHTTPSessionManager = _IdleReclaimSessionManager
    logger.info(f"会话空闲回收已启用：{timeout:.0f} 秒无请求即终止会话")


# ==================== 启动入口 ====================

if __name__ == "__main__":
    # 支持三种运行模式:
    # 1. stdio模式（默认）: python stock_mcp_integrated.py
    # 2. SSE模式: MCP_TRANSPORT=sse
    # 3. Streamable HTTP模式: MCP_TRANSPORT=http（推荐，MCP协议新标准）
    #    可选环境变量:
    #    - MCP_HOST: 监听地址，默认 0.0.0.0
    #    - MCP_PORT: 监听端口，默认 8091
    transport = os.environ.get("MCP_TRANSPORT", "stdio").lower()
    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("MCP_PORT", "8091"))

    # 传输模式映射：用户简写 -> FastMCP transport 参数
    TRANSPORT_MAP = {
        "stdio": "stdio",
        "sse": "sse",
        "http": "streamable-http",
        "streamable-http": "streamable-http",
        "streamable": "streamable-http",
    }

    mapped = TRANSPORT_MAP.get(transport)
    if mapped is None:
        logger.error(f"不支持的传输模式: {transport}，可选: stdio, sse, http")
        sys.exit(1)

    if mapped == "stdio":
        logger.info("启动 StockIntegratedMCP 服务器 (stdio模式)")
        mcp.run(transport="stdio")
    else:
        # Streamable HTTP 模式下启用会话空闲回收（SSE 不涉及会话管理器，无需处理）
        if mapped == "streamable-http":
            _install_session_idle_timeout()
        logger.info(f"启动 StockIntegratedMCP 服务器 ({mapped}模式) - {host}:{port}")
        mcp.run(transport=mapped, host=host, port=port)
