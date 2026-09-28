if (args.Length == 1 &&
    args[0] == "read-stdin")
{
    var input =
        await Console.In.ReadToEndAsync();

    Console.Write(
        input.Length == 0
            ? "EOF"
            : input);

    return 0;
}

if (args.Length == 2 &&
    args[0] == "print-env")
{
    Console.Write(
        Environment.GetEnvironmentVariable(args[1]) ??
        string.Empty);

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
    Environment.ProcessId.ToString());

File.Move(
    temporaryPidFile,
    pidFile,
    overwrite: true);

await Task.Delay(Timeout.InfiniteTimeSpan);

return 0;
