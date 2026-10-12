using System.Globalization;

if (args.Length == 1 && args[0] == "read-stdin")
{
    var input = await Console.In.ReadToEndAsync();

    Console.Write(input.Length == 0 ? "EOF" : input);

    return 0;
}

if (args.Length == 2 && args[0] == "print-env")
{
    Console.Write(Environment.GetEnvironmentVariable(args[1]) ?? string.Empty);

    return 0;
}

if (args.Length == 2 && args[0] == "emit-stdout-hex")
{
    await using var output = Console.OpenStandardOutput();
    await output.WriteAsync(Convert.FromHexString(args[1]));

    return 0;
}

if (args.Length == 2 && args[0] == "emit-stderr-hex")
{
    await using var error = Console.OpenStandardError();
    await error.WriteAsync(Convert.FromHexString(args[1]));

    return 1;
}

if (args.Length == 1 && args[0] == "emit-large-invalid-stdout")
{
    var bytes = new byte[2 * 1024 * 1024];
    Array.Fill(bytes, (byte)'A');
    bytes[0] = 0xFF;

    await using var output = Console.OpenStandardOutput();
    await output.WriteAsync(bytes);

    return 0;
}

if (args.Length != 1)
{
    return 2;
}

var pidFile = args[0];
var temporaryPidFile = pidFile + ".tmp";

await File.WriteAllTextAsync(
    temporaryPidFile,
    Environment.ProcessId.ToString(CultureInfo.InvariantCulture)
);

File.Move(temporaryPidFile, pidFile, overwrite: true);

await Task.Delay(Timeout.InfiniteTimeSpan);

return 0;
