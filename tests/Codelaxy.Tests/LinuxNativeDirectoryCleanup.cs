using System.Globalization;
using System.Runtime.InteropServices;

namespace Codelaxy.Tests;

internal static class LinuxNativeDirectoryCleanup
{
    private const int FtwPhysical = 1;
    private const int FtwDepth = 8;
    private const int ErrorNoEntry = 2; // Linux ENOENT

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate int VisitCallback(
        nint nativePath,
        nint statBuffer,
        int typeFlag,
        nint treeState
    );

    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport(
        "libc",
        EntryPoint = "nftw",
        CallingConvention = CallingConvention.Cdecl,
        SetLastError = true
    )]
    private static extern int WalkTree(
        nint path,
        VisitCallback callback,
        int descriptorLimit,
        int flags
    );

    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport(
        "libc",
        EntryPoint = "remove",
        CallingConvention = CallingConvention.Cdecl,
        SetLastError = true
    )]
    private static extern int RemoveEntry(nint nativePath);

    internal static void Delete(string directory) => Delete(directory, RemoveEntry);

    internal static void Delete(string directory, Func<nint, int> removeEntry)
    {
        ArgumentNullException.ThrowIfNull(removeEntry);

        if (!OperatingSystem.IsLinux())
        {
            throw new PlatformNotSupportedException();
        }

        var callbackError = 0;

        VisitCallback visitor = (nativePath, _, _, _) =>
        {
            if (removeEntry(nativePath) == 0)
            {
                return 0;
            }

            callbackError = Marshal.GetLastPInvokeError();
            return -1;
        };

        var nativeRoot = Marshal.StringToCoTaskMemUTF8(directory);

        try
        {
            var result = WalkTree(nativeRoot, visitor, 16, FtwPhysical | FtwDepth);

            var walkError = Marshal.GetLastPInvokeError();
            GC.KeepAlive(visitor);

            if (result != 0)
            {
                var error = callbackError != 0 ? callbackError : walkError;

                // A missing root is an acceptable cleanup outcome.
                // Do not suppress failures reported by the remove callback.
                if (callbackError == 0 && error == ErrorNoEntry && IsRootMissing(directory))
                {
                    return;
                }

                throw new IOException(
                    $"Native Linux cleanup failed (errno {error.ToString(CultureInfo.InvariantCulture)}): {directory}"
                );
            }
        }
        finally
        {
            Marshal.FreeCoTaskMem(nativeRoot);
        }
    }

    private static bool IsRootMissing(string directory)
    {
        try
        {
            // Check the root itself, not an entry inside the tree.
            // Unlike Directory.Exists, this preserves access errors.
            _ = File.GetAttributes(directory);
            return false;
        }
        catch (FileNotFoundException)
        {
            return true;
        }
        catch (DirectoryNotFoundException)
        {
            return true;
        }
    }
}
