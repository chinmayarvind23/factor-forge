using System.Globalization;

namespace FactorForge.LeanExecution;

/// <summary>Independent single-entry sizing consumes capital, raw prices and declared policy only.</summary>
public static class EntrySizing
{
    /// <summary>Use rational division before truncation so decimal rounding cannot cross a share boundary.</summary>
    public static (decimal Long, decimal Short) Compute(decimal cash, decimal rate,
        decimal longPrice, decimal shortPrice, string policy)
    {
        if (cash <= 0m || rate < 0m || longPrice <= 0m || shortPrice <= 0m
            || policy is not ("exact_terminating_decimal_18_v1" or "whole_shares_toward_zero_v1"))
            throw new InvalidOperationException("Invalid entry sizing input.");
        var equity = ExactRatio.Parse(cash.ToString(CultureInfo.InvariantCulture));
        var divisor = ExactRatio.Parse((1m + 2m * rate).ToString(CultureInfo.InvariantCulture));
        // The fresh two-sleeve portfolio has the closed-form ideal NAV cash/(1+2*rate).
        decimal Quantity(decimal price)
        {
            var mark = ExactRatio.Parse(price.ToString(CultureInfo.InvariantCulture));
            var ratio = new ExactRatio(equity.Numerator * divisor.Denominator * mark.Denominator,
                equity.Denominator * divisor.Numerator * mark.Numerator);
            if (policy == "exact_terminating_decimal_18_v1" && ratio.Denominator != 1)
                throw new InvalidOperationException("Exact integer shares required.");
            return checked((decimal)(ratio.Numerator / ratio.Denominator));
        }
        var longQuantity = Quantity(longPrice);
        var shortQuantity = Quantity(shortPrice);
        var longNotional = checked(longQuantity * longPrice);
        var shortNotional = checked(shortQuantity * shortPrice);
        var actualNav = checked(cash - (longNotional + shortNotional) * rate);
        if (longQuantity <= 0m || shortQuantity <= 0m || actualNav <= 0m
            || Math.Max(longNotional, shortNotional) > actualNav)
            throw new InvalidOperationException("Rounded entry is not funded.");
        return (longQuantity, shortQuantity);
    }
}
