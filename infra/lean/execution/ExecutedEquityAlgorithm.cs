using System.Globalization;
using System.Text.Json;
using QuantConnect;
using QuantConnect.Algorithm;
using QuantConnect.Data;
using QuantConnect.Orders;
using QuantConnect.Orders.Fees;
using QuantConnect.Securities;

namespace FactorForge.LeanExecution;

/// <summary>Execute a separately declared original long/short fixture in the actual LEAN engine.</summary>
public sealed class ExecutedEquityAlgorithm : QCAlgorithm
{
    private readonly Dictionary<string, Symbol> _symbols = new();
    private readonly List<DateTime> _clocks = new();
    private DateTime _formation, _entry, _exit;
    private string _long = "", _short = "";
    private decimal _cash, _rate;
    private int _seen, _fills;

    /// <summary>Read only source observations and declared policy; no holdings or NAV are seeded.</summary>
    public override void Initialize()
    {
        Require(File.Exists("/.dockerenv") && Environment.GetEnvironmentVariable("FACTORFORGE_LEAN_EXECUTION") == "1", "Owned execution container required.");
        using var source = JsonDocument.Parse(File.ReadAllBytes("/input/source.json"));
        var root = source.RootElement;
        Require(root.GetProperty("schema_version").GetString() == "original-lean-execution-v1", "Unsupported source.");
        _cash = Exact(root.GetProperty("initial_cash_usd"));
        var strategy = root.GetProperty("strategy");
        Require(strategy.GetProperty("formula").GetString() == "score", "Unsupported formula.");
        _formation = Clock("2024-04-30T20:00:00Z");
        _entry = Clock("2024-05-01T13:30:00Z");
        _exit = Clock("2024-05-16T20:00:00Z");
        _rate = (strategy.GetProperty("costs").GetProperty("commission_bps").GetDecimal()
            + strategy.GetProperty("costs").GetProperty("slippage_bps").GetDecimal()) / 10000m;
        var scores = root.GetProperty("signals").GetProperty("facts").EnumerateArray()
            .Where(row => row.GetProperty("concept").GetString() == "original-score"
                && Clock(row.GetProperty("available_at").GetString()!) <= _formation)
            .ToDictionary(row => row.GetProperty("security_id").GetString()!, row => Exact(row.GetProperty("value")));
        Require(scores.Count == 2 && scores["A"] != scores["B"], "Two distinct known signals required.");
        _long = scores.OrderByDescending(row => row.Value).First().Key;
        _short = scores.OrderBy(row => row.Value).First().Key;
        var grant = root.GetProperty("market").GetProperty("borrow_grants")[0];
        Require(grant.GetProperty("security_id").GetString() == _short
            && Clock(grant.GetProperty("available_at").GetString()!) <= _formation
            && Clock(grant.GetProperty("valid_through").GetString()!) >= _exit,
            "Declared short permission unavailable.");
        _clocks.AddRange(root.GetProperty("market").GetProperty("quotes").EnumerateArray()
            .Select(row => Clock(row.GetProperty("observed_at").GetString()!)).Distinct().Order());
        SetTimeZone(TimeZones.Utc);
        SetStartDate(2024, 4, 30);
        SetEndDate(2024, 5, 16);
        SetCash(_cash);
        SetBenchmark(_ => 1m);
        SetRiskFreeInterestRateModel(new ConstantRiskFreeRateInterestRateModel(0m));
        foreach (var (id, ticker) in new[] { ("A", "FFA"), ("B", "FFB") })
        {
            MarketHoursDatabase.SetEntryAlwaysOpen(Market.USA, ticker, SecurityType.Equity, TimeZones.Utc);
            SymbolPropertiesDatabase.SetEntry(Market.USA, ticker, SecurityType.Equity,
                new SymbolProperties("Original execution fixture", "USD", 1m, 0.0001m, 1m, ticker));
            var equity = AddEquity(ticker, Resolution.Tick, Market.USA, fillForward: false,
                leverage: 2m, extendedMarketHours: false, dataNormalizationMode: DataNormalizationMode.Raw);
            equity.SetBuyingPowerModel(new SecurityMarginModel(2m, 0m));
            equity.SetFeeModel(new OriginalCostModel(_rate));
            _symbols[id] = equity.Symbol;
        }
    }

