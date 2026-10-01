#property strict
#property version   "0.5.0"
#property description "Telegram signal polling EA with backend reporting and safe demo default"

#include <Trade/Trade.mqh>

enum ENUM_LOT_MODE
  {
   LOT_FIXED = 0,
   LOT_RISK_PERCENT = 1
  };

input string ServerURL = "http://127.0.0.1:8000";
input string ApiKey = "";
input int PollIntervalMs = 1000;
input long MagicNumber = 26093001;
input ENUM_LOT_MODE LotMode = LOT_FIXED;
input double FixedLot = 0.01;
input double RiskPercent = 1.0;
input int MaxSlippage = 20;
input int MaxSpreadPoints = 80;
input int MaxOpenTrades = 3;
input bool AllowBuy = true;
input bool AllowSell = true;
input bool UseDefaultSLTP = true;
input int DefaultSLPoints = 500;
input int DefaultTPPoints = 1000;
input string SymbolSuffix = "";
input int MaxSignalAgeSeconds = 120;
input int PendingOrderExpiryMinutes = 60;
input bool TradeOnlyAllowedSymbols = true;
input string AllowedSymbolsCsv = "XAUUSD,EURUSD,GBPUSD,USDJPY,AUDUSD";
input bool DemoMode = true;
input double MaxLot = 5.0;
input double MaxMarketDeviationPct = 5.0;
input int MaxRetries = 3;

CTrade g_trade;
datetime g_last_heartbeat = 0;
datetime g_last_expiry_scan = 0;
string g_connection_status = "starting";
string g_last_signal = "none";
int g_signal_count = 0;
int g_wins = 0;
int g_losses = 0;

string TrimTrailingSlash(string value)
  {
   while(StringLen(value) > 0 && StringSubstr(value, StringLen(value) - 1, 1) == "/")
      value = StringSubstr(value, 0, StringLen(value) - 1);
   return value;
  }

string JsonEscape(string value)
  {
   StringReplace(value, "\\", "\\\\");
   StringReplace(value, "\"", "\\\"");
   StringReplace(value, "\r", " ");
   StringReplace(value, "\n", " ");
   return value;
  }

bool HttpRequest(const string method, const string path, const string payload, string &response_body)
  {
   if(StringLen(ApiKey) < 24)
     {
      g_connection_status = "API key missing/short";
      return false;
     }
   string base = TrimTrailingSlash(ServerURL);
   string url = base + path;
   string headers = "Content-Type: application/json\r\nX-API-Key: " + ApiKey + "\r\n";
   char data[];
   char result[];
   string result_headers;
   if(StringLen(payload) > 0)
     {
      int count = StringToCharArray(payload, data, 0, WHOLE_ARRAY, CP_UTF8);
      if(count > 0)
         ArrayResize(data, count - 1);
     }
   else
      ArrayResize(data, 0);

   ResetLastError();
   int code = WebRequest(method, url, headers, 5000, data, result, result_headers);
   if(code < 200 || code >= 300)
     {
      int error = GetLastError();
      g_connection_status = StringFormat("HTTP %d / error %d", code, error);
      Print("[TelegramSignalEA] ", method, " ", path, " failed: ", g_connection_status);
      response_body = CharArrayToString(result, 0, -1, CP_UTF8);
      return false;
     }
   response_body = CharArrayToString(result, 0, -1, CP_UTF8);
   g_connection_status = "online";
   return true;
  }

int JsonValueStart(const string json, const string key)
  {
   string needle = "\"" + key + "\"";
   int key_pos = StringFind(json, needle);
   if(key_pos < 0)
      return -1;
   int colon = StringFind(json, ":", key_pos + StringLen(needle));
   if(colon < 0)
      return -1;
   int pos = colon + 1;
   while(pos < StringLen(json))
     {
      ushort c = StringGetCharacter(json, pos);
      if(c != 32 && c != 9 && c != 10 && c != 13)
         break;
      pos++;
     }
   return pos;
  }

string JsonValue(const string json, const string key)
  {
   int start = JsonValueStart(json, key);
   if(start < 0 || start >= StringLen(json))
      return "";
   ushort first = StringGetCharacter(json, start);
   if(first == '"')
     {
      bool escaped = false;
      for(int i = start + 1; i < StringLen(json); i++)
        {
         ushort c = StringGetCharacter(json, i);
         if(c == '"' && !escaped)
            return StringSubstr(json, start + 1, i - start - 1);
         if(c == '\\' && !escaped)
            escaped = true;
         else
            escaped = false;
        }
      return "";
     }
   if(first == '[' || first == '{')
     {
      int depth = 0;
      bool in_string = false;
      bool escaped = false;
      for(int i = start; i < StringLen(json); i++)
        {
         ushort c = StringGetCharacter(json, i);
         if(c == '"' && !escaped)
            in_string = !in_string;
         if(!in_string)
           {
            if(c == first)
               depth++;
            else if((first == '[' && c == ']') || (first == '{' && c == '}'))
              {
               depth--;
               if(depth == 0)
                  return StringSubstr(json, start, i - start + 1);
              }
           }
         if(c == '\\' && !escaped)
            escaped = true;
         else
            escaped = false;
        }
      return "";
     }
   int end = start;
   while(end < StringLen(json))
     {
      ushort c = StringGetCharacter(json, end);
      if(c == ',' || c == '}' || c == ']' || c == 10 || c == 13)
         break;
      end++;
     }
   return StringSubstr(json, start, end - start);
  }

