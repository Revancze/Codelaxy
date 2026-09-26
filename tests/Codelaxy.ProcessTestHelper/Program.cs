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
