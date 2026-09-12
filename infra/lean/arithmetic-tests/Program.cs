using System.Numerics;
using System.Text.Json;
using FactorForge.LeanExecution;

// Exercise the production arithmetic source independently of LEAN and Python scoring.
var inputs = new Dictionary<string, ExactRatio> { ["x"] = new(2, 3), ["y"] = new(1, 4) };
foreach (var (op, n, d) in new[] { ("add", 11, 12), ("subtract", 5, 12), ("multiply", 1, 6), ("divide", 8, 3) })
{
    using var node = JsonDocument.Parse(JsonSerializer.Serialize(new
    {
        kind = op, left = new { kind = "input", name = "x" }, right = new { kind = "input", name = "y" }
    }));
    if (ExactRatio.Evaluate(node.RootElement, inputs) != new ExactRatio(n, d)) throw new Exception(op);
}
foreach (var (text, n, d) in new[] { ("-1.25e2", -125, 1), ("1e-3", 1, 1000), (".25", 1, 4) })
    if (ExactRatio.Parse(text) != new ExactRatio(n, d)) throw new Exception("Decimal conversion");
var exact = ExactRatio.Parse("0.10000000000000000000001");
if (exact != new ExactRatio(BigInteger.Parse("10000000000000000000001"), BigInteger.Parse("100000000000000000000000")))
    throw new Exception("Precision loss");
if (new ExactRatio(1, 3).CompareTo(new ExactRatio(333333333, 1000000000)) <= 0)
    throw new Exception("Comparison rounding");
var rejected = false;
try { _ = new ExactRatio(1, 0); } catch (InvalidOperationException) { rejected = true; }
if (!rejected) throw new Exception("Division by zero accepted");
rejected = false;
try { _ = new ExactRatio(BigInteger.One << 4097, 1); } catch (InvalidOperationException) { rejected = true; }
if (!rejected) throw new Exception("Bit budget bypassed");
foreach (var kind in new[] { "positive", "negative" })
{
    using var node = JsonDocument.Parse(JsonSerializer.Serialize(new { kind, value = new { kind = "input", name = "x" } }));
    if (ExactRatio.Evaluate(node.RootElement, inputs) != new ExactRatio(kind == "positive" ? 2 : -2, 3))
        throw new Exception("Unary operator");
}
rejected = false;
try { _ = ExactRatio.Parse("1.2.3"); } catch (InvalidOperationException) { rejected = true; }
if (!rejected) throw new Exception("Malformed number accepted");
Console.WriteLine("14 arithmetic and boundary checks passed.");
