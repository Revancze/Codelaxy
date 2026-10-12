using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

namespace Codelaxy.Git;

// Reads filesystem identity only. It makes no trust decision.
internal static class WindowsFileIdentity
{
    private const uint ShareAll = 0x00000007;
    private const uint OpenExisting = 3;
    private const uint BackupSemantics = 0x02000000;
    private const int FileIdInfoClass = 18;

    [StructLayout(LayoutKind.Sequential)]
    internal readonly record struct Identity(
        ulong VolumeSerialNumber,
        ulong FileIdLow,
        ulong FileIdHigh
    );

    [StructLayout(LayoutKind.Sequential)]
    private struct NativeFileIdInfo
    {
        public ulong VolumeSerialNumber;
        public ulong FileIdLow;
        public ulong FileIdHigh;
    }

    internal static bool TryRead(string path, out Identity identity)
    {
        identity = default;

        if (!OperatingSystem.IsWindows() || string.IsNullOrWhiteSpace(path))
        {
            return false;
        }

        // Zero desired access permits metadata queries without reading
        // the contents. BackupSemantics also permits directory handles.
        using var handle = CreateFileW(
            path,
            0,
            ShareAll,
            IntPtr.Zero,
            OpenExisting,
            BackupSemantics,
            IntPtr.Zero
        );

        if (handle.IsInvalid)
        {
            return false;
        }

        if (
            !GetFileInformationByHandleEx(
                handle,
                FileIdInfoClass,
                out var native,
                (uint)Marshal.SizeOf<NativeFileIdInfo>()
            )
        )
        {
            return false;
        }

        identity = new Identity(native.VolumeSerialNumber, native.FileIdLow, native.FileIdHigh);

        return true;
    }

    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport(
        "kernel32.dll",
        EntryPoint = "CreateFileW",
        CharSet = CharSet.Unicode,
        ExactSpelling = true,
        SetLastError = true
    )]
    private static extern SafeFileHandle CreateFileW(
        string fileName,
        uint desiredAccess,
        uint shareMode,
        IntPtr securityAttributes,
        uint creationDisposition,
        uint flagsAndAttributes,
        IntPtr templateFile
    );

    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("kernel32.dll", ExactSpelling = true, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetFileInformationByHandleEx(
        SafeFileHandle handle,
        int informationClass,
        out NativeFileIdInfo information,
        uint bufferSize
    );
}