string FirstSignalObject(const string response)
  {
   int items = StringFind(response, "\"items\"");
   if(items < 0)
      return "";
   int start = StringFind(response, "{", items);
   if(start < 0)
      return "";
   int depth = 0;
   bool in_string = false;
   bool escaped = false;
   for(int i = start; i < StringLen(response); i++)
     {
      ushort c = StringGetCharacter(response, i);
      if(c == '"' && !escaped)
         in_string = !in_string;
      if(!in_string)
        {
         if(c == '{')
            depth++;
         else if(c == '}')
           {
            depth--;
            if(depth == 0)
               return StringSubstr(response, start, i - start + 1);
           }
        }
      if(c == '\\' && !escaped)
         escaped = true;
      else
         escaped = false;
     }
   return "";
  }

double JsonNumber(const string json, const string key)
  {
   string value = JsonValue(json, key);
   if(value == "" || value == "null")
      return 0.0;
   return StringToDouble(value);
  }

long JsonLong(const string json, const string key)
  {
   string value = JsonValue(json, key);
   if(value == "" || value == "null")
      return 0;
   return (long)StringToInteger(value);
  }

double FirstArrayNumber(const string array_json)
  {
   if(StringLen(array_json) < 3)
      return 0.0;
   string values = StringSubstr(array_json, 1, StringLen(array_json) - 2);
   int comma = StringFind(values, ",");
   if(comma >= 0)
      values = StringSubstr(values, 0, comma);
   return StringToDouble(values);
  }

double FinalArrayNumber(const string array_json, const string action)
  {
   if(StringLen(array_json) < 3)
      return 0.0;
   string values = StringSubstr(array_json, 1, StringLen(array_json) - 2);
   int start = 0;
   double final_value = 0.0;
   while(start < StringLen(values))
     {
      int comma = StringFind(values, ",", start);
      string token = comma < 0 ? StringSubstr(values, start) : StringSubstr(values, start, comma - start);
      double value = StringToDouble(token);
      if(value > 0.0 && (final_value <= 0.0 || (action == "BUY" && value > final_value) || (action == "SELL" && value < final_value)))
         final_value = value;
      if(comma < 0)
         break;
      start = comma + 1;
     }
   return final_value;
  }

string SignalMarker(const long signal_id, const int leg=0)
  {
   string marker = "CTS:" + IntegerToString(signal_id);
   if(leg > 0)
      marker += ":" + IntegerToString(leg);
   return marker;
  }

long SignalIdFromComment(const string comment)
  {
   if(StringFind(comment, "CTS:") != 0)
      return 0;
   int separator = StringFind(comment, ":", 4);
   string value = separator < 0 ? StringSubstr(comment, 4) : StringSubstr(comment, 4, separator - 4);
   return (long)StringToInteger(value);
  }

string GlobalKey(const long signal_id, const string field, const int leg=0)
  {
   string suffix = field;
   if(leg > 0)
      suffix += IntegerToString(leg);
   return StringFormat("CT_%I64d_%I64d_%I64d_%s", AccountInfoInteger(ACCOUNT_LOGIN), MagicNumber, signal_id, suffix);
  }

int SavedState(const long signal_id, const int leg=0)
  {
   string key = GlobalKey(signal_id, "S", leg);
   if(!GlobalVariableCheck(key))
      return 0;
   return (int)GlobalVariableGet(key);
  }

void SaveReport(const long signal_id, const int state, const long ticket, const double price, const double lots, const int leg=0)
  {
   GlobalVariableSet(GlobalKey(signal_id, "S", leg), state);
   GlobalVariableSet(GlobalKey(signal_id, "T", leg), (double)ticket);
   GlobalVariableSet(GlobalKey(signal_id, "P", leg), price);
   GlobalVariableSet(GlobalKey(signal_id, "L", leg), lots);
  }

bool SendReport(const long signal_id, const string status, const long ticket, const string symbol,
                const string action, const double lots, const double price, const string reason, const int leg=0)
  {
   string body = StringFormat(
      "{\"signal_id\":%I64d,\"status\":\"%s\",\"ticket\":\"%I64d\",\"symbol\":\"%s\",\"action\":\"%s\",\"lots\":%.8f,\"exec_price\":%.8f,\"reason\":\"%s\",\"leg\":%d}",
      signal_id, status, ticket, JsonEscape(symbol), action, lots, price, JsonEscape(reason), leg);
   string response;
   return HttpRequest("POST", "/api/ea/report", body, response);
  }