    /// <summary>Submit actual orders at the authored open/close and read LEAN's resulting NAV.</summary>
    public override void OnData(Slice slice)
    {
        if (!_symbols.Values.All(symbol => slice.Ticks.ContainsKey(symbol))) return;
        Require(_seen < _clocks.Count && UtcTime == _clocks[_seen], "Unexpected observation clock.");
        if (UtcTime == _entry)
        {
            decimal postFeeNav = _cash / (1m + 2m * _rate);
            decimal longQuantity = postFeeNav / Securities[_symbols[_long]].Price;
            decimal shortQuantity = postFeeNav / Securities[_symbols[_short]].Price;
            Require(longQuantity == decimal.Truncate(longQuantity) && shortQuantity == decimal.Truncate(shortQuantity), "Exact integer shares required.");
            MarketOrder(_symbols[_long], longQuantity);
            MarketOrder(_symbols[_short], -shortQuantity);
        }
        if (UtcTime == _exit)
        {
            foreach (var symbol in _symbols.Values)
                MarketOrder(symbol, -Portfolio[symbol].Quantity);
        }
        if (UtcTime.Hour == 20)
            Console.WriteLine("FACTORFORGE_EXECUTION_NAV:" + JsonSerializer.Serialize(new
            {
                at = UtcTime.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", CultureInfo.InvariantCulture),
                nav_usd = Portfolio.TotalPortfolioValue.ToString(CultureInfo.InvariantCulture),
                cash_usd = Portfolio.Cash.ToString(CultureInfo.InvariantCulture),
                fees_usd = Portfolio.TotalFees.ToString(CultureInfo.InvariantCulture)
            }));
        _seen++;
    }

    /// <summary>Preserve actual filled orders and reject invalid orders instead of fabricating fills.</summary>
    public override void OnOrderEvent(OrderEvent orderEvent)
    {
        Require(orderEvent.Status != OrderStatus.Invalid, "LEAN rejected an order.");
        if (orderEvent.Status != OrderStatus.Filled) return;
        _fills++;
        Console.WriteLine("FACTORFORGE_EXECUTION_FILL:" + JsonSerializer.Serialize(new
        {
            symbol = orderEvent.Symbol.Value,
            quantity = orderEvent.FillQuantity.ToString(CultureInfo.InvariantCulture),
            price_usd = orderEvent.FillPrice.ToString(CultureInfo.InvariantCulture),
            fee_usd = orderEvent.OrderFee.Value.Amount.ToString(CultureInfo.InvariantCulture)
        }));
    }

    /// <summary>Require a complete observation and order inventory with no remaining holdings.</summary>
    public override void OnEndOfAlgorithm()
    {
        Require(_seen == _clocks.Count && _fills == 4 && !Portfolio.Invested, "Incomplete execution.");
        Console.WriteLine("FACTORFORGE_EXECUTION_DONE:" + _seen);
    }

    /// <summary>Keep decimal inputs exact across the JSON and .NET boundary.</summary>
    private static decimal Exact(JsonElement value) => decimal.Parse(value.GetString()!, NumberStyles.Float, CultureInfo.InvariantCulture);
    /// <summary>Translate explicit UTC source clocks without exchange-time inference.</summary>
    private static DateTime Clock(string value) => DateTime.Parse(value, CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal);
    /// <summary>Admission and completeness checks remain enabled in release builds.</summary>
    private static void Require(bool condition, string message) { if (!condition) throw new InvalidOperationException(message); }
}

/// <summary>The Python profile charges commission and slippage as explicit notional costs.</summary>
public sealed class OriginalCostModel(decimal rate) : FeeModel
{
    /// <summary>Use LEAN's current raw security price and actual order quantity, not expected NAV.</summary>
    public override OrderFee GetOrderFee(OrderFeeParameters parameters) =>
        new(new CashAmount(parameters.Order.AbsoluteQuantity * parameters.Security.Price * rate, "USD"));
}

/// <summary>Keep stored engine results without an unrelated SPY-history analysis.</summary>
public sealed class OriginalFixtureResultHandler : QuantConnect.Lean.Engine.Results.BacktestingResultHandler
{
    /// <summary>The fixture has no upstream benchmark dataset.</summary>
    public OriginalFixtureResultHandler() => RunResultsAnalysis = false;
}
