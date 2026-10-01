# wol_sender.ps1 - Native Windows Host Wake-on-LAN Sender
param(
    [string]$MacListJson,
    [string]$SingleMac,
    [string]$TargetIp
)

try {
    $items = @()
    if ($MacListJson) {
        try {
            $parsed = ConvertFrom-Json $MacListJson
            if ($parsed -is [Array]) {
                $items = $parsed
            } else {
                $items = @($parsed)
            }
        } catch {
            $items = @()
        }
    }
    if ($SingleMac) {
        $items += [PSCustomObject]@{ mac = $SingleMac; ip = $TargetIp }
    }

    if ($items.Count -eq 0) {
        Write-Output "NO_ITEMS"
        exit 0
    }

    $baseTargets = @("255.255.255.255")
    try {
        Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -notmatch '^127\.' -and $_.IPAddress -notmatch '^169\.254\.' } | ForEach-Object {
            $ipParts = $_.IPAddress.Split('.')
            if ($ipParts.Length -eq 4) {
                $baseTargets += "$($ipParts[0]).$($ipParts[1]).$($ipParts[2]).255"
            }
        }
    } catch {}

    $client = New-Object System.Net.Sockets.UdpClient
    $client.EnableBroadcast = $true

    $sentCount = 0
    foreach ($item in $items) {
        $rawMac = if ($item.mac) { $item.mac } elseif ($item -is [string]) { $item } else { "" }
        $tip = if ($item.ip) { $item.ip } else { "" }
        if (-not $rawMac) { continue }

        $cleanMac = $rawMac -replace '[^a-fA-F0-9]', ''
        if ($cleanMac.Length -ne 12) { continue }

        $hex = ("FF" * 6) + ($cleanMac * 16)
        $bytes = New-Object byte[] 102
        for ($i = 0; $i -lt 102; $i++) {
            $bytes[$i] = [Convert]::ToByte($hex.Substring($i * 2, 2), 16)
        }

        $targets = @($baseTargets)
        if ($tip -and $tip -match '^\d+\.\d+\.\d+\.\d+$') {
            $targets += $tip
            $p = $tip.Split('.')
            $targets += "$($p[0]).$($p[1]).$($p[2]).255"
        }

        $uniqueTargets = $targets | Select-Object -Unique

        foreach ($port in @(9, 7)) {
            foreach ($t in $uniqueTargets) {
                for ($k = 0; $k -lt 3; $k++) {
                    try {
                        [void]$client.Send($bytes, $bytes.Length, $t, $port)
                    } catch {}
                }
            }
        }
        $sentCount++
    }

    $client.Close()
    Write-Output "WOL_SENT_COUNT:$sentCount"
} catch {
    Write-Error $_.Exception.Message
    exit 1
}
