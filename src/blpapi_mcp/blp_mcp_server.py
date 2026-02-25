

import typing

import blpapi
import blpapi.version
import pandas as pd
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.utilities.logging import get_logger
from mcp.server.transport_security import TransportSecuritySettings
from xbbg import blp

from . import types
from .rate_limit_counter import DailyRateLimitCounter

# Daily cap: 10,000 hits (EST/NY). One hit = one cell in the returned DataFrame.
RATE_LIMIT_MSG = (
  "Daily limit of 10,000 Bloomberg hits has been reached (America/New_York day). "
  "No further BLP requests can be made until the next day. Try again tomorrow."
)


def _count_dataframe_cells(value: typing.Any) -> int:
  """Number of data cells (values) in a DataFrame; 0 for non-DataFrame."""
  if value is None:
    return 0
  if isinstance(value, pd.DataFrame):
    return int(value.size)
  return 0


def serve(args: types.StartupArgs):
  # Streamable HTTP at /mcp so clients can use the same URL for GET (SSE) and POST (JSON-RPC)
  # Disable strict Host validation so requests via Cloudflare tunnel (Host: *.trycloudflare.com) are accepted
  mcp = FastMCP(
    "blpapi-mcp",
    host=args.host,
    port=args.port,
    streamable_http_path="/mcp",
    json_response=True,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
  )

  logger = get_logger(__name__)
  logger.info("startup args:" + str(args))
  logger.info("blpapi version:" + blpapi.version()) # type: ignore

  # Single daily rate-limit counter (10k hits/day EST), persisted to var/ratelimit_state.json
  rate_limit = DailyRateLimitCounter()

  def _wrap_blp(name: str, call_blp: typing.Callable[[], typing.Any]) -> typing.Any:
    if not rate_limit.can_consume(1):
      return RATE_LIMIT_MSG
    try:
      out = call_blp()
      n = _count_dataframe_cells(out)
      if n > 0:
        rate_limit.record_usage(n)
      return out
    except Exception:
      raise

  @mcp.tool(
    name="bdp",
    description="Get Bloomberg reference data"
  )
  async def bdp(tickers:typing.List[str], flds:typing.List[str], kwargs: types.BloombergKWArgs = None) -> typing.Any:
    return _wrap_blp("bdp", lambda: blp.bdp(tickers=tickers, flds=flds) if kwargs is None else blp.bdp(tickers=tickers, flds=flds, kwargs=kwargs))

  @mcp.tool(
    name="bds",
    description="Get Bloomberg block data"
  )
  async def bds(tickers:typing.List[str], flds:typing.List[str], use_port:bool=False, kwargs:types.BloombergKWArgs=None) -> typing.Any:
    return _wrap_blp("bds", lambda: blp.bds(tickers=tickers, flds=flds, use_port=use_port) if kwargs is None else blp.bds(tickers=tickers, flds=flds, use_port=use_port, kwargs=kwargs))

  @mcp.tool(
    name="bdh",
    description="Get Bloomberg historical data"
  )
  async def bdh(tickers:typing.List[str], flds:typing.List[str], start_date:typing.Union[None, str]=None, end_date:str="today", adjust: typing.Union[str, None] = None, kwargs: types.BloombergKWArgs = None) -> typing.Any:
    return _wrap_blp("bdh", lambda: blp.bdh(tickers=tickers, flds=flds, start_date=start_date, end_date=end_date, adjust=adjust) if kwargs is None else blp.bdh(tickers=tickers, flds=flds, start_date=start_date, end_date=end_date, adjust=adjust, kwargs=kwargs))

  @mcp.tool(
    name="bdib",
    description="Get Bloomberg intraday bar data"
  )
  async def bdib(ticker:str, dt:str, session:str = "allday", typ:str = "TRADE", kwargs: types.BloombergKWArgs=None) -> typing.Any:
    return _wrap_blp("bdib", lambda: blp.bdib(ticker=ticker, dt=dt, session=session, typ=typ) if kwargs is None else blp.bdib(ticker=ticker, dt=dt, session=session, typ=typ, kwargs=kwargs))

  @mcp.tool(
    name="bdtick",
    description="Get Bloomberg tick data"
  )
  async def bdtick(ticker:str, dt:str, session:str="allday", time_range:typing.Union[None, typing.Tuple[str]]=None, types:typing.Union[None, typing.List[str]]=None, kwargs:types.BloombergKWArgs=None) -> typing.Any:
    return _wrap_blp("bdtick", lambda: blp.bdtick(ticker=ticker, dt=dt, session=session, time_range=time_range, types=types) if kwargs is None else blp.bdtick(ticker=ticker, dt=dt, session=session, time_range=time_range, types=types, kwargs=kwargs))

  @mcp.tool(
    name="earning",
    description="Get Bloomberg earning exposure by Geo or Products"
  )
  async def earning(ticker:str, by:str="Geo", typ:str="Revenue", ccy:typing.Union[None,str]=None, level: typing.Union[None, str]=None, kwargs:types.BloombergKWArgs=None) -> typing.Any:
    return _wrap_blp("earning", lambda: blp.earning(ticker=ticker, by=by, typ=typ, ccy=ccy, level=level) if kwargs is None else blp.earning(ticker=ticker, by=by, typ=typ, ccy=ccy, level=level, kwargs=kwargs))

  @mcp.tool(
    name="dividend",
    description="Get Bloomberg divident / split history"
  )
  async def dividend(tickers:typing.List[str], typ:str="all", start_date:typing.Union[None,str]=None, end_date:typing.Union[None,str]=None, kwargs:types.BloombergKWArgs=None) -> typing.Any:
    return _wrap_blp("dividend", lambda: blp.dividend(tickers=tickers, typ=typ, start_date=start_date, end_date=end_date) if kwargs is None else blp.dividend(tickers=tickers, typ=typ, start_date=start_date, end_date=end_date, kwargs=kwargs))

  @mcp.tool(
    name="beqs",
    description="Get Bloomberg equity screening"
  )
  async def beqs(screen:str, asof:typing.Union[None,str]=None, typ:str="PRIVATE", group:str="General", kwargs:types.BloombergKWArgs=None) -> typing.Any:
    return _wrap_blp("beqs", lambda: blp.beqs(screen=screen, asof=asof, typ=typ, group=group) if kwargs is None else blp.beqs(screen=screen, asof=asof, typ=typ, group=group, kwargs=kwargs))

  @mcp.tool(
    name="turnover",
    description="Calculate the adjusted turnover (in millions)"
  )
  async def turnover(tickers:typing.List[str], flds:str="Turnover", start_date:typing.Union[None,str]=None, end_date:typing.Union[None,str]=None, ccy:str="USD", factor:float=1e6) -> typing.Any:
    return _wrap_blp("turnover", lambda: blp.turnover(tickers=tickers, flds=flds, start_date=start_date, end_date=end_date, ccy=ccy, factor=factor))


  mcp.run(transport=args.transport.value)
