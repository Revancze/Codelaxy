// See https://aka.ms/new-console-template for more information
Console.WriteLine("Hello, World!");
if (args.Length != 1)
{
    return 2;
}

await File.WriteAllTextAsync(
    args[0],
    Environment.ProcessId.ToString());

await Task.Delay(Timeout.InfiniteTimeSpan);

return 0;