void RepeatSavedReport(const long signal_id, const string symbol, const string action, const int leg=0)
  {
   int state = SavedState(signal_id, leg);
   if(state == 0)
      return;
   long ticket = (long)GlobalVariableGet(GlobalKey(signal_id, "T", leg));
   double price = GlobalVariableGet(GlobalKey(signal_id, "P", leg));
   double lots = GlobalVariableGet(GlobalKey(signal_id, "L", leg));
   string status = state == 1 ? "EXECUTED" : state == 4 ? "DRY_RUN" : state == 3 ? "FAILED" : "REJECTED";
   SendReport(signal_id, status, ticket, symbol, action, lots, price, "Idempotent report retry", leg);
  }

bool FindExistingSignalOrder(const long signal_id, long &ticket_out, double &lots_out, double &price_out, const int leg=0)
  {
   string marker = SignalMarker(signal_id, leg);
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong ticket = OrderGetTicket(i);
      if(ticket == 0)
         continue;
      if((long)OrderGetInteger(ORDER_MAGIC) == MagicNumber && StringFind(OrderGetString(ORDER_COMMENT), marker) == 0)
        {
         ticket_out = (long)ticket;
         lots_out = OrderGetDouble(ORDER_VOLUME_CURRENT);
         price_out = OrderGetDouble(ORDER_PRICE_OPEN);
         return true;
        }
     }
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if((long)PositionGetInteger(POSITION_MAGIC) == MagicNumber && StringFind(PositionGetString(POSITION_COMMENT), marker) == 0)
        {
         ticket_out = (long)ticket;
         lots_out = PositionGetDouble(POSITION_VOLUME);
         price_out = PositionGetDouble(POSITION_PRICE_OPEN);
         return true;
        }
     }
   return false;
  }

bool SymbolAllowed(const string symbol)
  {
   if(!TradeOnlyAllowedSymbols)
      return true;
   string allowed[];
   int count = StringSplit(AllowedSymbolsCsv, ',', allowed);
   for(int i = 0; i < count; i++)
     {
      string item = allowed[i];
      StringToUpper(item);
      string test = symbol;
      StringToUpper(test);
      if(item == test || (SymbolSuffix != "" && item + SymbolSuffix == test))
         return true;
     }
   return false;
  }

string ResolveSymbol(string requested)
  {
   if(requested == "")
      return _Symbol;
   if(SymbolSelect(requested, true))
      return requested;
   if(SymbolSuffix != "" && SymbolSelect(requested + SymbolSuffix, true))
      return requested + SymbolSuffix;
   return requested;
  }

int CountOpenTrades()
  {
   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(PositionGetTicket(i) > 0 && (long)PositionGetInteger(POSITION_MAGIC) == MagicNumber)
         count++;
     }
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      if(OrderGetTicket(i) > 0 && (long)OrderGetInteger(ORDER_MAGIC) == MagicNumber)
         count++;
     }
   return count;
  }

double NormalizePrice(const string symbol, const double price)
  {
   if(price <= 0.0)
      return 0.0;
   double tick = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
   int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   if(tick <= 0.0)
      tick = SymbolInfoDouble(symbol, SYMBOL_POINT);
   return NormalizeDouble(MathRound(price / tick) * tick, digits);
  }

double NormalizeLots(const string symbol, double lots)
  {
   double min_lot = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
   double max_lot = MathMin(SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX), MaxLot);
   double step = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
   if(step <= 0.0 || min_lot <= 0.0 || max_lot <= 0.0)
      return 0.0;
   lots = MathMin(lots, max_lot);
   lots = MathFloor(lots / step + 1e-8) * step;
   int digits = 2;
   if(step < 0.01) digits = 3;
   if(step < 0.001) digits = 4;
   lots = NormalizeDouble(lots, digits);
   if(lots < min_lot)
      return 0.0;
   return lots;
  }

double CalculateLots(const string symbol, const double price, const double stop_loss)
  {
   if(LotMode == LOT_FIXED)
      return NormalizeLots(symbol, FixedLot);
   if(stop_loss <= 0.0 || price <= 0.0)
      return 0.0;
   double tick_size = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
   double tick_value = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE_LOSS);
   if(tick_value <= 0.0)
      tick_value = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE);
   if(tick_size <= 0.0 || tick_value <= 0.0)
      return 0.0;
   double risk_money = AccountInfoDouble(ACCOUNT_BALANCE) * RiskPercent / 100.0;
   double risk_per_lot = MathAbs(price - stop_loss) / tick_size * tick_value;
   if(risk_money <= 0.0 || risk_per_lot <= 0.0)
      return 0.0;
   return NormalizeLots(symbol, risk_money / risk_per_lot);
  }

