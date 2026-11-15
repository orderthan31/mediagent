param([Parameter(Mandatory=$true)][string]$Launcher)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$root=Join-Path ([IO.Path]::GetDirectoryName($Launcher)) ('test space '+[Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($root)|Out-Null
function Write-Fixture([string]$name,[string]$content){
    $path=Join-Path $root $name
    [IO.File]::WriteAllText($path,$content,[Text.UTF8Encoding]::new($false))
    return $path
}
function Run-Fixture([string]$argument,[int]$expected){
    $start=[Diagnostics.ProcessStartInfo]::new();$start.FileName=$Launcher;$start.UseShellExecute=$false;$start.Arguments=$argument
    $process=[Diagnostics.Process]::Start($start)
    if(!$process.WaitForExit(20000)){throw 'Owned launcher fixture timed out'}
    if($process.ExitCode -ne $expected){throw ('Wrong exit status: '+$process.ExitCode+' expected '+$expected)}
    $process.Dispose()
}
$cases=@()
$bytes=[IO.File]::ReadAllBytes($Launcher);$pe=[BitConverter]::ToInt32($bytes,0x3c)
if([BitConverter]::ToUInt16($bytes,$pe+24+68) -ne 2){throw 'Console executable instead of GUI launcher'}
$cases+='GUI subsystem'
$probePath=Join-Path $root 'console-probe.json'
$probe=@'
$ErrorActionPreference='Stop'
Add-Type -TypeDefinition 'using System;using System.Runtime.InteropServices;public static class ConsoleProbe{[DllImport("kernel32.dll")]public static extern IntPtr GetConsoleWindow();[DllImport("user32.dll")]public static extern bool IsWindowVisible(IntPtr h);}'
$first=[ConsoleProbe]::GetConsoleWindow();$before=[ConsoleProbe]::IsWindowVisible($first)
& "$env:WINDIR\System32\cmd.exe" /d /c ver|Out-Null
$last=[ConsoleProbe]::GetConsoleWindow();$after=[ConsoleProbe]::IsWindowVisible($last)
[IO.File]::WriteAllText('__RESULT__',(@{before_handle=$first.ToInt64();before_visible=$before;after_handle=$last.ToInt64();after_visible=$after}|ConvertTo-Json),[Text.UTF8Encoding]::new($false))
exit 0
'@
$probe=$probe.Replace('__RESULT__',$probePath.Replace("'","''"))
$success=Write-Fixture 'successful observer.ps1' $probe
Run-Fixture ('"'+$success+'"') 0
$value=Get-Content -LiteralPath $probePath -Raw|ConvertFrom-Json
if($value.before_visible -or $value.after_visible){throw 'PowerShell/native child exposed a visible console'}
$cases+='hidden PowerShell and native child; quoted path'
$failure=Write-Fixture 'failed.ps1' '[Console]::Error.WriteLine("EXPECTED_TEST_ERROR");exit 7'
Run-Fixture ('"'+$failure+'"') 7
if(!([IO.File]::ReadAllText((Join-Path ([IO.Path]::GetDirectoryName($Launcher)) 'last-run.txt')).Contains('EXPECTED_TEST_ERROR'))){throw 'Failure diagnostics lost'}
$cases+='nonzero exit and error diagnostics'
Run-Fixture ('"'+(Join-Path $root 'missing.ps1')+'"') 66
$cases+='missing script rejected'
Run-Fixture '' 64
$cases+='missing argument rejected'
$pipes=Write-Fixture 'pipe-drain.ps1' '[Console]::Out.WriteLine(("x"*50000));[Console]::Error.WriteLine(("y"*50000));exit 0'
Run-Fixture ('"'+$pipes+'"') 0
if(([IO.File]::ReadAllText((Join-Path ([IO.Path]::GetDirectoryName($Launcher)) 'last-run.txt'))).Length -gt 17000){throw 'Diagnostics not bounded'}
$cases+='concurrent pipe drain and bounded diagnostics'
@{passed=$cases.Count;cases=$cases;console_probe=$value;fixture_directory=$root}|ConvertTo-Json -Depth 4 -Compress
