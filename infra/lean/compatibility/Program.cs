using System.IO.Compression;
using System.Text;
using System.Text.Json;
using LeanCompression = QuantConnect.Compression;

/// <summary>Original compression fixtures exercise the patched dependency without a strategy.</summary>
internal static class Program
{
    private static readonly List<object> Results = new();
    private static readonly string Scratch = "/scratch/compatibility";
    private static readonly byte[] PriceBytes = Encoding.UTF8.GetBytes("price\n100\n102\n104\n");

    /// <summary>Refuse accidental host execution and report every original case independently.</summary>
    private static int Main()
    {
        if (Environment.GetEnvironmentVariable("FACTORFORGE_LEAN_COMPAT") != "1" ||
            !File.Exists("/.dockerenv"))
            throw new InvalidOperationException("This diagnostic requires its owned container.");
        Directory.CreateDirectory(Scratch);
        byte[] original = Archive(new Dictionary<string, byte[]>
        {
            ["prices.csv"] = PriceBytes,
            ["notes/label.txt"] = Encoding.UTF8.GetBytes("fixture π\n")
        });
        string archivePath = Path.Combine(Scratch, "original.zip");
        File.WriteAllBytes(archivePath, original);
        int failures = 0;
        failures += Check("stream-price-bytes", () =>
            Require(ReadEntry(original, "prices.csv").SequenceEqual(PriceBytes)));
        failures += Check("stream-unicode-entry", () =>
            Require(Encoding.UTF8.GetString(ReadEntry(original, "notes/label.txt")) == "fixture π\n"));
        failures += Check("file-reader-case-insensitive-name", () =>
        {
            using var reader = LeanCompression.Unzip(archivePath, "PRICES.CSV", out var zip);
            using (zip) Require(reader != null && reader.ReadToEnd() == Encoding.UTF8.GetString(PriceBytes));
        });
        failures += Check("missing-entry-is-null", () =>
        {
            using var input = new MemoryStream(original);
            using var stream = LeanCompression.UnzipStream(input, out var zip, "missing.csv");
            using (zip) Require(stream == null);
        });
        failures += Check("lean-writer-independent-reader", () =>
        {
            string first = Path.Combine(Scratch, "first.txt");
            string second = Path.Combine(Scratch, "second.txt");
            File.WriteAllText(first, "alpha\n", new UTF8Encoding(false));
            File.WriteAllText(second, "beta\n", new UTF8Encoding(false));
            string output = Path.Combine(Scratch, "lean-written.zip");
            LeanCompression.ZipFiles(output, new[] { first, second });
            using var zip = System.IO.Compression.ZipFile.OpenRead(output);
            Require(zip.Entries.Count == 2);
            using var a = new StreamReader(zip.GetEntry("first.txt")!.Open());
            using var b = new StreamReader(zip.GetEntry("second.txt")!.Open());
            Require(a.ReadToEnd() == "alpha\n" && b.ReadToEnd() == "beta\n");
        });
        failures += Check("fork-writer-independent-reader", () =>
        {
            string output = Path.Combine(Scratch, "fork-written.zip");
            using (var zip = new Ionic.Zip.ZipFile())
            {
                zip.AddEntry("prices.csv", PriceBytes);
                zip.Save(output);
            }
            using var read = System.IO.Compression.ZipFile.OpenRead(output);
            using var payload = read.GetEntry("prices.csv")!.Open();
            using var copy = new MemoryStream();
            payload.CopyTo(copy);
            Require(copy.ToArray().SequenceEqual(PriceBytes));
        });
        failures += Check("malformed-stream-rejected", () =>
        {
            bool rejected = false;
            try { ReadEntry(new byte[] { 1, 2, 3, 4 }, "prices.csv"); }
            catch (Ionic.Zip.ZipException) { rejected = true; }
            Require(rejected);
        });
        failures += Check("truncated-central-directory-rejected", () =>
        {
            bool rejected = false;
            try { ReadEntry(original[..12], "prices.csv"); }
            catch (Ionic.Zip.ZipException) { rejected = true; }
            Require(rejected);
        });
        foreach (string entry in new[] { "../canary.txt", "../sibling/escape.txt", "..\\canary.txt" })
        {
            string captured = entry;
            failures += Check("extract-boundary-" + captured, () => ExtractionBoundary(captured));
        }
        Console.WriteLine(JsonSerializer.Serialize(new
        {
            schema_version = "original-lean-zip-compatibility-v1",
            strategy_executed = false,
            cases = Results,
            failed = failures
        }));
        return failures == 0 ? 0 : 1;
    }

    /// <summary>Use the framework ZIP writer as an independent source of original bytes.</summary>
    private static byte[] Archive(Dictionary<string, byte[]> entries)
    {
        using var result = new MemoryStream();
        using (var zip = new ZipArchive(result, ZipArchiveMode.Create, true, Encoding.UTF8))
            foreach (var item in entries)
            {
                using var output = zip.CreateEntry(item.Key).Open();
                output.Write(item.Value);
            }
        return result.ToArray();
    }

    /// <summary>Read a small original payload through LEAN's public Ionic-dependent API.</summary>
    private static byte[] ReadEntry(byte[] archive, string entry)
    {
        using var input = new MemoryStream(archive);
        using var stream = LeanCompression.UnzipStream(input, out var zip, entry);
        using (zip)
        {
            if (stream is null) throw new InvalidOperationException("Expected original entry is missing.");
            using var output = new MemoryStream();
            stream.CopyTo(output);
            return output.ToArray();
        }
    }

    /// <summary>Observe rejection or safe normalization while preserving an outside canary.</summary>
    private static void ExtractionBoundary(string entry)
    {
        string root = Path.Combine(Scratch, Guid.NewGuid().ToString("N"));
        string destination = Path.Combine(root, "sibling-base");
        Directory.CreateDirectory(destination);
        string canary = Path.Combine(root, "canary.txt");
        File.WriteAllText(canary, "unchanged", new UTF8Encoding(false));
        using var input = new MemoryStream(Archive(new Dictionary<string, byte[]>
        {
            [entry] = Encoding.UTF8.GetBytes("unexpected")
        }));
        using var zip = Ionic.Zip.ZipFile.Read(input);
        try { zip.ExtractAll(destination, Ionic.Zip.ExtractExistingFileAction.OverwriteSilently); }
        catch (IOException) { }
        Require(File.ReadAllText(canary) == "unchanged");
        Require(!File.Exists(Path.Combine(root, "sibling", "escape.txt")));
        Require(Directory.EnumerateFiles(root, "*", SearchOption.AllDirectories)
            .All(path => path == canary || path.StartsWith(destination + Path.DirectorySeparatorChar,
                StringComparison.Ordinal)));
    }

    /// <summary>Keep failed compatibility cases visible without stopping later independent probes.</summary>
    private static int Check(string name, Action action)
    {
        try { action(); Results.Add(new { name, passed = true }); return 0; }
        catch (Exception exception)
        {
            string detail = exception.Message == "Expected original entry is missing."
                ? "missing_original_entry"
                : exception.Message == "Original ZIP compatibility check failed."
                    ? "assertion_false" : "library_exception";
            Results.Add(new { name, passed = false, error_type = exception.GetType().Name, detail });
            return 1;
        }
    }

    /// <summary>Use an explicit failure signal instead of assertion settings that builds can omit.</summary>
    private static void Require(bool condition)
    {
        if (!condition) throw new InvalidOperationException("Original ZIP compatibility check failed.");
    }
}
