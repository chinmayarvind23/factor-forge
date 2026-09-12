using System.Globalization;
using System.Numerics;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace FactorForge.LeanExecution;

/// <summary>Bounded exact arithmetic keeps formula ranking independent of Python's evaluator.</summary>
public readonly record struct ExactRatio : IComparable<ExactRatio>
{
    public BigInteger Numerator { get; }
    public BigInteger Denominator { get; }

    /// <summary>Canonical reduction preserves signs and limits intermediate arithmetic growth.</summary>
    public ExactRatio(BigInteger numerator, BigInteger denominator)
    {
        if (denominator.IsZero) throw new InvalidOperationException("Formula division by zero.");
        if (denominator.Sign < 0) { numerator = -numerator; denominator = -denominator; }
        var gcd = BigInteger.GreatestCommonDivisor(numerator, denominator);
        Numerator = numerator / gcd;
        Denominator = denominator / gcd;
        if (Numerator.GetBitLength() > 4096 || Denominator.GetBitLength() > 4096)
            throw new InvalidOperationException("Formula arithmetic exceeds bit budget.");
    }

    /// <summary>Read finite decimal source text without binary floating-point conversion.</summary>
    public static ExactRatio Parse(string text)
    {
        if (text.Length > 128 || !Regex.IsMatch(text, @"\A[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\z", RegexOptions.CultureInvariant, TimeSpan.FromSeconds(1)))
            throw new InvalidOperationException("Invalid source number.");
        var parts = text.ToLowerInvariant().Split('e');
        if (parts.Length > 2) throw new InvalidOperationException("Invalid source exponent.");
        var exponent = parts.Length == 2 ? int.Parse(parts[1], CultureInfo.InvariantCulture) : 0;
        if (Math.Abs((long)exponent) > 1000) throw new InvalidOperationException("Source exponent exceeds budget.");
        var dot = parts[0].IndexOf('.');
        var scale = (dot < 0 ? 0 : parts[0].Length - dot - 1) - exponent;
        var numerator = BigInteger.Parse(parts[0].Replace(".", ""), CultureInfo.InvariantCulture);
        return scale >= 0 ? new(numerator, BigInteger.Pow(10, scale)) : new(numerator * BigInteger.Pow(10, -scale), 1);
    }

    /// <summary>Cross products compare normalized rational values without rounding score ties.</summary>
    public int CompareTo(ExactRatio other) => (Numerator * other.Denominator).CompareTo(other.Numerator * Denominator);

    /// <summary>Interpret only serialized arithmetic nodes within a fixed recursion budget.</summary>
    public static ExactRatio Evaluate(JsonElement node, IReadOnlyDictionary<string, ExactRatio> inputs, int depth = 0)
    {
        if (depth > 24) throw new InvalidOperationException("Formula tree exceeds depth budget.");
        var kind = node.GetProperty("kind").GetString();
        if (kind == "input") return inputs[node.GetProperty("name").GetString()!];
        if (kind == "number") return new(BigInteger.Parse(node.GetProperty("numerator").GetString()!, CultureInfo.InvariantCulture), BigInteger.Parse(node.GetProperty("denominator").GetString()!, CultureInfo.InvariantCulture));
        if (kind is "negative" or "positive")
        {
            var value = Evaluate(node.GetProperty("value"), inputs, depth + 1);
            return new(kind == "negative" ? -value.Numerator : value.Numerator, value.Denominator);
        }
        var left = Evaluate(node.GetProperty("left"), inputs, depth + 1);
        var right = Evaluate(node.GetProperty("right"), inputs, depth + 1);
        return kind switch
        {
            "add" => new(left.Numerator * right.Denominator + right.Numerator * left.Denominator, left.Denominator * right.Denominator),
            "subtract" => new(left.Numerator * right.Denominator - right.Numerator * left.Denominator, left.Denominator * right.Denominator),
            "multiply" => new(left.Numerator * right.Numerator, left.Denominator * right.Denominator),
            "divide" => new(left.Numerator * right.Denominator, left.Denominator * right.Numerator),
            _ => throw new InvalidOperationException("Unsupported formula operator.")
        };
    }
}
