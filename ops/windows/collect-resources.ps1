param([string]$OutputDirectory)
$ErrorActionPreference='Stop'
$os=Get-CimInstance Win32_OperatingSystem
$cpus=@(Get-CimInstance Win32_Processor)
$hostInfo=Get-CimInstance Win32_ComputerSystem
$loads=@($cpus | Where-Object {$null -ne $_.LoadPercentage} | ForEach-Object {[double]$_.LoadPercentage})
$cpu=$null;if($loads.Count -gt 0){$cpu=($loads|Measure-Object -Average).Average}
$gpu=@();try{$gpu=@(& nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits 2>$null)}catch{}
$disks=@(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | ForEach-Object {@{name=$_.DeviceID;total=[double]$_.Size;free=[double]$_.FreeSpace;source='Host physical disk';status='connected'}})
try{
 $df=@(& docker exec mideagent-infra-objects-1 df -Pk /data 2>$null)
 if($LASTEXITCODE -eq 0 -and $df.Count -ge 2){$parts=($df[-1].Trim()-split '\s+');$disks+=@{name='Object storage';total=([double]$parts[1])*1024;free=([double]$parts[3])*1024;source='Connected object volume';status='connected'}}
}catch{$disks+=@{name='Object storage';source='Object volume';status='unavailable'}}
$now=[DateTimeOffset]::UtcNow
$value=@{observed_at=$now.ToString('o');observed_unix=$now.ToUnixTimeSeconds();nodes=@(@{id=$env:COMPUTERNAME;name='Execution PC';cpu_percent=$cpu;logical_processors=[int]$hostInfo.NumberOfLogicalProcessors;memory_total=([double]$os.TotalVisibleMemorySize)*1024;memory_available=([double]$os.FreePhysicalMemory)*1024;gpu=$gpu});storage=$disks}
$target=Join-Path $OutputDirectory 'resources.json';$tmp=Join-Path $OutputDirectory 'resources.next.json'
[IO.File]::WriteAllText($tmp,($value|ConvertTo-Json -Depth 6 -Compress),[Text.UTF8Encoding]::new($false))
Move-Item -LiteralPath $tmp -Destination $target -Force