bool CheckSpread(const string symbol)
  {
   double ask = SymbolInfoDouble(symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(symbol, SYMBOL_BID);
   double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
   if(ask <= 0.0 || bid <= 0.0 || point <= 0.0)
      return false;
   double spread = (ask - bid) / point;
   return spread <= MaxSpreadPoints;
  }

bool CheckMargin(const ENUM_ORDER_TYPE order_type, const string symbol, const double lots, const double price)
  {
   double margin = 0.0;
   if(!OrderCalcMargin(order_type, symbol, lots, price, margin))
      return false;
   return margin <= AccountInfoDouble(ACCOUNT_MARGIN_FREE);
  }

bool CheckPriceLevels(const string symbol, const string action, const double reference, const double sl, const double tp)
  {
   if(reference <= 0.0)
      return false;
   double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
   if(point <= 0.0)
      point = 0.00001;
   double minimum = (double)SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL) * point;
   if(action == "BUY")
     {
      if(sl > 0.0 && (sl >= reference || reference - sl < minimum)) return false;
      if(tp > 0.0 && (tp <= reference || tp - reference < minimum)) return false;
     }
   else
     {
      if(sl > 0.0 && (sl <= reference || sl - reference < minimum)) return false;
      if(tp > 0.0 && (tp >= reference || reference - tp < minimum)) return false;
     }
   return true;
  }

bool PlaceOrder(const string action, const string order_type, const string symbol, const double entry,
                const double sl, const double tp, const double lots, const long signal_id, const int leg)
  {
   string comment = SignalMarker(signal_id, leg);
   g_trade.SetExpertMagicNumber((ulong)MagicNumber);
   g_trade.SetDeviationInPoints((ulong)MaxSlippage);
   g_trade.SetTypeFillingBySymbol(symbol);
   bool placed = false;
   int expiration_modes = (int)SymbolInfoInteger(symbol, SYMBOL_EXPIRATION_MODE);
   ENUM_ORDER_TYPE_TIME time_type = (expiration_modes & SYMBOL_EXPIRATION_SPECIFIED) != 0 ? ORDER_TIME_SPECIFIED : ORDER_TIME_GTC;
   datetime expiration = TimeCurrent() + PendingOrderExpiryMinutes * 60;
   for(int attempt = 0; attempt < MathMax(1, MaxRetries); attempt++)
     {
      if(order_type == "MARKET")
        {
         if(action == "BUY") placed = g_trade.Buy(lots, symbol, 0.0, sl, tp, comment);
         else placed = g_trade.Sell(lots, symbol, 0.0, sl, tp, comment);
        }
      else if(order_type == "LIMIT")
        {
         if(action == "BUY") placed = g_trade.BuyLimit(lots, entry, symbol, sl, tp, time_type, expiration, comment);
         else placed = g_trade.SellLimit(lots, entry, symbol, sl, tp, time_type, expiration, comment);
        }
      else
        {
         if(action == "BUY") placed = g_trade.BuyStop(lots, entry, symbol, sl, tp, time_type, expiration, comment);
         else placed = g_trade.SellStop(lots, entry, symbol, sl, tp, time_type, expiration, comment);
        }
      uint retcode = g_trade.ResultRetcode();
      if(placed && (retcode == TRADE_RETCODE_DONE || retcode == TRADE_RETCODE_PLACED || retcode == TRADE_RETCODE_DONE_PARTIAL))
         return true;
      if(attempt + 1 < MathMax(1, MaxRetries))
         Sleep(250 * (attempt + 1));
     }
   return false;
  }

string ExpiryReportKey(const ulong ticket)
  {
   return StringFormat("CTEXP_%I64d_%I64d_%I64d", AccountInfoInteger(ACCOUNT_LOGIN), MagicNumber, (long)ticket);
  }

void ReportExpiredOrder(const ulong ticket)
  {
   string key = ExpiryReportKey(ticket);
   if(GlobalVariableCheck(key))
      return;
   string body = StringFormat(
      "{\"ticket\":\"%I64d\",\"profit\":0.0,\"result\":\"EXPIRED\"}", (long)ticket);
   string response;
   if(HttpRequest("POST", "/api/ea/result", body, response))
      GlobalVariableSet(key, (double)TimeCurrent());
  }

