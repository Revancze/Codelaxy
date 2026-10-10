namespace Codelaxy.Git;

internal enum WorkingTreeEntryKind
{
    Missing,
    RegularFile,
    SymbolicLink,
    Directory,
    ReparsePoint,
}
