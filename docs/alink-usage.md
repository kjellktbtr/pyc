# alink usage
ALINK v1.6 (C) Copyright 1998-9 Anthony A.J. Williams.
All Rights Reserved

## Usage 
```
alink [file [file [...]]] [options]
```
    Each file may be an object file, a library, or a Win32 resource
    file. If no extension is specified, .obj is assumed. Modules are
    only loaded from library files if they are required to match an
    external reference.
    Options and files may be listed in any order, all mixed together.

The following options are permitted:
```
    @name   Load additional options from response file name
    -c      Enable Case sensitivity
    -c+     Enable Case sensitivity
    -c-     Disable Case sensitivity
    -p      Enable segment padding
    -p+     Enable segment padding
    -p-     Disable segment padding
    -m      Enable map file
    -m+     Enable map file
    -m-     Disable map file
    -h      Display this help list
    -H      "
    -?      "
    -L ddd  Add directory ddd to search list
    -o name Choose output file name
    -oXXX   Choose output format XXX
        Available options are:
            COM - MSDOS COM file
            EXE - MSDOS EXE file
            PE  - Win32 PE Executable
    -entry name   Use public symbol name as the entry point
```

Options for PE files:
```
    -base addr        Set base address of image
    -filealign addr   Set section alignment in file
    -objectalign addr Set section alignment in memory
    -subsys xxx       Set subsystem used
        Available options are:
            console   Select character mode
            con       "
            char      "
            windows   Select windowing mode
            win       "
            gui       "
            native    Select native mode
            posix     Select POSIX mode
    -subsysver x.y    Select subsystem version x.y
    -osver x.y        Select OS version x.y
    -stub xxx         Use xxx as the MSDOS stub
    -dll              Build DLL instead of EXE
    -stacksize xxx    Set stack size to xxx
    -stackcommitsize xxx Set stack commit size to xxx
    -heapsize xxx     Set heap size to xxx
    -heapcommitsize xxx Set heap commit size to xxx
```

Warning: Executing `alink` without arguments results in that it waits forever for the user to click enter twice. For executing alink with no arguments or `-h` for help do as follows: `printf "\n\n" | alink` to avoid getting stuck.