void ExpirePendingOrders()
  {
   if(PendingOrderExpiryMinutes <= 0)
      return;
   datetime now = TimeCurrent();
   int lifetime = PendingOrderExpiryMinutes * 60;
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong ticket = OrderGetTicket(i);
      if(ticket == 0 || (long)OrderGetInteger(ORDER_MAGIC) != MagicNumber)
         continue;
      if(StringFind(OrderGetString(ORDER_COMMENT), "CTS:") != 0)
         continue;
      datetime setup_time = (datetime)OrderGetInteger(ORDER_TIME_SETUP);
      if(setup_time <= 0 || now - setup_time < lifetime)
         continue;
      long position_id = OrderGetInteger(ORDER_POSITION_ID);
      if(g_trade.OrderDelete(ticket) && g_trade.ResultRetcode() == TRADE_RETCODE_DONE)
        {
         Print("[TelegramSignalEA] pending order ", ticket, " expired after ", PendingOrderExpiryMinutes, " minutes");
         if(position_id <= 0)
            ReportExpiredOrder(ticket);
        }
      else
         Print("[TelegramSignalEA] could not expire pending order ", ticket, ": ", g_trade.ResultRetcodeDescription());
     }
  }

void ReportExpiredOrdersFromHistory()
  {
   datetime now = TimeCurrent();
   if(g_last_expiry_scan > 0 && now - g_last_expiry_scan < 30)
      return;
   g_last_expiry_scan = now;
   if(!HistorySelect(now - 30 * 24 * 60 * 60, now))
      return;
   for(int i = HistoryOrdersTotal() - 1; i >= 0; i--)
     {
      ulong ticket = HistoryOrderGetTicket(i);
      if(ticket == 0 || (long)HistoryOrderGetInteger(ticket, ORDER_MAGIC) != MagicNumber)
         continue;
      if((ENUM_ORDER_STATE)HistoryOrderGetInteger(ticket, ORDER_STATE) != ORDER_STATE_EXPIRED)
         continue;
      if(StringFind(HistoryOrderGetString(ticket, ORDER_COMMENT), "CTS:") != 0)
         continue;
      if(HistoryOrderGetInteger(ticket, ORDER_POSITION_ID) <= 0)
         ReportExpiredOrder(ticket);
     }
  }

void RejectSignal(const long signal_id, const string symbol, const string action, const string reason)
  {
   SaveReport(signal_id, 2, 0, 0.0, 0.0);
   SendReport(signal_id, "REJECTED", 0, symbol, action, 0.0, 0.0, reason);
   Print("[TelegramSignalEA] signal ", signal_id, " rejected: ", reason);
  }

void ReportLegOutcome(const long signal_id, const string symbol, const string action, const int leg,
                      const string status, const double lots, const string reason)
  {
   int state = status == "FAILED" ? 3 : 2;
   SaveReport(signal_id, state, 0, 0.0, lots, leg);
   SendReport(signal_id, status, 0, symbol, action, lots, 0.0, reason, leg);
   Print("[TelegramSignalEA] signal ", signal_id, " entry ", leg, " ", status, ": ", reason);
  }

string ZoneOrderType(const string action, const double entry, const double bid, const double ask, const double tick_size)
  {
   double tolerance = tick_size > 0.0 ? tick_size * 0.5 : 0.00000001;
   if(action == "BUY")
     {
      if(entry < ask - tolerance) return "LIMIT";
      if(entry > ask + tolerance) return "STOP";
      return "MARKET";
     }
   if(entry > bid + tolerance) return "LIMIT";
   if(entry < bid - tolerance) return "STOP";
   return "MARKET";
  }

