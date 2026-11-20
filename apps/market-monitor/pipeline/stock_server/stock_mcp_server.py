from fastmcp import FastMCP
import os

import requests
from datetime import datetime
from typing import Optional, Dict, Any


QUOTE_API = os.environ.get("QUOTE_API", "https://quotes.anchan.kazuhahub.com")


class StockQuoteAPI:
    BASE_URL = QUOTE_API + "/api/v1/quotes/daily"
    LATEST_BASE_URL = QUOTE_API + "/api/v1/quotes/latest"
    CALENDAR_BASE_URL = QUOTE_API + "/api/v1/calendar/trading"
    INSTRUMENT_BASE_URL = QUOTE_API + "/api/v1/instruments/symbol"

    def __init__(self):
        self.session = requests.Session()

    def _get_exchange(self, stock_code: str) -> str:
        """根据股票代码首位判断交易所，支持沪市/深市/创业板/ETF/北交所"""
        prefix = stock_code[0]
        if prefix == '6' or prefix == '5':
            return 'SSE'  # 沪市主板/沪市ETF
        elif prefix in ('0', '3', '1'):
            return 'SZSE'  # 深市主板/创业板/深市ETF
        elif prefix in ('8', '4'):
            return 'BSE'  # 北交所
        else:
            raise ValueError(f"无法识别股票代码 {stock_code} 的交易所")

    def _format_date(self, date_str: str) -> str:
        try:
            datetime.strptime(date_str, '%Y-%m-%d')
            return f"{date_str}T00:00:00"
        except ValueError:
            raise ValueError(f"日期格式错误，请使用 YYYY-MM-DD 格式，例如：2025-01-05")

    def get_daily_quotes(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
        return_format: str = 'json'
    ) -> Dict[str, Any]:
        instrument_id = f"{stock_code}.{self._get_exchange(stock_code)}"
        formatted_start_date = self._format_date(start_date)
        formatted_end_date = self._format_date(end_date)

        params = {
            'instrument_id': instrument_id,
            'start_date': formatted_start_date,
            'end_date': formatted_end_date,
            'return_format': return_format
        }

        try:
            response = self.session.get(self.BASE_URL, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"请求失败: {e}")
        except ValueError:
            raise Exception(f"JSON解析失败，请检查API返回格式")

    def get_latest_quotes(
        self,
        stock_codes: list,
        return_format: str = 'json'
    ) -> Dict[str, Any]:
        instrument_ids = []
        for stock_code in stock_codes:
            exchange = self._get_exchange(stock_code)
            instrument_id = f"{stock_code}.{exchange}"
            instrument_ids.append(instrument_id)

        params = {
            'instrument_ids': instrument_ids,
            'return_format': return_format
        }

        try:
            response = self.session.get(self.LATEST_BASE_URL, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"请求失败: {e}")
        except ValueError:
            raise Exception(f"JSON解析失败，请检查API返回格式")

    def get_trading_calendar(
        self,
        exchange: str,
        start_date: str,
        end_date: str,
        return_format: str = 'json'
    ) -> Dict[str, Any]:
        valid_exchanges = ["SSE", "SZSE"]
        if exchange not in valid_exchanges:
            raise ValueError(f"无效的交易所代码 {exchange}，支持的交易所：{valid_exchanges}")
        
        formatted_start_date = self._format_date(start_date)
        formatted_end_date = self._format_date(end_date)

        params = {
            'exchange': exchange,
            'start_date': formatted_start_date,
            'end_date': formatted_end_date,
            'return_format': return_format
        }

        try:
            response = self.session.get(self.CALENDAR_BASE_URL, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"请求失败: {e}")
        except ValueError:
            raise Exception(f"JSON解析失败，请检查API返回格式")

    def get_instrument_info(
        self,
        stock_code: str,
        return_format: str = 'json'
    ) -> Dict[str, Any]:
        if not (isinstance(stock_code, str) and len(stock_code) == 6 and stock_code.isdigit()):
            raise ValueError(f"无效的股票代码 {stock_code}，请输入6位数字股票代码")

        url = f"{self.INSTRUMENT_BASE_URL}/{stock_code}"
        params = {
            'return_format': return_format
        }

        try:
            response = self.session.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"请求失败: {e}")
        except ValueError:
            raise Exception(f"JSON解析失败，请检查API返回格式")

    def close(self):
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# 创建MCP服务器实例
mcp = FastMCP("StockQuoteMCP")

# 初始化股票API客户端
stock_api = StockQuoteAPI()


@mcp.tool()
def get_daily_stock_data(stock_code: str, start_date: str, end_date: str) -> Dict[str, Any]:
    """
    获取股票日度行情数据
    
    参数:
    - stock_code: 6位股票代码，例如 "601126" 或 "300708"
    - start_date: 开始日期，格式 YYYY-MM-DD
    - end_date: 结束日期，格式 YYYY-MM-DD
    
    返回:
    - 包含股票行情数据的字典
    """
    return stock_api.get_daily_quotes(stock_code, start_date, end_date)


@mcp.tool()
def get_latest_stock_data(stock_code) -> Dict[str, Any]:
    """
    获取股票最新行情数据，支持单个或多个股票

    参数:
    - stock_code: 6位股票代码，支持单个字符串或列表
      例如 "000001" 或 ["000001", "600000", "300708"]

    返回:
    - 包含股票最新行情数据的字典
    """
    # 兼容单个字符串输入，自动转为列表
    if isinstance(stock_code, str):
        codes = [stock_code]
    else:
        codes = list(stock_code)
    result = stock_api.get_latest_quotes(codes)
    return {
        "stock_codes": codes,
        "data": result
    }


@mcp.tool()
def get_trading_calendar_data(exchange: str, start_date: str, end_date: str) -> Dict[str, Any]:
    """
    获取交易日历数据
    
    参数:
    - exchange: 交易所代码，例如 "SSE" (上海证券交易所) 或 "SZSE" (深圳证券交易所)
    - start_date: 开始日期，格式 YYYY-MM-DD
    - end_date: 结束日期，格式 YYYY-MM-DD
    
    返回:
    - 包含交易日历数据的字典
    """
    return stock_api.get_trading_calendar(exchange, start_date, end_date)


@mcp.tool()
def get_stock_info(stock_code: str) -> Dict[str, Any]:
    """
    获取股票基本信息
    
    参数:
    - stock_code: 6位股票代码，例如 "300708" 或 "601126"
    
    返回:
    - 包含股票基本信息的字典
    """
    return stock_api.get_instrument_info(stock_code)


if __name__ == "__main__":
    mcp.run(transport="stdio")
