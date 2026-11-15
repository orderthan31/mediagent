param(
    [Parameter(Mandatory=$true)][string]$InstallDirectory,
    [Parameter(Mandatory=$true)][string]$WrapperPath,
    [string]$TaskName='Mideagent Resource Observer',
    [switch]$Apply
)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$source=Join-Path $PSScriptRoot 'ResourceObserverLauncher.cs'
$sourceHash=(Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
$directory=Join-Path $InstallDirectory ('launcher-'+$sourceHash.Substring(0,16))
$binary=Join-Path $directory 'Mideagent.ResourceObserver.exe'
$buildPath=Join-Path $directory 'build.json'
$wrapper=(Get-Item -LiteralPath $WrapperPath).FullName
if([IO.Path]::GetExtension($wrapper) -ne '.ps1'){throw 'Expected an existing PS1 wrapper'}
$task=Get-ScheduledTask -TaskName $TaskName -TaskPath '\'
if(@($task.Actions).Count -ne 1){throw 'Expected exactly one existing observer action'}
$originalActions=$task.Actions
$originalXml=[string](Export-ScheduledTask -TaskName $TaskName -TaskPath $task.TaskPath)
$originalWrapperHash=(Get-FileHash -LiteralPath $wrapper -Algorithm SHA256).Hash
[xml]$before=$originalXml
$compiler=Join-Path ([Environment]::GetFolderPath('Windows')) 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if(!(Test-Path -LiteralPath $compiler)){throw 'Existing Windows .NET Framework compiler not available'}
[IO.Directory]::CreateDirectory($directory)|Out-Null
if(Test-Path -LiteralPath $binary){
    $build=Get-Content -LiteralPath $buildPath -Raw|ConvertFrom-Json
    if($build.source_sha256 -ne $sourceHash -or $build.binary_sha256 -ne (Get-FileHash -LiteralPath $binary -Algorithm SHA256).Hash){throw 'Existing launcher build does not match its source manifest'}
}else{
    & $compiler /nologo /target:winexe /optimize+ ('/out:'+$binary) $source
    if($LASTEXITCODE -ne 0){throw 'Observer GUI launcher compilation failed'}
    $build=@{source_sha256=$sourceHash;binary_sha256=(Get-FileHash -LiteralPath $binary -Algorithm SHA256).Hash;target='winexe'}
    [IO.File]::WriteAllText($buildPath,($build|ConvertTo-Json),[Text.UTF8Encoding]::new($false))
}
$bytes=[IO.File]::ReadAllBytes($binary);$pe=[BitConverter]::ToInt32($bytes,0x3c)
if([BitConverter]::ToUInt16($bytes,$pe+24+68) -ne 2){throw 'Launcher must use the Windows GUI subsystem, not console subsystem'}
$tag=(Get-Date -Format 'yyyyMMddTHHmmss')+'-'+[Guid]::NewGuid().ToString('N').Substring(0,8)
$backup=Join-Path $directory ('task-before-'+$tag+'.xml')
[IO.File]::WriteAllText($backup,$originalXml,[Text.Encoding]::Unicode)
$actionArgs='"'+$wrapper+'"'
$actionParameters=@{Execute=$binary;Argument=$actionArgs}
if($task.Actions[0].WorkingDirectory){$actionParameters.WorkingDirectory=$task.Actions[0].WorkingDirectory}
$action=New-ScheduledTaskAction @actionParameters
$applied=$false
if($Apply){
    if([string]$task.State -eq 'Running'){throw 'Observer currently running; wait for its normal exit before applying'}
    try{
        Set-ScheduledTask -TaskName $TaskName -TaskPath $task.TaskPath -Action $action|Out-Null
        [xml]$after=[string](Export-ScheduledTask -TaskName $TaskName -TaskPath $task.TaskPath)
        foreach($section in @('Principals','Triggers','Settings','RegistrationInfo')){
            if($before.Task.$section.OuterXml -ne $after.Task.$section.OuterXml){throw ('Non-action task configuration changed: '+$section)}
        }
        $current=Get-ScheduledTask -TaskName $TaskName -TaskPath $task.TaskPath
        if($current.Actions[0].Execute -ne $binary -or $current.Actions[0].Arguments -ne $actionArgs){throw 'Observer action readback mismatch'}
        if((Get-FileHash -LiteralPath $wrapper -Algorithm SHA256).Hash -ne $originalWrapperHash){throw 'Original collector wrapper changed'}
        $applied=$true
    }catch{
        Set-ScheduledTask -TaskName $TaskName -TaskPath $task.TaskPath -Action $originalActions|Out-Null
        throw
    }
}
$result=@{task=$TaskName;binary=$binary;source_sha256=$sourceHash;binary_sha256=$build.binary_sha256;gui_subsystem=2;wrapper=$wrapper;wrapper_sha256=$originalWrapperHash;task_backup=$backup;applied=$applied;principal_triggers_settings_preserved=$true}
[IO.File]::WriteAllText((Join-Path $directory ('installation-'+$tag+'.json')),($result|ConvertTo-Json),[Text.UTF8Encoding]::new($false))
$result|ConvertTo-Json -Compress