bool ProcessOrderLeg(const long signal_id, const string symbol, const string action,
                     const string requested_type, const bool zone_order, const double requested_entry,
                     const double sl_input, const double tp_input, const int leg,
                     const double bid, const double ask)
  {
   int saved_state = SavedState(signal_id, leg);
   if(saved_state != 0)
     {
      RepeatSavedReport(signal_id, symbol, action, leg);
      return true;
     }

   long old_ticket = 0;
   double old_lots = 0.0;
   double old_price = 0.0;
   if(FindExistingSignalOrder(signal_id, old_ticket, old_lots, old_price, leg))
     {
      SaveReport(signal_id, 1, old_ticket, old_price, old_lots, leg);
      SendReport(signal_id, "EXECUTED", old_ticket, symbol, action, old_lots, old_price,
                 "Recovered existing order after restart", leg);
      return true;
     }

   string order_type = zone_order ? ZoneOrderType(action, NormalizePrice(symbol, requested_entry), bid, ask,
                                                   SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE)) : requested_type;
   if(order_type != "MARKET" && order_type != "LIMIT" && order_type != "STOP")
     {
      ReportLegOutcome(signal_id, symbol, action, leg, "REJECTED", 0.0, "Order type tidak valid");
      return false;
     }
   bool market = order_type == "MARKET";
   double current_price = action == "BUY" ? ask : bid;
   double entry = market ? 0.0 : NormalizePrice(symbol, requested_entry);
   if((market && current_price <= 0.0) || (!market && entry <= 0.0))
     {
      ReportLegOutcome(signal_id, symbol, action, leg, "REJECTED", 0.0, "Missing entry/current quote");
      return false;
     }
   if(market && requested_entry > 0.0 && current_price > 0.0 &&
      MathAbs(requested_entry - current_price) / current_price * 100.0 > MaxMarketDeviationPct)
     {
      ReportLegOutcome(signal_id, symbol, action, leg, "REJECTED", 0.0, "Market entry deviates too far from current price");
      return false;
     }

   double reference = market ? current_price : entry;
   double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
   double sl = sl_input;
   double tp = tp_input;
   if(UseDefaultSLTP && point > 0.0)
     {
      if(sl <= 0.0 && DefaultSLPoints > 0)
         sl = action == "BUY" ? reference - DefaultSLPoints * point : reference + DefaultSLPoints * point;
      if(tp <= 0.0 && DefaultTPPoints > 0)
         tp = action == "BUY" ? reference + DefaultTPPoints * point : reference - DefaultTPPoints * point;
     }
   sl = NormalizePrice(symbol, sl);
   tp = NormalizePrice(symbol, tp);
   if(!CheckPriceLevels(symbol, action, reference, sl, tp))
     {
      ReportLegOutcome(signal_id, symbol, action, leg, "REJECTED", 0.0, "SL/TP invalid or inside broker stops level");
      return false;
     }

   double lots = CalculateLots(symbol, reference, sl);
   if(lots <= 0.0)
     {
      ReportLegOutcome(signal_id, symbol, action, leg, "REJECTED", 0.0, "Lot size invalid or risk sizing requires SL");
      return false;
     }
   ENUM_ORDER_TYPE margin_type = action == "BUY" ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   if(!market && order_type == "LIMIT")
      margin_type = action == "BUY" ? ORDER_TYPE_BUY_LIMIT : ORDER_TYPE_SELL_LIMIT;
   if(!market && order_type == "STOP")
      margin_type = action == "BUY" ? ORDER_TYPE_BUY_STOP : ORDER_TYPE_SELL_STOP;
   if(!CheckMargin(margin_type, symbol, lots, reference))
     {
      ReportLegOutcome(signal_id, symbol, action, leg, "REJECTED", lots, "Insufficient free margin or margin calculation failed");
      return false;
     }

   if(!PlaceOrder(action, order_type, symbol, entry, sl, tp, lots, signal_id, leg))
     {
      string failure = StringFormat("Order failed: %s (%u)", g_trade.ResultRetcodeDescription(), g_trade.ResultRetcode());
      ReportLegOutcome(signal_id, symbol, action, leg, "FAILED", lots, failure);
      return false;
     }

   long ticket = (long)g_trade.ResultOrder();
   double fill_price = g_trade.ResultPrice();
   double fill_lots = g_trade.ResultVolume();
   if(ticket <= 0)
     {
      if(!FindExistingSignalOrder(signal_id, ticket, fill_lots, fill_price, leg) || ticket <= 0)
        {
         Print("[TelegramSignalEA] signal ", signal_id, " entry ", leg,
               " accepted but ticket is not available yet; will recover by order marker");
         return false;
        }
     }
   if(fill_price <= 0.0)
      fill_price = market ? current_price : entry;
   if(fill_lots <= 0.0)
      fill_lots = lots;
   SaveReport(signal_id, 1, ticket, fill_price, fill_lots, leg);
   SendReport(signal_id, "EXECUTED", ticket, symbol, action, fill_lots, fill_price,
              StringFormat("Order accepted at entry %s", DoubleToString(market ? fill_price : entry, (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS))), leg);
   Print("[TelegramSignalEA] signal ", signal_id, " entry ", leg, " executed ticket ", ticket,
         " at ", DoubleToString(fill_price, (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS)),
         " lots ", DoubleToString(fill_lots, 2));
   return true;
  }

