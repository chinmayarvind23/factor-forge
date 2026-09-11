using System.Globalization;
using System.Text.Json;
using QuantConnect;
using QuantConnect.Algorithm;
using QuantConnect.Data;
using QuantConnect.Data.Market;
using QuantConnect.Orders;
using QuantConnect.Orders.Fees;
using QuantConnect.Securities;

namespace FactorForge.LeanSpike;

/// <summary>One original seeded equity fixture measures actual LEAN portfolio state.</summary>
public sealed class SeededEquityAlgorithm : QCAlgorithm
{
    private Symbol _symbol = QuantConnect.Symbol.Empty;
    private readonly List<DateTime> _clocks = new();
    private readonly List<decimal> _prices = new();
    private int _seen;

    /// <summary>Seed explicit inventory and first price without submitting an order.</summary>
    public override void Initialize()
    {
        if (!File.Exists("/.dockerenv") || Environment.GetEnvironmentVariable("FACTORFORGE_LEAN_SPIKE") != "1")
            throw new InvalidOperationException("Owned LEAN spike container required.");
        using var source = JsonDocument.Parse(File.ReadAllBytes("/input/source.json"));
        var root = source.RootElement;
        var holding = root.GetProperty("holdings")[0];
        decimal quantity = Exact(holding.GetProperty("quantity"));
        decimal average = Exact(holding.GetProperty("average_price_usd"));
        decimal cash = Exact(root.GetProperty("cash_usd"));
        foreach (var row in root.GetProperty("snapshots").EnumerateArray())
        {
            _clocks.Add(DateTime.ParseExact(row.GetProperty("at").GetString()!,
                "yyyy-MM-dd'T'HH:mm:ss'Z'", CultureInfo.InvariantCulture,
                DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal));
            _prices.Add(Exact(row.GetProperty("prices")[0].GetProperty("price_usd")));
        }
        Require(quantity == 10m && average == 100m && cash == 0m && _clocks.Count == 3,
            "Original source inventory changed.");
        SetTimeZone(TimeZones.Utc);
        SetStartDate(2024, 4, 29);
        SetEndDate(2024, 5, 1);
        SetCash(cash);
        SetBenchmark(_ => 1m);
        SetRiskFreeInterestRateModel(new ConstantRiskFreeRateInterestRateModel(0m));
        MarketHoursDatabase.SetEntryAlwaysOpen(Market.USA, "FFA", SecurityType.Equity, TimeZones.Utc);
        SymbolPropertiesDatabase.SetEntry(Market.USA, "FFA", SecurityType.Equity,
            new SymbolProperties("Original conditional fixture", "USD", 1m, 0.0001m, 1m, "FFA"));
        var equity = AddEquity("FFA", Resolution.Tick, Market.USA, fillForward: false,
            leverage: 1m, extendedMarketHours: false, dataNormalizationMode: DataNormalizationMode.Raw);
        _symbol = equity.Symbol;
        equity.SetFeeModel(new ConstantFeeModel(0m));
        equity.SetMarketPrice(new Tick
        {
            Symbol = _symbol, Time = _clocks[0], Value = _prices[0], Quantity = 1m,
            TickType = TickType.Trade
        });
        equity.Holdings.SetHoldings(average, quantity);
        Portfolio.InvalidateTotalPortfolioValue();
    }

    /// <summary>Observe NAV after LEAN's feed updates prices; never assign the expected NAV.</summary>
    public override void OnData(Slice slice)
    {
        if (!slice.Ticks.TryGetValue(_symbol, out var ticks)) return;
        var trades = ticks.Where(tick => tick.TickType == TickType.Trade).ToList();
        if (trades.Count == 0) return;
        Require(_seen < _clocks.Count && trades.Count == 1 && UtcTime == _clocks[_seen],
            "Unexpected tick inventory or clock.");
        Require(trades[0].Value == _prices[_seen] && Securities[_symbol].Price == _prices[_seen],
            "LEAN price differs from original input.");
        Require(Portfolio[_symbol].Quantity == 10m && Portfolio.Cash == 0m,
            "Seeded holdings or cash changed.");
        Console.WriteLine("FACTORFORGE_NAV:" + JsonSerializer.Serialize(new
        {
            at = UtcTime.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", CultureInfo.InvariantCulture),
            security_id = "SEC-A",
            lean_security_type = Securities[_symbol].Type.ToString(),
            price_usd = Securities[_symbol].Price.ToString(CultureInfo.InvariantCulture),
            quantity = Portfolio[_symbol].Quantity.ToString(CultureInfo.InvariantCulture),
            cash_usd = Portfolio.Cash.ToString(CultureInfo.InvariantCulture),
            nav_usd = Portfolio.TotalPortfolioValue.ToString(CultureInfo.InvariantCulture)
        }));
        _seen++;
    }

    /// <summary>The seeded profile has no order path, including unexpected engine orders.</summary>
    public override void OnOrderEvent(OrderEvent orderEvent)
    {
        throw new InvalidOperationException("Orders are outside the seeded-price spike.");
    }

    /// <summary>Missing rows, fills or fees fail the run rather than shortening its denominator.</summary>
    public override void OnEndOfAlgorithm()
    {
        Require(_seen == 3 && !Transactions.GetOrderTickets().Any() && Portfolio.TotalFees == 0m,
            "Incomplete observations or unexpected order accounting.");
        Console.WriteLine("FACTORFORGE_DONE:3");
    }

    /// <summary>Invariant decimal parsing retains exact authored numbers and exponent notation.</summary>
    private static decimal Exact(JsonElement value) =>
        decimal.Parse(value.GetString()!, NumberStyles.Float, CultureInfo.InvariantCulture);

    /// <summary>Explicit guards stay enabled independently of compiler assertion settings.</summary>
    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }
}

/// <summary>The original valuation fixture has no SPY dataset for optional strategy analysis.</summary>
public sealed class OriginalFixtureResultHandler : QuantConnect.Lean.Engine.Results.BacktestingResultHandler
{
    /// <summary>Keep normal result storage while disabling unrelated SPY-history analysis.</summary>
    public OriginalFixtureResultHandler() => RunResultsAnalysis = false;
}