void ProcessSignal(const string item)
  {
   long signal_id = JsonLong(item, "signal_id");
   if(signal_id <= 0)
      return;
   string action = JsonValue(item, "action");
   string order_type = JsonValue(item, "order_type");
   string symbol = ResolveSymbol(JsonValue(item, "symbol"));
   if(symbol == "") symbol = _Symbol;
   g_last_signal = StringFormat("%s %s #%I64d", action, symbol, signal_id);
   if(SavedState(signal_id, 0) != 0)
     {
      RepeatSavedReport(signal_id, symbol, action, 0);
      return;
     }

   double entry_low = JsonNumber(item, "entry_low");
   double entry_high = JsonNumber(item, "entry_high");
   bool has_low = entry_low > 0.0;
   bool has_high = entry_high > 0.0;
   bool zone_order = has_low && has_high;
   if(has_low != has_high)
     {
      RejectSignal(signal_id, symbol, action, "Entry zone requires both lower and upper prices");
      return;
     }
   if(zone_order && entry_low > entry_high)
     {
      double swap = entry_low;
      entry_low = entry_high;
      entry_high = swap;
     }
   if(zone_order && entry_low == entry_high)
     {
      RejectSignal(signal_id, symbol, action, "Entry zone prices must be different");
      return;
     }
   if(!zone_order && order_type == "AUTO")
     {
      RejectSignal(signal_id, symbol, action, "AUTO order requires an entry zone");
      return;
     }

   long created_epoch = JsonLong(item, "created_epoch");
   if(MaxSignalAgeSeconds > 0 && created_epoch > 0 && TimeGMT() - created_epoch > MaxSignalAgeSeconds)
     {
      RejectSignal(signal_id, symbol, action, "Signal expired");
      return;
     }
   if((action == "BUY" && !AllowBuy) || (action == "SELL" && !AllowSell) || (action != "BUY" && action != "SELL"))
     {
      RejectSignal(signal_id, symbol, action, "Action disabled or invalid");
      return;
     }
   if(!SymbolSelect(symbol, true) || !SymbolAllowed(symbol))
     {
      RejectSignal(signal_id, symbol, action, "Symbol unavailable or not allowed");
      return;
     }
   if(DemoMode)
     {
      SaveReport(signal_id, 4, 0, 0.0, 0.0);
      SendReport(signal_id, "DRY_RUN", 0, symbol, action, 0.0, 0.0, "EA DemoMode enabled; no order sent");
      g_signal_count++;
      return;
     }
   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) || !MQLInfoInteger(MQL_TRADE_ALLOWED))
     {
      RejectSignal(signal_id, symbol, action, "AutoTrading is disabled");
      return;
     }
   if(!CheckSpread(symbol))
     {
      RejectSignal(signal_id, symbol, action, "Spread exceeds MaxSpreadPoints");
      return;
     }

   double bid = SymbolInfoDouble(symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(symbol, SYMBOL_ASK);
   double sl = JsonNumber(item, "sl");
   double tp = zone_order ? FinalArrayNumber(JsonValue(item, "tp"), action) : FirstArrayNumber(JsonValue(item, "tp"));
   int order_count = zone_order ? 2 : 1;

   if(zone_order && AccountInfoInteger(ACCOUNT_MARGIN_MODE) != ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)
     {
      RejectSignal(signal_id, symbol, action, "Two-entry zone requires an MT5 hedging account");
      return;
     }

   int needed_orders = 0;
   for(int i = 0; i < order_count; i++)
     {
      int leg = zone_order ? i + 1 : 0;
      if(SavedState(signal_id, leg) == 0)
        {
         long existing_ticket = 0;
         double existing_lots = 0.0;
         double existing_price = 0.0;
         if(!FindExistingSignalOrder(signal_id, existing_ticket, existing_lots, existing_price, leg))
            needed_orders++;
        }
     }
   if(MaxOpenTrades > 0 && CountOpenTrades() + needed_orders > MaxOpenTrades)
     {
      RejectSignal(signal_id, symbol, action, "MaxOpenTrades limit does not allow all signal entries");
      return;
     }

   if(zone_order)
     {
      ProcessOrderLeg(signal_id, symbol, action, "AUTO", true, entry_low, sl, tp, 1, bid, ask);
      ProcessOrderLeg(signal_id, symbol, action, "AUTO", true, entry_high, sl, tp, 2, bid, ask);
     }
   else
     {
      ProcessOrderLeg(signal_id, symbol, action, order_type, false, JsonNumber(item, "entry"), sl, tp, 0, bid, ask);
     }
   g_signal_count++;
  }

void PollSignals()
  {
   string body;
   if(!HttpRequest("GET", "/api/ea/pending?limit=1", "", body))
      return;
   string item = FirstSignalObject(body);
   if(item == "")
      return;
   ProcessSignal(item);
  }

void SendHeartbeat()
  {
   string symbol = JsonEscape(_Symbol);
   string body = StringFormat(
      "{\"active\":true,\"terminal\":\"%s\",\"version\":\"0.5.0\",\"symbol\":\"%s\"}",
      JsonEscape(TerminalInfoString(TERMINAL_NAME)), symbol);
   string response;
   HttpRequest("POST", "/api/ea/heartbeat", body, response);
   g_last_heartbeat = TimeCurrent();
  }

bool PositionExistsByIdentifier(const long position_id)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket > 0 && (long)PositionGetInteger(POSITION_IDENTIFIER) == position_id)
         return true;
     }
   return false;
  }

void ReportClosedPosition(const long position_id, const ulong closing_deal)
  {
   string id_key = StringFormat("CTPOS_%I64d_%I64d_S", AccountInfoInteger(ACCOUNT_LOGIN), position_id);
   string ticket_key = StringFormat("CTPOS_%I64d_%I64d_T", AccountInfoInteger(ACCOUNT_LOGIN), position_id);
   if(!GlobalVariableCheck(id_key) || PositionExistsByIdentifier(position_id))
      return;
   long signal_id = (long)GlobalVariableGet(id_key);
   long ticket = (long)GlobalVariableGet(ticket_key);
   if(signal_id <= 0 || ticket <= 0 || !HistorySelectByPosition((ulong)position_id))
      return;
   double profit = 0.0;
   datetime close_time = TimeCurrent();
   for(int i = 0; i < HistoryDealsTotal(); i++)
     {
      ulong deal = HistoryDealGetTicket(i);
      if(deal == 0) continue;
      profit += HistoryDealGetDouble(deal, DEAL_PROFIT);
      profit += HistoryDealGetDouble(deal, DEAL_SWAP);
      profit += HistoryDealGetDouble(deal, DEAL_COMMISSION);
      datetime deal_time = (datetime)HistoryDealGetInteger(deal, DEAL_TIME);
      if(deal_time > close_time || i == 0) close_time = deal_time;
     }
   string result = MathAbs(profit) < 0.005 ? "BE" : profit > 0.0 ? "WIN" : "LOSS";
   string iso_close_time = TimeToString(close_time, TIME_DATE | TIME_SECONDS);
   StringReplace(iso_close_time, ".", "-");
   StringReplace(iso_close_time, " ", "T");
   string payload = StringFormat(
      "{\"ticket\":\"%I64d\",\"profit\":%.2f,\"result\":\"%s\",\"closed_at\":\"%s\"}",
      ticket, profit, result, iso_close_time);
   string response;
   if(HttpRequest("POST", "/api/ea/result", payload, response))
     {
      if(result == "WIN") g_wins++;
      if(result == "LOSS") g_losses++;
      GlobalVariableDel(id_key);
      GlobalVariableDel(ticket_key);
     }
   Print("[TelegramSignalEA] position ", position_id, " closed: ", result, " profit ", DoubleToString(profit, 2));
  }

void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
  {
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD || trans.deal == 0 || !HistoryDealSelect(trans.deal))
      return;
   long position_id = (long)HistoryDealGetInteger(trans.deal, DEAL_POSITION_ID);
   ENUM_DEAL_ENTRY entry = (ENUM_DEAL_ENTRY)HistoryDealGetInteger(trans.deal, DEAL_ENTRY);
   if(entry == DEAL_ENTRY_IN || entry == DEAL_ENTRY_INOUT)
     {
      string comment = HistoryDealGetString(trans.deal, DEAL_COMMENT);
      if(StringFind(comment, "CTS:") == 0)
        {
         long signal_id = SignalIdFromComment(comment);
         long ticket = (long)HistoryDealGetInteger(trans.deal, DEAL_ORDER);
         GlobalVariableSet(StringFormat("CTPOS_%I64d_%I64d_S", AccountInfoInteger(ACCOUNT_LOGIN), position_id), signal_id);
         GlobalVariableSet(StringFormat("CTPOS_%I64d_%I64d_T", AccountInfoInteger(ACCOUNT_LOGIN), position_id), (double)ticket);
        }
     }
   if(entry == DEAL_ENTRY_OUT || entry == DEAL_ENTRY_OUT_BY || entry == DEAL_ENTRY_INOUT)
      ReportClosedPosition(position_id, trans.deal);
  }

void UpdatePanel()
  {
   int closed = g_wins + g_losses;
   double winrate = closed > 0 ? (double)g_wins / closed * 100.0 : 0.0;
   Comment("TelegramSignalEA 0.5.0\n",
           "Backend: ", g_connection_status, "\n",
           "Mode: ", DemoMode ? "DEMO / DRY RUN" : "LIVE", "\n",
           "Signals this session: ", g_signal_count, "\n",
           "Win / Loss: ", g_wins, " / ", g_losses, " (", DoubleToString(winrate, 1), "%)\n",
           "Last signal: ", g_last_signal);
  }

int OnInit()
  {
   if(PollIntervalMs < 100)
     {
      Print("[TelegramSignalEA] PollIntervalMs must be >= 100");
      return INIT_PARAMETERS_INCORRECT;
     }
   if(PendingOrderExpiryMinutes < 1)
     {
      Print("[TelegramSignalEA] PendingOrderExpiryMinutes must be >= 1");
      return INIT_PARAMETERS_INCORRECT;
     }
   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) || !MQLInfoInteger(MQL_TRADE_ALLOWED))
      Print("[TelegramSignalEA] AutoTrading is off; signals will be rejected unless DemoMode is active.");
   EventSetMillisecondTimer(PollIntervalMs);
   SendHeartbeat();
   UpdatePanel();
   Print("[TelegramSignalEA] initialized; add ServerURL to MT5 WebRequest allow-list");
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   Comment("");
   Print("[TelegramSignalEA] stopped, reason ", reason);
  }

void OnTimer()
  {
   ExpirePendingOrders();
   ReportExpiredOrdersFromHistory();
   PollSignals();
   if(TimeCurrent() - g_last_heartbeat >= 30)
      SendHeartbeat();
   UpdatePanel();
  }
